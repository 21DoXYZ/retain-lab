"""Identity stitching: Stripe customer ↔ сниппет client_user_id по email_hash.

Правила (REBUILD-TASK §1.3, явные и простые):
  R1. Stripe-кастомер с email → identity по email_hash (canonical-ключ).
  R2. Ключ событий (client_user_id, email_hash) → та же identity по email_hash;
      client_user_id дописывается в неё.
  R3. Ключ событий со stripe_customer_id → identity этого кастомера.
  R4. client_user_id без email_hash и без stripe_customer_id → СВОЯ identity
      по cuid (uuid5 "cuid:<id>"): такой юзер должен быть видим (стадия,
      ACTIVATE-кампания, in-app баннер по client_user_id). Появится email -
      R2 сделает каноническую identity по email_hash, cuid-овая исчезнет при
      следующей пересборке.
  R5. Один client_user_id с двумя разными email_hash → выигрывает поздний по ts,
      прежняя пара уходит в unmatched (reason=conflicting_email).

identity_id = uuid5(NAMESPACE, "<tenant>:<email_hash>") — стабилен между
пересборками; без email_hash (только Stripe customer без email) —
uuid5("<tenant>:scus:<customer_id>").

Чистая логика — build_identities(); I/O (ClickHouse) — run_stitch()/main.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid5 DNS ns


@dataclass
class EventKey:
    """Уникальная комбинация идентификаторов, встреченная в saas_events."""
    client_user_id: str = ""
    email_hash: str = ""
    stripe_customer_id: str = ""
    email_norm: str = ""   # открытый адрес из СЕРВЕРНЫХ событий (не из браузера)
    last_ts: str = ""   # максимальный ts события с этой комбинацией


@dataclass
class Identity:
    tenant_id: str
    identity_id: str
    email_hash: str = ""
    email_norm: str = ""
    stripe_customer_id: str = ""
    client_user_id: str = ""
    sources: list[str] = field(default_factory=list)


def _iid(tenant_id: str, key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{tenant_id}:{key}"))


def build_identities(
    tenant_id: str,
    customers: list[dict[str, Any]],
    event_keys: list[EventKey],
) -> tuple[list[Identity], list[dict[str, Any]]]:
    """(identities, unmatched) из снимка Stripe-кастомеров и ключей событий."""
    by_hash: dict[str, Identity] = {}
    by_customer: dict[str, Identity] = {}
    unmatched: list[dict[str, Any]] = []

    # R1 — кастомеры Stripe задают канонические identity
    for c in customers:
        h = c.get("email_hash") or ""
        cid = c.get("customer_id") or ""
        if h:
            ident = by_hash.get(h) or Identity(
                tenant_id, _iid(tenant_id, h), email_hash=h,
                email_norm=c.get("email_norm") or "",
            )
            by_hash[h] = ident
        else:
            ident = Identity(tenant_id, _iid(tenant_id, f"scus:{cid}"))
            unmatched.append({
                "tenant_id": tenant_id, "source": "stripe",
                "key_type": "stripe_customer_id", "key_value": cid,
                "reason": "customer_without_email", "ts": c.get("updated_at") or "",
            })
        ident.stripe_customer_id = cid
        _add_source(ident, "stripe")
        if cid:
            by_customer[cid] = ident

    # identity по одному client_user_id (R4) - для юзеров без email и биллинга
    by_cuid: dict[str, Identity] = {}

    # R5 — конфликт client_user_id с несколькими email_hash: поздний побеждает
    latest_hash_for_cuid: dict[str, EventKey] = {}
    for k in event_keys:
        if not k.client_user_id or not k.email_hash:
            continue
        cur = latest_hash_for_cuid.get(k.client_user_id)
        if cur is None or k.last_ts > cur.last_ts:
            latest_hash_for_cuid[k.client_user_id] = k

    for k in event_keys:
        # R3 — прямой stripe_customer_id в событии
        if k.stripe_customer_id and k.stripe_customer_id in by_customer:
            ident = by_customer[k.stripe_customer_id]
            if k.client_user_id and not ident.client_user_id:
                ident.client_user_id = k.client_user_id
            _add_source(ident, "snippet" if k.client_user_id else "stripe")
            continue

        if k.email_hash:
            winner = latest_hash_for_cuid.get(k.client_user_id)
            if k.client_user_id and winner is not None and winner.email_hash != k.email_hash:
                unmatched.append({
                    "tenant_id": tenant_id, "source": "snippet",
                    "key_type": "client_user_id", "key_value": k.client_user_id,
                    "reason": "conflicting_email", "ts": k.last_ts,
                })
                continue
            # R2 — склейка/создание по email_hash
            ident = by_hash.get(k.email_hash) or Identity(
                tenant_id, _iid(tenant_id, k.email_hash), email_hash=k.email_hash,
            )
            by_hash[k.email_hash] = ident
            if k.client_user_id:
                ident.client_user_id = k.client_user_id
            # открытый адрес (серверное событие) - без него письма неоплатившим
            # юзерам невозможны: из хеша адрес не восстановить
            if k.email_norm and not ident.email_norm:
                ident.email_norm = k.email_norm
            # событие-мост (checkout.completed) несёт и customer: без бэкфила
            # кастомеров это единственный способ привязать billing-события
            if k.stripe_customer_id and not ident.stripe_customer_id:
                ident.stripe_customer_id = k.stripe_customer_id
                by_customer[k.stripe_customer_id] = ident
                _add_source(ident, "stripe")
            _add_source(ident, "snippet")
            continue

        # R4 — только client_user_id (юзер ещё не дал email и не платил).
        # Заводим СВОЮ identity по cuid: иначе такой юзер невидим системе -
        # нет стадии, нет ACTIVATE-кампании, нет in-app баннера (а он как раз
        # адресуется по client_user_id). Когда email появится, R2 создаст
        # каноническую identity по email_hash, а эта исчезнет на следующей
        # пересборке (джоб собирает всё заново).
        if k.client_user_id:
            if k.client_user_id in latest_hash_for_cuid:
                continue      # email у этого cuid уже есть - живёт по R2
            ident = by_cuid.get(k.client_user_id) or Identity(
                tenant_id, _iid(tenant_id, f"cuid:{k.client_user_id}"),
                client_user_id=k.client_user_id,
            )
            by_cuid[k.client_user_id] = ident
            _add_source(ident, "snippet")

    identities = list({id(i): i for i in [*by_hash.values(), *by_customer.values(),
                                          *by_cuid.values()]}.values())
    return identities, unmatched


def _add_source(ident: Identity, source: str) -> None:
    if source not in ident.sources:
        ident.sources.append(source)


# ── I/O: пересборка из ClickHouse ────────────────────────────────────────────

def run_stitch(client, tenant_id: str, now_ts: str) -> dict[str, int]:
    """Читает снимки из CH, пересобирает identities/unmatched, пишет обратно."""
    customers = [
        dict(zip(["customer_id", "email_norm", "email_hash", "updated_at"], r))
        for r in client.query(
            """
            SELECT customer_id,
                   argMax(email_norm, updated_at),
                   argMax(email_hash, updated_at),
                   toString(max(updated_at))
            FROM retention.stripe_customers
            WHERE tenant_id = %(t)s
            GROUP BY customer_id
            """,
            parameters={"t": tenant_id},
        ).result_rows
    ]
    event_keys = [
        EventKey(client_user_id=r[0], email_hash=r[1], stripe_customer_id=r[2],
                 email_norm=r[4] if len(r) > 4 else "", last_ts=r[3])
        for r in client.query(
            """
            SELECT client_user_id, email_hash, stripe_customer_id, toString(max(ts)),
                   argMax(email, ts) AS email_open
            FROM retention.saas_events
            WHERE tenant_id = %(t)s
              AND (client_user_id != '' OR email_hash != '' OR stripe_customer_id != '')
            GROUP BY client_user_id, email_hash, stripe_customer_id
            """,
            parameters={"t": tenant_id},
        ).result_rows
    ]

    identities, unmatched = build_identities(tenant_id, customers, event_keys)

    if identities:
        client.insert(
            "retention.identities",
            [[i.tenant_id, i.identity_id, i.email_hash, i.email_norm,
              i.stripe_customer_id, i.client_user_id, i.sources, now_ts, now_ts]
             for i in identities],
            column_names=["tenant_id", "identity_id", "email_hash", "email_norm",
                          "stripe_customer_id", "client_user_id", "sources",
                          "first_seen", "updated_at"],
        )
    if unmatched:
        client.insert(
            "retention.identity_unmatched",
            [[u["tenant_id"], u["source"], u["key_type"], u["key_value"],
              u["reason"], u["ts"] or now_ts]
             for u in unmatched],
            column_names=["tenant_id", "source", "key_type", "key_value", "reason", "ts"],
        )
    return {"identities": len(identities), "unmatched": len(unmatched)}


def main() -> None:
    import clickhouse_connect
    from datetime import datetime, timezone

    tenant_id = os.environ.get("TENANT_ID", "").strip()
    if not tenant_id_id:
        raise SystemExit("нужен TENANT_ID: джоб работает в пространстве клиента")
    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000")
    stats = run_stitch(client, tenant_id, now)
    print(f"[stitch] tenant={tenant_id} identities={stats['identities']} unmatched={stats['unmatched']}")


if __name__ == "__main__":
    main()
