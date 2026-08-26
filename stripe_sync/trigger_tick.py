"""Событийные триггеры: момент интента -> касание за минуты, не за сутки.

ЗАЧЕМ. Стадийные кампании (campaign_tick) думают циклами по 15 минут и
категориями («он в CONVERT»). Но покупка живёт в моментах: человек открыл
чекаут и закрыл, сжёг последний кредит, его карта истекает. Письмо про
брошенный чекаут в первый час конвертит в разы лучше, чем назавтра - это
самая проверенная механика конверсии в индустрии.

КАК. Триггерные кампании - ОБЫЧНЫЕ кампании конфига (T*_: тексты правятся
в CRM, статистика на /campaigns, uplift меряется как у всех), но:
  • entry_stage='TRIGGER' - ни у кого нет такой стадии, стадийное
    автозачисление молчит; зачисляет ЭТОТ джоб по условию-событию;
  • manual_audience=true - смена стадии не выкидывает, выход по шагам;
  • reentry_days кампании = кулдаун триггера (чекаут - раз в 7д, карта -
    раз в 30д): повторный вход раньше кулдауна блокирует сам движок.
После зачисления зовём campaign_tick.tick() - шаг 0 (delay 0) уходит СРАЗУ,
со всеми общими предохранителями: dry-run до автопилота, подавления,
частотный колпак, consent. Хвостовые шаги дальше ведёт штатный тик.

Запуск: TENANT_ID=<пространство> python trigger_tick.py (ops_loop, каждую
минуту; пустой прогон - одна пачка дешёвых запросов).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

# Условие: кому триггер должен сработать ПРЯМО СЕЙЧАС. Каждый SELECT обязан
# вернуть identity_id и (для журнала) stage-подобную пометку. Кулдаун здесь
# НЕ проверяется - им владеет reentry_days кампании в движке.
TRIGGERS: dict[str, str] = {
    # Регистрация 30 минут - 24 часа назад: даём транзакционному письму
    # продукта уйти первым, но ловим человека в самый горячий момент.
    # Окно 24ч отсекает исторические импорты (у них ts = давняя дата
    # регистрации); кулдаун кампании (reentry 3650д) = одно welcome навсегда.
    "T0_welcome": """
        SELECT identity_id FROM (
            SELECT identity_id, min(ts) AS first_signup
            FROM retention.saas_events_resolved
            WHERE tenant_id = %(t)s AND event_type = 'signup'
            GROUP BY identity_id
        ) WHERE first_signup BETWEEN now() - INTERVAL 24 HOUR
                                 AND now() - INTERVAL 30 MINUTE
    """,
    # Чекаут открыт 30+ минут назад (и не старше 48ч), оплата после него не
    # пришла, человек не платящий. 30 минут - чтобы не влезть в живую оплату.
    "T1_checkout_rescue": """
        SELECT ua.identity_id
        FROM (
            SELECT identity_id, max(ts) AS last_co
            FROM retention.saas_events_resolved
            WHERE tenant_id = %(t)s AND event_type = 'checkout_started'
              AND ts BETWEEN now() - INTERVAL 48 HOUR AND now() - INTERVAL 30 MINUTE
            GROUP BY identity_id
        ) co
        JOIN retention.user_actions ua
          ON ua.tenant_id = %(t)s AND ua.identity_id = co.identity_id
        WHERE ua.sub_status NOT IN ('active', 'past_due')
          AND co.identity_id NOT IN (
              SELECT identity_id FROM retention.saas_events_resolved
              WHERE tenant_id = %(t)s AND event_type = 'billing.invoice_paid'
                AND ts >= now() - INTERVAL 48 HOUR)
    """,
    # Баланс кредитов добит до <=3 за последние сутки - человек в потоке
    # упёрся в потолок. Самый горячий момент для апгрейда/докупки.
    "T2_credits_out": """
        SELECT identity_id FROM (
            SELECT identity_id,
                   argMax(JSONExtractFloat(meta, 'balance_after'), ts) AS bal,
                   max(ts) AS last_spend
            FROM retention.saas_events_resolved
            WHERE tenant_id = %(t)s AND event_type = 'credit_spend'
            GROUP BY identity_id
        ) WHERE bal <= 3 AND last_spend >= now() - INTERVAL 24 HOUR
    """,
    # NPS-пульс: ВОВЛЕЧЁННЫМ (5+ ценных действий, месяц с нами, активен на
    # неделе). Спрашивать оценку у того, кто не пользовался - мусорный сигнал.
    # Кулдаун 90 дней держит reentry_days кампании.
    "T4_nps": """
        SELECT ua.identity_id
        FROM retention.user_actions ua
        JOIN retention.user_event_features f
          ON f.tenant_id = ua.tenant_id AND f.identity_id = ua.identity_id
        WHERE ua.tenant_id = %(t)s
          AND f.generations_total >= 5
          AND f.first_seen <= now() - INTERVAL 30 DAY
          AND f.last_seen >= now() - INTERVAL 7 DAY
          AND ua.client_user_id != ''
    """,
    # Карта платящего истекает в ближайшие 14 дней - невольный отток,
    # который дешевле всего перехватить ДО фейла списания.
    "T3_card_expiring": """
        SELECT ua.identity_id
        FROM retention.card_expiry_current ce
        JOIN retention.user_actions ua
          ON ua.tenant_id = %(t)s AND ua.stripe_customer_id = ce.customer_id
        WHERE ce.tenant_id = %(t)s AND ce.days_to_expiry BETWEEN 0 AND 14
          AND ua.sub_status IN ('active', 'past_due')
    """,
}


def fire(client, tenant: str) -> dict[str, int]:
    """Зачислить сработавшие триггеры. Возвращает {campaign_id: новых}."""
    from campaign_tick import holdout_split, next_step_time

    import json as _json
    from pathlib import Path
    conf_path = Path(__file__).resolve().parent / "saas_campaigns.json"
    cfgs = _json.loads(conf_path.read_text())
    conf = cfgs.get(tenant) or cfgs.get("_default") or {}
    camps = {c["campaign_id"]: c for c in conf.get("campaigns", [])
             if str(c.get("entry_stage")) == "TRIGGER"}
    control_pct = int(conf.get("control_pct", 10))

    now = datetime.now(tz=timezone.utc)
    cols = ["tenant_id", "campaign_id", "identity_id", "control", "entry_stage",
            "step_idx", "next_step_at", "status", "enrolled_at", "updated_at"]
    out: dict[str, int] = {}

    for cid, sql in TRIGGERS.items():
        camp = camps.get(cid)
        if not camp:
            continue
        try:
            hits = [r[0] for r in client.query(
                sql, parameters={"t": tenant}).result_rows]
        except Exception as exc:  # noqa: BLE001 - один триггер не валит остальные
            print(f"[trigger] {tenant}: {cid} condition failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue
        if not hits:
            continue

        # кулдаун = reentry_days кампании: было зачисление в окне - молчим
        reentry = int(camp.get("reentry_days", 7))
        # ПОСЛЕДНЕЕ зачисление, не первое: campaign_enrollments_current даёт
        # enrolled_at = min() (первое за всю историю), и кулдаун по нему навсегда
        # оставался бы открытым для персистентных когорт (NPS/кредиты) - человек
        # перезачислялся бы каждый тик. Берём max(enrolled_at) прямо из базовой
        # таблицы (аудит 2026-08-26).
        recent = {r[0] for r in client.query(
            """
            SELECT identity_id FROM retention.campaign_enrollments
            WHERE tenant_id = %(t)s AND campaign_id = %(c)s
            GROUP BY identity_id
            HAVING max(enrolled_at) >= now() - INTERVAL %(d)s DAY
            """, parameters={"t": tenant, "c": cid, "d": reentry}).result_rows}
        fresh = [i for i in hits if i not in recent]
        if not fresh:
            continue

        first_at = next_step_time(camp.get("steps", []), now, 0)
        rows = []
        for ident in fresh:
            control = holdout_split(tenant, cid, ident, control_pct)
            rows.append([tenant, cid, ident, 1 if control else 0, "TRIGGER",
                        0, first_at, "active", now, now])
        client.insert("retention.campaign_enrollments", rows, column_names=cols)
        out[cid] = len(rows)
    return out


def main() -> None:
    import clickhouse_connect

    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID: джоб работает в пространстве клиента")
    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"))

    fired = fire(client, tenant)
    if fired:
        # шаг 0 уходит немедленно ШТАТНЫМ движком - все предохранители общие
        from campaign_tick import tick
        stats = tick(client, tenant)
        print(f"[trigger] tenant={tenant} fired={fired} tick={stats}", flush=True)
    # тишина - норма: триггеры срабатывают редко, лог не засоряем


if __name__ == "__main__":
    main()
