"""Скоринг-джоб Phase 2: фичи из ClickHouse → heur-v1 → retention.user_scores.

Запуск (ночной — cron в Phase 6; руками):
  docker compose ... run --rm stripe-webhook python scoring.py
Стадии НЕ пишет — их считает вьюха user_actions по live-данным (DUNNING
событийный). Джоб отвечает только за скоры.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from heuristics import VERSION, compute_scores

# Жизненный цикл тенанта для LTV: измеренная месячная отписка по когорте
# подписок + сколько месяцев мы её вообще наблюдаем + средний чек (для
# триалов). Доверяем замеру только от 3 уходов И 30 подписко-месяцев -
# иначе честный прайор (base_churn_m=None).
LIFECYCLE_QUERY = """
SELECT
    countIf(status IN ('canceled', 'incomplete_expired'))          AS churned,
    sum(greatest(1, dateDiff('month', created,
        if(status IN ('canceled', 'incomplete_expired')
           AND canceled_at IS NOT NULL, canceled_at, now()))))     AS sub_months,
    if(toUnixTimestamp(min(created)) = 0, 0,
       dateDiff('day', min(created), now()) / 30.0)                AS obs_months
FROM (
    -- базовый лог, не _current: вьюха схлопывает клиента до одной строки и
    -- прячет ушедшие подписки - когорту по ней не измерить
    SELECT subscription_id,
           argMax(status, updated_at)      AS status,
           argMax(canceled_at, updated_at) AS canceled_at,
           min(created_ts)                 AS created
    FROM retention.stripe_subscriptions
    WHERE tenant_id = %(t)s
    GROUP BY subscription_id)
"""

MIN_CHURNED = 3
MIN_SUB_MONTHS = 30


def tenant_lifecycle(client, tenant: str) -> dict:
    """ctx для compute_scores + сырьё замера (в knowledge для карточки)."""
    rows = client.query(LIFECYCLE_QUERY, parameters={"t": tenant}).result_rows
    churned, sub_months, obs = (rows[0] if rows else (0, 0, 0))
    churned, sub_months = int(churned or 0), float(sub_months or 0)
    obs = round(float(obs or 0), 2)      # дробные месяцы: подпискам может быть 8 дней

    base = None
    if churned >= MIN_CHURNED and sub_months >= MIN_SUB_MONTHS:
        base = round(churned / sub_months, 4)

    price_rows = client.query(
        "SELECT coalesce(avg(nullIf(toFloat64(mrr), 0)), 0) "
        "FROM retention.tenant_plans_current WHERE tenant_id = %(t)s",
        parameters={"t": tenant}).result_rows
    avg_price = float(price_rows[0][0] or 0) if price_rows else 0.0

    # ИЗМЕРЕННАЯ конверсия триала: доля СОЗРЕВШЕЙ когорты (аккаунту 14+
    # дней - триал успел прожить), которая стала платить. Ею leak-audit
    # оценивает мёртвые триалы в деньгах вместо «не знаем». Меньше 50
    # созревших - честный None, не выдумываем.
    conv = None
    try:
        r = client.query("""
            SELECT countIf(ua.sub_status IN ('active', 'past_due')), count()
            FROM retention.user_actions ua
            LEFT JOIN retention.user_event_features f
              ON f.tenant_id = ua.tenant_id AND f.identity_id = ua.identity_id
            WHERE ua.tenant_id = %(t)s
              AND toUnixTimestamp(f.first_seen) > 0
              AND f.first_seen <= now() - INTERVAL 14 DAY
            """, parameters={"t": tenant}).result_rows[0]
        matured = int(r[1] or 0)
        if matured >= 50:
            conv = round(int(r[0] or 0) / matured, 4)
    except Exception:  # noqa: BLE001 - замер опционален
        pass

    return {"base_churn_m": base, "obs_months": obs, "avg_price": avg_price,
            "churned": churned, "sub_months": round(sub_months, 1),
            "trial_conv": conv}

FEATURE_QUERY = """
SELECT
    i.identity_id                                   AS identity_id,
    coalesce(s.status, '')                          AS sub_status,
    coalesce(toFloat64(p.mrr), 0)                   AS plan_mrr,
    coalesce(toUInt32(p.monthly_tokens), 0)         AS monthly_tokens,
    coalesce(f.generations_total, 0)                AS generations_total,
    coalesce(f.generations_7d, 0)                   AS generations_7d,
    coalesce(f.generations_prev_7d, 0)              AS generations_prev_7d,
    coalesce(f.gen_days_this_month, 0)              AS gen_days_this_month,
    coalesce(f.paywall_views, 0)                    AS paywall_views,
    coalesce(f.checkout_starts, 0)                  AS checkout_starts,
    coalesce(f.cancel_flow_14d, 0)                  AS cancel_flow_14d,
    coalesce(f.tokens_spent_month, 0)               AS tokens_spent_month,
    if(f.last_seen IS NULL OR toUnixTimestamp(f.last_seen) = 0,
       999, dateDiff('day', f.last_seen, now()))    AS days_since_seen,
    if(f.first_seen IS NULL OR toUnixTimestamp(f.first_seen) = 0,
       0, dateDiff('day', f.first_seen, now()))     AS tenure_days,
    coalesce(f.support_tickets_30d, 0)              AS support_tickets_30d,
    coalesce(f.bug_reports_30d, 0)                  AS bug_reports_30d,
    coalesce(f.rage_clicks_7d, 0)                   AS rage_clicks_7d,
    coalesce(f.js_errors_7d, 0)                     AS js_errors_7d,
    coalesce(f.active_sec_7d, 0)                    AS active_sec_7d,
    coalesce(f.active_sec_prev_7d, 0)               AS active_sec_prev_7d,
    coalesce(f.pricing_visits, 0)                   AS pricing_visits,
    coalesce(f.downloads_14d, 0)                    AS downloads_14d,
    coalesce(f.inp_ms, 0)                           AS inp_ms,
    coalesce(f.apple_pay, 0)                        AS apple_pay,
    coalesce(f.last_payment_failed > f.last_invoice_paid, 0)    AS failed_recent,
    coalesce(f.last_cancel_scheduled > f.last_invoice_paid, 0)  AS cancel_scheduled
