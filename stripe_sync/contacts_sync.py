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


def _parse(meta: str) -> tuple[str, str, int] | None:
    try:
        m = json.loads(meta)
    except ValueError:
        return None
    channel = str(m.get("channel", "")).lower()
    address = str(m.get("address", "")).strip()
    if channel not in VALID_CHANNELS or not address:
        return None
    return channel, address, 1 if m.get("consent") else 0


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

    out = []
    for cuid, meta, ts in rows:
        p = _parse(meta)
        if p:
            out.append([tenant, cuid, p[0], p[1], p[2], ts, ts])

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

    tenant = os.environ.get("TENANT_ID", "hubcontent")
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
