"""Планы тенанта: Stripe (цена) + ответ клиента (лимит) -> tenant_plans.

ПОЧЕМУ ЭТО НУЖНО. tenant_plans - вход для трёх вещей:
  • burn_rate = потрачено за месяц / monthly_tokens  -> стадия UPGRADE;
  • value_at_stake юзеров без активной подписки (CONVERT/ACTIVATE/WINBACK);
  • leak-audit: «мёртвые триалы» и «тихие отмены» в долларах.
Без таблицы всё это молча равно нулю: UPGRADE не срабатывает НИКОГДА, а
половина аудита утечек показывает $0.

ОТКУДА ДАННЫЕ (без выдумок):
  • mrr           - из Stripe: amount подписки, годовые делим на 12;
  • monthly_tokens - Stripe НЕ знает лимитов продукта. Берём из ответа
    клиента в опроснике (onboarding_answers.monthly_units) - его собственное
    заявление про типовой план. Нет ответа -> 0 (burn_rate останется 0,
    UPGRADE не сработает - честно, а не выдуманное число).

Запуск: планировщиком рядом со stitch (ops_loop, :05) и после бэкфила.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def plan_rows(subs: list, monthly_units: int, tenant: str, now: str) -> list:
    """Чистая функция: строки stripe_subscriptions_current -> строки tenant_plans.
    subs: (plan_id, amount, bill_interval). Годовой план -> mrr = amount/12."""
    out = []
    for plan_id, amount, interval in subs:
        if not plan_id:
            continue
        amt = float(amount or 0)
        mrr = round(amt / 12, 2) if str(interval) == "year" else round(amt, 2)
        out.append([tenant, str(plan_id), int(monthly_units or 0), mrr, now])
    return out


def sync_plans(client, tenant: str, monthly_units: int) -> int:
    subs = client.query(
        """
        SELECT plan_id,
               argMax(amount, updated_at)        AS amount,
               argMax(bill_interval, updated_at) AS bill_interval
        FROM retention.stripe_subscriptions
        WHERE tenant_id = %(t)s AND plan_id != ''
        GROUP BY plan_id
        """,
        parameters={"t": tenant},
    ).result_rows

    rows = plan_rows(subs, monthly_units, tenant, _now())
    if rows:
        client.insert(
            "retention.tenant_plans", rows,
            column_names=["tenant_id", "plan_id", "monthly_tokens", "mrr",
                          "updated_at"])
    return len(rows)


def main() -> None:
    import clickhouse_connect
    from saas_senders import load_tenant_channels

    tenant = os.environ.get("TENANT_ID", "hubcontent")
    answers = (load_tenant_channels(tenant) or {}).get("onboarding_answers") or {}
    monthly_units = int(answers.get("monthly_units") or 0)

    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )
    n = sync_plans(client, tenant, monthly_units)
    print(f"[plans] tenant={tenant} plans={n} monthly_units={monthly_units}"
          + ("" if monthly_units else "  (лимит не задан в опроснике -> UPGRADE не сработает)"))


if __name__ == "__main__":
    main()