FROM retention.identities_current i
LEFT JOIN retention.stripe_subscriptions_current s
    ON i.tenant_id = s.tenant_id AND i.stripe_customer_id = s.customer_id
LEFT JOIN retention.user_event_features f
    ON i.tenant_id = f.tenant_id AND i.identity_id = f.identity_id
LEFT JOIN retention.tenant_plans_current p
    ON i.tenant_id = p.tenant_id AND s.plan_id = p.plan_id
WHERE i.tenant_id = %(t)s
"""


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
        database=os.environ.get("CH_DB", "retention"),
    )

    ctx = tenant_lifecycle(client, tenant)
    # замер цикла - в знания: карточка объясняет им, откуда взялся LTV
    from knowledge import save as kb_save
    kb_save(client, tenant, "lifecycle_measured",
            {**ctx, "version": VERSION}, "scoring")

    res = client.query(FEATURE_QUERY, parameters={"t": tenant})
    cols = res.column_names
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000")

    rows = []
    for r in res.result_rows:
        feat = dict(zip(cols, r))
        scores = compute_scores(feat, ctx)
        feat_json = {k: (str(v) if isinstance(v, datetime) else v)
                     for k, v in feat.items() if k != "identity_id"}
        feat_json["ltv_months"] = scores["ltv_months"]
        feat_json["ltv_basis"] = scores["ltv_basis"]
        rows.append([
            tenant, feat["identity_id"],
            scores["p_convert"], scores["p_churn"],
            scores["ltv_estimate"], scores["power_score"],
            scores["buy_intent"],
            json.dumps(feat_json, separators=(",", ":")),
            VERSION, now,
        ])

    if rows:
        client.insert(
            "retention.user_scores", rows,
            column_names=["tenant_id", "identity_id", "p_convert", "p_churn",
                          "ltv_estimate", "power_score", "buy_intent",
                          "features", "version", "scored_at"],
        )
    print(f"[scoring] tenant={tenant} version={VERSION} scored={len(rows)}")


if __name__ == "__main__":
    main()
