"""Выдача оффера: гигиена → holdout → исполнение → лог. CLI для ручных прогонов;
из цепочек (Phase 4) вызывается issue_offer().

  python issue.py --offer O2_discount20 --email user5@example.test [--campaign K3]
  python issue.py --offer O1_tokens_100 --identity <uuid> --control-pct 100

Каждое решение — строка в retention.offers_issued (issued/dry_run/holdout/rejected).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from executors import ExecConfig, execute
from hygiene import holdout_split, run_checks

CATALOG_PATH = Path(__file__).parent / "offers_catalog.json"


def load_catalog(tenant_id: str) -> dict:
    data = json.loads(CATALOG_PATH.read_text())
    if tenant_id not in data:
        raise SystemExit(f"нет каталога офферов для тенанта {tenant_id}")
    # правки щедрости/лимитов из CRM (runtime-файл, мерж без деплоя)
    from overrides import load_tenant as load_overrides, merge_catalog
    return merge_catalog(data[tenant_id], load_overrides(tenant_id))


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _log(client, tenant_id: str, offer: dict, user: dict, campaign_id: str,
         holdout: bool, status: str, reason: str) -> None:
    client.insert(
        "retention.offers_issued",
        [[tenant_id, offer["offer_id"], user["identity_id"], campaign_id,
          1 if holdout else 0, 1 if offer.get("monetary") else 0,
          offer["executor"], json.dumps(offer["params"], separators=(",", ":")),
          status, reason, float(offer.get("cost_estimate") or 0.0), _now()]],
        column_names=["tenant_id", "offer_id", "identity_id", "campaign_id",
                      "holdout", "monetary", "executor", "params", "status",
                      "reason", "cost_estimate", "issued_at"],
    )


def issue_offer(client, tenant_id: str, identity_id: str, offer_id: str,
                campaign_id: str = "manual", control_pct: int | None = None,
                cfg: ExecConfig | None = None) -> tuple[str, str]:
    """Возвращает (status, reason) — то же, что записано в offers_issued."""
    catalog = load_catalog(tenant_id)
    offer = next((o for o in catalog["offers"] if o["offer_id"] == offer_id), None)
    if offer is None:
        raise SystemExit(f"оффер {offer_id} не найден в каталоге {tenant_id}")

    rows = client.query(
        """
        SELECT identity_id, client_user_id, stripe_customer_id, sub_status,
               coalesce(p_convert, 0) AS p_convert
        FROM retention.user_actions
        WHERE tenant_id = %(t)s AND identity_id = %(i)s
        """,
        parameters={"t": tenant_id, "i": identity_id},
    ).result_rows
    if not rows:
        raise SystemExit(f"identity {identity_id} не найдена в user_actions")
    user = dict(zip(["identity_id", "client_user_id", "stripe_customer_id",
                     "sub_status", "p_convert"], rows[0]))

    # subscription_id для Stripe-исполнителей
    sub = client.query(
        "SELECT subscription_id FROM retention.stripe_subscriptions_current "
        "WHERE tenant_id = %(t)s AND customer_id = %(c)s",
        parameters={"t": tenant_id, "c": user["stripe_customer_id"]},
    ).result_rows
    user["subscription_id"] = sub[0][0] if sub else ""

    history = [dict(zip(["offer_id", "monetary", "status", "issued_at"], r))
               for r in client.query(
                   """
                   SELECT offer_id, monetary, status, toString(issued_at)
                   FROM retention.offers_issued
                   WHERE tenant_id = %(t)s AND identity_id = %(i)s
                     AND issued_at >= now() - INTERVAL 30 DAY
                   """,
                   parameters={"t": tenant_id, "i": identity_id},
               ).result_rows]
    h14 = [r for r in history if r["issued_at"] >= _cutoff_14d()]

    ok, reason = run_checks(offer, user, h14, history,
                            float(catalog.get("p_convert_cap", 0.7)))
    if not ok:
        _log(client, tenant_id, offer, user, campaign_id, False, "rejected", reason)
        return "rejected", reason

    pct = catalog.get("control_pct", 10) if control_pct is None else control_pct
    if holdout_split(tenant_id, campaign_id, identity_id, int(pct)):
        _log(client, tenant_id, offer, user, campaign_id, True, "holdout", "")
        return "holdout", ""

    cfg = cfg or ExecConfig.from_env()
    exec_ok, detail = execute(offer, user, tenant_id, cfg)
    status = "dry_run" if (exec_ok and detail == "dry_run") else ("issued" if exec_ok else "rejected")
    _log(client, tenant_id, offer, user, campaign_id, False, status,
         "" if exec_ok else detail)
    return status, "" if exec_ok else detail


def _cutoff_14d() -> str:
    from datetime import timedelta
    return (datetime.now(tz=timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    import clickhouse_connect

    ap = argparse.ArgumentParser()
    ap.add_argument("--offer", required=True)
    ap.add_argument("--identity")
    ap.add_argument("--email", help="email_norm вместо identity_id")
    ap.add_argument("--campaign", default="manual")
    ap.add_argument("--control-pct", type=int, default=None)
    args = ap.parse_args()

    tenant = os.environ.get("TENANT_ID", "hubcontent")
    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )

    identity = args.identity
    if not identity:
        if not args.email:
            raise SystemExit("нужен --identity или --email")
        rows = client.query(
            "SELECT identity_id FROM retention.identities_current "
            "WHERE tenant_id = %(t)s AND email_norm = %(e)s",
            parameters={"t": tenant, "e": args.email},
        ).result_rows
        if not rows:
            raise SystemExit(f"identity для {args.email} не найдена")
        identity = rows[0][0]

    status, reason = issue_offer(client, tenant, identity, args.offer,
                                 args.campaign, args.control_pct)
    print(f"[issue] offer={args.offer} identity={identity} -> {status}"
          + (f" ({reason})" if reason else ""))


if __name__ == "__main__":
    main()
