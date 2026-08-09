"""Продуктовые события из экспорта клиента: использование, кредиты, планы.

ЗАЧЕМ. Сниппет видит браузер, Stripe видит деньги. Что человек ДЕЛАЕТ в
продукте (генерации, траты кредитов, смены планов) - видит только сам продукт.
Экспорт (см. connectors.export_rows) отдаёт это готовыми таблицами, и мы
превращаем их в обычные события конвейера - никаких особых путей:

  jobs                -> generation_completed / generation_failed
                         (главное value-действие: его уже ждёт скоринг)
  credit_transactions -> credit_spend / credit_grant (глубина использования)
  plan_changes        -> plan_change (апгрейд/даунгрейд - сигнал намерения)
  subscriptions       -> subscription_link (client_user_id ↔ stripe_customer_id
                         для склейки: у части юзеров связка есть только здесь)

ИЗМЕРЕННАЯ ЭКОНОМИКА. У jobs есть provider_cost_micro_usd - живые деньги
провайдерам. Из них считаем себестоимость кредита и валовую маржу ПО ФАКТУ
(выручка Stripe минус расходы за то же окно) и кладём в конфиг тенанта:
measured бьёт claimed (§9 методологии) - офферы перестают считаться по
догадкам владельца.

Инкрементально: since = максимальный ts уже загруженных событий датасета
минус люфт (джоб мог завершиться позже, чем создан). Идемпотентно: event_id
детерминирован по id строки, дубли гасит saas_events_deduped.

Запуск: TENANT_ID=<пространство> python product_sync.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

LOOKBACK_H = 48          # люфт инкремента: джоб завершается позже создания
MARGIN_WINDOW_D = 90     # окно измеренной экономики
COLUMNS = ["tenant_id", "event_id", "event_type", "ts", "client_user_id",
           "email_hash", "email", "source", "stripe_customer_id", "meta"]


def _ts(raw: str) -> str:
    """ISO из экспорта -> формат ClickHouse. Пусто - самое начало эпохи."""
    text = str(raw or "").strip().replace("T", " ").replace("Z", "")
    text = text.split("+")[0]
    return text[:23] if text else "1970-01-01 00:00:00.000"


def _meta(d: dict) -> str:
    clean = {k: v for k, v in d.items() if v not in (None, "")}
    return json.dumps(clean, separators=(",", ":"), ensure_ascii=False,
                      default=str) if clean else ""


def job_event(r: dict, tenant: str) -> list | None:
    """Джоб -> событие. Только завершённые: бегущий джоб догоним люфтом."""
    status = str(r.get("status") or "")
    if status == "done":
        etype = "generation_completed"
    elif status in ("failed", "error", "cancelled"):
        etype = "generation_failed"
    else:
        return None
    return [tenant, f"export:jobs:{r.get('id')}", etype,
            _ts(r.get("finished_at") or r.get("started_at") or r.get("created_at")),
            str(r.get("user_id") or ""), "", "", "product", "",
            _meta({"job_type": r.get("type"), "provider": r.get("provider"),
                   "credits_cost": r.get("credits_cost"),
                   "provider_cost_micro_usd": r.get("provider_cost_micro_usd"),
                   "status": status})]


def credit_event(r: dict, tenant: str) -> list | None:
    try:
        amount = float(r.get("amount") or 0)
    except (TypeError, ValueError):
        return None
    if amount == 0:
        return None
    return [tenant, f"export:ct:{r.get('id')}",
            "credit_spend" if amount < 0 else "credit_grant",
            _ts(r.get("created_at")), str(r.get("user_id") or ""), "", "",
            "product", "",
            _meta({"amount": amount, "reason": r.get("reason"),
                   "balance_after": r.get("balance_after")})]


def plan_change_event(r: dict, tenant: str) -> list | None:
    old, new = str(r.get("old_plan") or ""), str(r.get("new_plan") or "")
    if not new:
        return None
    return [tenant, f"export:pc:{r.get('id')}", "plan_change",
            _ts(r.get("changed_at") or r.get("created_at")),
            str(r.get("user_id") or ""), "", "", "product", "",
            _meta({"old_plan": old, "new_plan": new})]


def subscription_event(r: dict, tenant: str) -> list | None:
    """Не платёж (платежи ведёт Stripe) - СВЯЗКА user_id ↔ stripe_customer_id.

    У части юзеров она есть только здесь: users.stripe_customer_id пуст, а
    подписка знает обоих. Без неё платящий человек живёт двумя личностями.
    """
    uid, scid = str(r.get("user_id") or ""), str(r.get("stripe_customer_id") or "")
    if not uid or not scid:
        return None
    return [tenant, f"export:sub:{r.get('id')}", "subscription_link",
            _ts(r.get("created_at")), uid, "", "", "product", scid,
            _meta({"plan": r.get("plan"), "status": r.get("status"),
                   "seats": r.get("seats"),
                   "current_period_end": r.get("current_period_end")})]


def feedback_event(r: dict, tenant: str) -> list | None:
    """Обратная связь из продукта: категория (bug/complaint/idea) - сигнал
    фрустрации в скоринг и фильтры; текст обрезаем - карточке хватит начала."""
    uid = str(r.get("user_id") or "")
    if not uid:
        return None
    return [tenant, f"export:fb:{r.get('id')}", "feedback",
            _ts(r.get("created_at")), uid, "", "", "product", "",
            _meta({"category": r.get("category"),
                   "message": str(r.get("message") or "")[:300],
                   "page": r.get("page")})]


def support_event(r: dict, tenant: str) -> list | None:
    """Тикет поддержки: сам факт обращения - ранний предиктор оттока."""
    uid = str(r.get("user_id") or "")
    if not uid:
        return None
    return [tenant, f"export:sc:{r.get('conversation_id')}", "support_ticket",
            _ts(r.get("created_at")), uid, "", "", "product", "",
            _meta({"updated_at": r.get("updated_at"),
                   "last_operator_reply_at": r.get("last_operator_reply_at")})]


DATASETS = {
    "jobs": job_event,
    "credit_transactions": credit_event,
    "plan_changes": plan_change_event,
    "subscriptions": subscription_event,
    "feedback": feedback_event,
    "support_conversations": support_event,
}
_PREFIX = {"jobs": "export:jobs:", "credit_transactions": "export:ct:",
           "plan_changes": "export:pc:", "subscriptions": "export:sub:",
           "feedback": "export:fb:", "support_conversations": "export:sc:"}


def last_ts(client, tenant: str, dataset: str) -> str:
    """С какого момента добирать: максимум ts загруженного минус люфт."""
    row = client.query(
        "SELECT max(ts) FROM retention.saas_events "
        "WHERE tenant_id = %(t)s AND event_id LIKE %(p)s",
        parameters={"t": tenant, "p": _PREFIX[dataset] + "%"}).result_rows
    top = row[0][0] if row and row[0] and row[0][0] else None
    if not top or str(top).startswith("1970"):
        return ""
    return (top - timedelta(hours=LOOKBACK_H)).strftime("%Y-%m-%dT%H:%M:%S")


def measured_costs(client, tenant: str) -> dict | None:
    """Экономика по факту за окно: себестоимость кредита и валовая маржа.

    Себестоимость = живые деньги провайдерам / потраченные кредиты (из jobs,
    по ВСЕМ юзерам: цена генерации одна и та же). Маржа = (выручка Stripe -
    расходы на ПЛАТЯЩИХ) / выручка: триальный burn - это расход на привлечение,
    мешать его в маржу платящего клиента - значит запретить все офферы разом.
    Мало данных (<20 джобов или нулевая выручка) - маржу не выдумываем.

    Дедуп по event_id внутри: инкремент с люфтом кладёт часть событий дважды.
    """
    rows = client.query(
        "SELECT count(), sum(c), sum(cr), sumIf(c, paying) FROM ("
        "  SELECT event_id,"
        "         any(JSONExtractFloat(meta, 'provider_cost_micro_usd')) / 1e6 AS c,"
        "         any(JSONExtractFloat(meta, 'credits_cost')) AS cr,"
        "         any(client_user_id) IN ("
        "           SELECT DISTINCT client_user_id FROM retention.saas_events"
        "           WHERE tenant_id = %(t)s AND stripe_customer_id != ''"
        "             AND client_user_id != '') AS paying,"
        "         max(ts) AS mts"
        "  FROM retention.saas_events"
        "  WHERE tenant_id = %(t)s AND event_type = 'generation_completed'"
        "    AND source = 'product'"
        "  GROUP BY event_id) WHERE mts >= now() - INTERVAL %(d)s DAY",
        parameters={"t": tenant, "d": MARGIN_WINDOW_D}).result_rows
    jobs, cost_usd, credits, cost_paying = (rows[0] if rows else (0, 0, 0, 0))
    jobs, cost_usd = int(jobs or 0), float(cost_usd or 0)
    credits, cost_paying = float(credits or 0), float(cost_paying or 0)
    if jobs < 20:
        return None

    out = {"measured_jobs": jobs, "measured_window_days": MARGIN_WINDOW_D,
           "measured_provider_cost_usd": round(cost_usd, 2),
           "measured_paying_cost_usd": round(cost_paying, 2),
           "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
    if credits > 0:
        out["measured_unit_cost_usd"] = round(cost_usd / credits, 6)

    rev = client.query(
        "SELECT sum(amount_paid) FROM retention.stripe_invoices "
        "WHERE tenant_id = %(t)s AND created_ts >= now() - INTERVAL %(d)s DAY",
        parameters={"t": tenant, "d": MARGIN_WINDOW_D}).result_rows
    revenue = float(rev[0][0] or 0) if rev and rev[0] else 0.0
    if revenue > 0:
        out["measured_revenue_usd"] = round(revenue, 2)
        out["measured_margin_pct"] = round(
            max(0.0, (revenue - cost_paying) / revenue) * 100, 1)
    return out


def main() -> None:
    import clickhouse_connect

    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID: джоб работает в пространстве клиента")

    from connectors import export_rows
    from saas_senders import load_tenant_channels

    source = (load_tenant_channels(tenant) or {}).get("users_source") or {}
    if source.get("kind") != "export":
        print(f"[product_sync] tenant={tenant} экспорт не подключён - пропуск", flush=True)
        return

    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"))

    report = {}
    for dataset, mapper in DATASETS.items():
        try:
            raw = export_rows(source["url"], source["key"], dataset,
                              since=last_ts(client, tenant, dataset))
        except Exception as exc:  # noqa: BLE001 - один датасет не валит остальные
            report[dataset] = f"err:{type(exc).__name__}"
            continue
        events = [e for e in (mapper(r, tenant) for r in raw) if e]
        if events:
            client.insert("retention.saas_events", events, column_names=COLUMNS)
        report[dataset] = f"{len(events)}/{len(raw)}"

    measured = measured_costs(client, tenant)
    if measured:
        # в знания (ClickHouse), не в tenants.json: /secrets у джобов read-only,
        # и это данные, а не секрет - им место рядом с brief и economics
        try:                            # борд импортирует пакетом, джобы плоско
            from knowledge import save as kb_save
        except ImportError:
            from stripe_sync.knowledge import save as kb_save  # type: ignore
        kb_save(client, tenant, "measured_costs", measured, "product_sync")
    print(f"[product_sync] tenant={tenant} {report} "
          f"measured={'да' if measured else 'мало данных'}", flush=True)


if __name__ == "__main__":
    main()
