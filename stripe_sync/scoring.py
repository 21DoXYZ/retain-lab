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
    coalesce(f.rage_clicks_7d, 0)                   AS rage_clicks_7d,
    coalesce(f.js_errors_7d, 0)                     AS js_errors_7d,
    coalesce(f.active_sec_7d, 0)                    AS active_sec_7d,
    coalesce(f.active_sec_prev_7d, 0)               AS active_sec_prev_7d,
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

    res = client.query(FEATURE_QUERY, parameters={"t": tenant})
    cols = res.column_names
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000")

    rows = []
    for r in res.result_rows:
        feat = dict(zip(cols, r))
        scores = compute_scores(feat)
        feat_json = {k: (str(v) if isinstance(v, datetime) else v)
                     for k, v in feat.items() if k != "identity_id"}
        rows.append([
            tenant, feat["identity_id"],
            scores["p_convert"], scores["p_churn"],
            scores["ltv_estimate"], scores["power_score"],
            json.dumps(feat_json, separators=(",", ":")),
            VERSION, now,
        ])

    if rows:
        client.insert(
            "retention.user_scores", rows,
            column_names=["tenant_id", "identity_id", "p_convert", "p_churn",
                          "ltv_estimate", "power_score", "features", "version", "scored_at"],
        )
    print(f"[scoring] tenant={tenant} version={VERSION} scored={len(rows)}")


if __name__ == "__main__":
    main()
