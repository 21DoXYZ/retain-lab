"""Синк контактов из шины (Phase 4 каналы): события contact_update -> contacts.

Тенант шлёт через Server Events API:
  {"event_type": "contact_update", "client_user_id": "u_1",
   "meta": "{\"channel\":\"viber\",\"address\":\"380631112233\",\"consent\":true}"}

Идемпотентно: Replacing по (tenant, client_user_id, channel), версия = ts
события. Запуск - планировщиком вместе со stitch (ops_loop, :05).
"""

from __future__ import annotations

import json
import os

VALID_CHANNELS = {"sms", "viber", "whatsapp", "telegram"}


def _parse(meta: str) -> tuple[str, str, int, bool] | None:
    try:
        m = json.loads(meta)
    except ValueError:
        return None
    channel = str(m.get("channel", "")).lower()
    address = str(m.get("address", "")).strip()
    if channel not in VALID_CHANNELS or not address:
        return None
    # verified=False - легаси-payload без подписи (старый сниппет): такой
    # client_user_id мог назвать кто угодно. По умолчанию верим: события от
    # самого клиента (Server Events API) подписи не несут и не должны.
    return (channel, address, 1 if m.get("consent") else 0,
            bool(m.get("verified", True)))


def sync_contacts(client, tenant: str) -> int:
    rows = client.query(
        """
        SELECT client_user_id, meta, toString(ts)
        FROM retention.saas_events
        WHERE tenant_id = %(t)s AND event_type = 'contact_update'
          AND client_user_id != '' AND meta != ''
        """,
        parameters={"t": tenant},
    ).result_rows

    # НЕПОДПИСАННЫЙ payload из Telegram привязывается только к СУЩЕСТВУЮЩЕМУ
    # юзеру: иначе любой, кто узнал чужой id (или перебирает id), уводит чужие
    # уведомления в свой чат. Подписанные и клиентские события это не трогает.
    unverified = {cuid for cuid, meta, _ts in rows
                  if (p := _parse(meta)) and not p[3]}
    known_uids: set = set()
    if unverified:
        known_uids = {r[0] for r in client.query(
            """
            SELECT DISTINCT client_user_id FROM retention.identities_current
            WHERE tenant_id = %(t)s AND client_user_id != ''
            """,
            parameters={"t": tenant},
        ).result_rows}

    out, refused = [], 0
    for cuid, meta, ts in rows:
        p = _parse(meta)
        if not p:
            continue
        if not p[3] and cuid not in known_uids:
            refused += 1
            continue
        out.append([tenant, cuid, p[0], p[1], p[2], ts, ts])
    if refused:
        print(f"[contacts] tenant={tenant} отклонено неподписанных с "
              f"неизвестным uid: {refused}", flush=True)

    # Отписки без client_user_id (телеграмный /stop или блокировка бота знают
    # только chat_id): восстанавливаем юзера по уже известному адресу канала.
    orphan = client.query(
        """
        SELECT meta, toString(ts)
        FROM retention.saas_events
        WHERE tenant_id = %(t)s AND event_type = 'contact_update'
          AND client_user_id = '' AND meta != ''
        """,
        parameters={"t": tenant},
    ).result_rows
    if orphan:
        known = {(r[0], r[1]): r[2] for r in client.query(
            """
            SELECT channel, address, client_user_id
            FROM retention.contacts_current WHERE tenant_id = %(t)s
            """,
            parameters={"t": tenant},
        ).result_rows}
        for meta, ts in orphan:
            p = _parse(meta)
            if not p:
                continue
            cuid = known.get((p[0], p[1]), "")
            if cuid:
                out.append([tenant, cuid, p[0], p[1], p[2], ts, ts])

    if out:
        client.insert(
            "retention.contacts", out,
            column_names=["tenant_id", "client_user_id", "channel", "address",
                          "consent", "consent_ts", "updated_at"])
    return len(out)


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
    n = sync_contacts(client, tenant)
    print(f"[contacts] tenant={tenant} upserted={n}")


if __name__ == "__main__":
    main()
