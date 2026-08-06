"""One-time backfill Stripe → ClickHouse (stripe_* raw), затем identity stitching.

Режимы:
  реальный:  STRIPE_API_KEY=sk_... python backfill.py            (read-only запросы)
  мок:       python backfill.py --mock 40 [--seed 7]             (без ключа/сети)

Мок генерит согласованный мир: кастомеры с email → подписки (trialing/active/
past_due/canceled) → инвойсы (paid/open) — достаточно для проверки витрин
(mrr_facts) и склейки. Идемпотентно: ReplacingMergeTree по updated_at.
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta, timezone

from mapper import email_hash, normalize_email, ts_str
from stitch import run_stitch

PLANS = [("starter_monthly", 1900, "month"), ("pro_monthly", 4900, "month"),
         ("agency_yearly", 149900, "year")]
SUB_STATUSES = ["active", "active", "active", "trialing", "past_due", "canceled"]


def _client():
    import clickhouse_connect
    return clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000")


# ── МОК ──────────────────────────────────────────────────────────────────────

def mock_world(tenant: str, n: int, seed: int) -> dict[str, list[list]]:
    rng = random.Random(seed)
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    now = _now()
    customers, subs, invoices = [], [], []

    for i in range(1, n + 1):
        cid = f"cus_mock{i:04d}"
        email = f"user{i}@example.test"
        created = base + timedelta(days=rng.randint(0, 60), minutes=rng.randint(0, 1440))
        customers.append([tenant, cid, email, normalize_email(email), email_hash(email),
                          f"Mock User {i}", ts_str(created.timestamp()), "{}", now])

        plan, cents, interval = rng.choice(PLANS)
        status = rng.choice(SUB_STATUSES)
        sub_id = f"sub_mock{i:04d}"
        period_start = created + timedelta(days=3)
        period_end = period_start + timedelta(days=365 if interval == "year" else 30)
        trial_end = period_start + timedelta(days=7) if status == "trialing" else None
        canceled_at = period_start + timedelta(days=rng.randint(5, 40)) if status == "canceled" else None
        subs.append([tenant, sub_id, cid, status, plan, f"price_{plan}", cents / 100.0,
                     "usd", interval, ts_str(period_start.timestamp()), ts_str(period_end.timestamp()),
                     ts_str(trial_end.timestamp()) if trial_end else None,
                     ts_str(trial_end.timestamp()) if trial_end else None,
                     None, ts_str(canceled_at.timestamp()) if canceled_at else None,
                     ts_str(created.timestamp()), now])

        inv_status = "open" if status == "past_due" else "paid"
        invoices.append([tenant, f"in_mock{i:04d}", cid, sub_id, inv_status,
                         cents / 100.0, 0.0 if inv_status == "open" else cents / 100.0,
                         "usd", 2 if inv_status == "open" else 1, None,
                         ts_str(period_start.timestamp()), now])

    return {"stripe_customers": customers, "stripe_subscriptions": subs,
            "stripe_invoices": invoices}


# ── РЕАЛЬНЫЙ STRIPE (read-only) ──────────────────────────────────────────────

def fetch_stripe(tenant: str) -> dict[str, list[list]]:
    import stripe
    stripe.api_key = os.environ["STRIPE_API_KEY"]
    now = _now()
    out: dict[str, list[list]] = {"stripe_customers": [], "stripe_subscriptions": [],
                                  "stripe_invoices": [], "stripe_charges": []}

    for c in stripe.Customer.list(limit=100).auto_paging_iter():
        out["stripe_customers"].append([
            tenant, c.id, c.email or "", normalize_email(c.email), email_hash(c.email),
            c.name or "", ts_str(c.created), "{}", now])

    for s in stripe.Subscription.list(status="all", limit=100).auto_paging_iter():
        item = s["items"]["data"][0] if s["items"]["data"] else None
        price = item["price"] if item else {}
        out["stripe_subscriptions"].append([
            tenant, s.id, s.customer, s.status,
            price.get("lookup_key") or price.get("nickname") or price.get("id", ""),
            price.get("id", ""), (price.get("unit_amount") or 0) / 100.0,
            (price.get("currency") or "").lower(),
            (price.get("recurring") or {}).get("interval", ""),
            ts_str(s.current_period_start), ts_str(s.current_period_end),
            ts_str(s.trial_start) or None, ts_str(s.trial_end) or None,
            ts_str(s.cancel_at) or None, ts_str(s.canceled_at) or None,
            ts_str(s.created), now])

    for inv in stripe.Invoice.list(limit=100).auto_paging_iter():
        out["stripe_invoices"].append([
            tenant, inv.id, inv.customer or "", inv.subscription or "", inv.status or "",
            (inv.amount_due or 0) / 100.0, (inv.amount_paid or 0) / 100.0,
            (inv.currency or "").lower(), inv.attempt_count or 0,
            ts_str(inv.next_payment_attempt) or None, ts_str(inv.created), now])

    for ch in stripe.Charge.list(limit=100).auto_paging_iter():
        out["stripe_charges"].append([
            tenant, ch.id, ch.customer or "", ch.invoice or "",
            (ch.amount or 0) / 100.0, (ch.currency or "").lower(), ch.status or "",
            1 if ch.refunded else 0, ts_str(ch.created), now])

    return out


COLUMNS = {
    "stripe_customers": ["tenant_id", "customer_id", "email", "email_norm", "email_hash",
                         "name", "created_ts", "meta", "updated_at"],
    "stripe_subscriptions": ["tenant_id", "subscription_id", "customer_id", "status",
                             "plan_id", "price_id", "amount", "currency", "bill_interval",
                             "current_period_start", "current_period_end", "trial_start",
                             "trial_end", "cancel_at", "canceled_at", "created_ts", "updated_at"],
    "stripe_invoices": ["tenant_id", "invoice_id", "customer_id", "subscription_id", "status",
                        "amount_due", "amount_paid", "currency", "attempt_count",
                        "next_payment_attempt", "created_ts", "updated_at"],
    "stripe_charges": ["tenant_id", "charge_id", "customer_id", "invoice_id", "amount",
                       "currency", "status", "refunded", "created_ts", "updated_at"],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", type=int, metavar="N", help="сгенерировать N мок-кастомеров")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID: джоб работает в пространстве клиента")
    if args.mock:
        world = mock_world(tenant, args.mock, args.seed)
    elif os.environ.get("STRIPE_API_KEY"):
        world = fetch_stripe(tenant)
    else:
        raise SystemExit("нужен STRIPE_API_KEY либо --mock N")

    client = _client()
    for table, rows in world.items():
        if rows:
            client.insert(f"retention.{table}", rows, column_names=COLUMNS[table])
        print(f"[backfill] {table}: +{len(rows)}")

    stats = run_stitch(client, tenant, _now())
    print(f"[backfill] stitch: identities={stats['identities']} unmatched={stats['unmatched']}")


if __name__ == "__main__":
    main()
