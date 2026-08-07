"""Восстановление снапшотов подписок из уже принятых событий.

ЗАЧЕМ. Событие в шине и снимок объекта - две разные записи. Если вставка
снимка когда-то не удалась (например, Stripe поменял формат и поле периода
уехало внутрь позиций), событие в базе есть, а подписки нет: стадии, MRR и
аудит утечек молчат. Джоб добирает недостающие подписки из событий.

Период, если его в событии не было, берём от времени самого события и шага
тарифа - для только что созданной подписки это ровно её период.

Запуск: TENANT_ID=<пространство> python resnapshot.py
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def missing_rows(events: list, known: set, now: datetime) -> list:
    """События подписок без снимка -> строки для stripe_subscriptions."""
    out, seen = [], set()
    for (sub_id, cust, status, plan, price, amount, interval, ts) in events:
        if not sub_id or sub_id in known or sub_id in seen:
            continue
        seen.add(sub_id)
        start = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        step = timedelta(days=365 if str(interval) == "year" else 30)
        out.append([
            os.environ.get("TENANT_ID", ""), str(sub_id), str(cust),
            str(status or "active"), str(plan or ""), str(price or ""),
            float(amount or 0), "usd", str(interval or "month"),
            _fmt(start), _fmt(start + step), _fmt(start), _fmt(now),
        ])
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
        database=os.environ.get("CH_DB", "retention"),
    )
    known = {r[0] for r in client.query(
        "SELECT DISTINCT subscription_id FROM retention.stripe_subscriptions "
        "WHERE tenant_id = %(t)s", parameters={"t": tenant}).result_rows}
    events = client.query(
        """
        SELECT subscription_id,
               argMax(stripe_customer_id, ts) AS customer_id,
               argMax(status, ts)             AS status,
               argMax(plan_id, ts)            AS plan_id,
               argMax(JSONExtractString(meta, 'price_id'), ts) AS price_id,
               argMax(toFloat64(amount), ts)  AS amount,
               argMax(JSONExtractString(meta, 'interval'), ts) AS bill_interval,
               max(ts)                        AS last_ts
        FROM retention.saas_events
        WHERE tenant_id = %(t)s AND subscription_id != ''
          AND event_type LIKE 'billing.subscription%%'
        GROUP BY subscription_id
        """, parameters={"t": tenant}).result_rows

    rows = missing_rows(events, known, datetime.now(tz=timezone.utc))
    if rows:
        client.insert(
            "retention.stripe_subscriptions", rows,
            column_names=["tenant_id", "subscription_id", "customer_id", "status",
                          "plan_id", "price_id", "amount", "currency",
                          "bill_interval", "current_period_start",
                          "current_period_end", "created_ts", "updated_at"])
    print(f"[resnapshot] tenant={tenant} восстановлено подписок={len(rows)}")


if __name__ == "__main__":
    main()
