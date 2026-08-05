"""Telegram-апдейт -> событие contact_update шины (чистые функции, без Kafka).

Подключение юзера: клиент даёт диплинк t.me/<бот>?start=<client_user_id> -
Telegram присылает "/start <payload>", payload и есть client_user_id тенанта.
Отписка: /stop в чате или блокировка бота (my_chat_member: kicked) -> consent 0
(client_user_id пустой - contacts_sync восстановит его по адресу chat_id).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _ts(unix: int | None) -> str:
    if not unix:
        return ""
    return datetime.fromtimestamp(int(unix), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _event(tenant_id: str, update_id, chat_id, client_user_id: str,
           consent: bool, ts: str) -> dict:
    return {
        "event_id": f"tg-{tenant_id}-{update_id}",
        "tenant_id": tenant_id,
        "event_type": "contact_update",
        "client_user_id": client_user_id,
        "ts": ts or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "source": "telegram",
        "meta": json.dumps({"channel": "telegram", "address": str(chat_id),
                            "consent": consent}),
    }


def update_to_event(tenant_id: str, upd: dict) -> dict | None:
    """None - апдейт не про подписку (обычная переписка игнорируется)."""
    if not isinstance(upd, dict):
        return None
    uid = upd.get("update_id", "x")

    msg = upd.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = str(msg.get("text") or "").strip()
    if chat_id and text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        return _event(tenant_id, uid, chat_id, payload, True, _ts(msg.get("date")))
    if chat_id and text.lower().rstrip("@") in ("/stop", "stop"):
        return _event(tenant_id, uid, chat_id, "", False, _ts(msg.get("date")))

    mcm = upd.get("my_chat_member") or {}
    status = ((mcm.get("new_chat_member") or {}).get("status") or "")
    mcm_chat = (mcm.get("chat") or {}).get("id")
    if mcm_chat and status in ("kicked", "left"):
        return _event(tenant_id, uid, mcm_chat, "", False, _ts(mcm.get("date")))
    return None
