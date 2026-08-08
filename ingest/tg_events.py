"""Telegram-апдейт -> событие contact_update шины (чистые функции, без Kafka).

Подключение юзера: диплинк t.me/<бот>?start=<payload>. Payload двух видов:
  s<base64url(uid)>_<hmac10> - ПОДПИСАННЫЙ (ссылки, которые генерируем мы:
      письма, in-app, inbox). Подпись проверяется здесь - в событие уходит
      verified=true.
  голый uid                  - легаси от старых сниппетов: без подписи любой,
      кто узнал чужой id, увёл бы чужие уведомления в свой чат. Уходит с
      verified=false, contacts_sync примет его только если uid существует в
      базе тенанта.
Отписка: /stop в чате или блокировка бота (my_chat_member: kicked) -> consent 0
(client_user_id пустой - contacts_sync восстановит его по адресу chat_id).

ЗЕРКАЛО. Разбор payload продублирован из stripe_sync/telegram_connect.py:
шлюз собирается из ./ingest и stripe_sync не видит. Паритет держит тест
test_telegram_connect.py::test_ingest_mirror_stays_in_sync.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone

UNSUB_SECRET = (os.environ.get("UNSUB_SECRET")
                or os.environ.get("SUPABASE_JWT_SECRET") or "")
PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SIGNED_RE = re.compile(r"^s([A-Za-z0-9_-]+)_([0-9a-f]{10})$")


def _sig(tenant: str, uid: str) -> str:
    return hmac.new(UNSUB_SECRET.encode(), f"tg|{tenant}|{uid}".encode(),
                    hashlib.sha256).hexdigest()[:10]


def parse_start(tenant: str, payload: str) -> tuple[str, str]:
    """payload -> (uid, 'signed'|'legacy') либо ('', причина)."""
    payload = str(payload or "").strip()
    if not payload:
        return "", "empty"
    signed = SIGNED_RE.match(payload)
    if signed:
        try:
            raw = signed.group(1)
            uid = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
        except Exception:
            return "", "bad_encoding"
        if not hmac.compare_digest(signed.group(2), _sig(tenant, uid)):
            return "", "bad_signature"
        return uid, "signed"
    if PAYLOAD_RE.match(payload):
        return payload, "legacy"
    return "", "bad_payload"


def _ts(unix: int | None) -> str:
    if not unix:
        return ""
    return datetime.fromtimestamp(int(unix), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _event(tenant_id: str, update_id, chat_id, client_user_id: str,
           consent: bool, ts: str, verified: bool = True) -> dict:
    return {
        "event_id": f"tg-{tenant_id}-{update_id}",
        "tenant_id": tenant_id,
        "event_type": "contact_update",
        "client_user_id": client_user_id,
        "ts": ts or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "source": "telegram",
        "meta": json.dumps({"channel": "telegram", "address": str(chat_id),
                            "consent": consent, "verified": verified}),
    }


def update_to_event(tenant_id: str, upd: dict) -> tuple[dict | None, dict | None]:
    """(событие | None, ответ бота | None).

    Ответ бота отделён от события: молчание после Start - главная жалоба на
    такие флоу, человек не понимает, сработало ли. Ответ шлёт app.py, чтобы
    здесь остались чистые функции.
    """
    if not isinstance(upd, dict):
        return None, None
    uid = upd.get("update_id", "x")

    msg = upd.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = str(msg.get("text") or "").strip()
    if chat_id and text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        cuid, kind = parse_start(tenant_id, payload)
        if not cuid:
            # /start без payload или битая подпись: связать не с кем, но
            # человеку в чате надо ответить, а не молчать
            return None, {"chat_id": chat_id, "text": (
                "This bot delivers notifications about your account. "
                "Please use the connect button on the product site or the "
                "link from an email, so we know it is you.")}
        return (_event(tenant_id, uid, chat_id, cuid, True, _ts(msg.get("date")),
                       verified=(kind == "signed")),
                {"chat_id": chat_id, "text": (
                    "Connected. Important updates about your account will "
                    "arrive here. Send /stop any time to opt out.")})
    if chat_id and text.lower().rstrip("@") in ("/stop", "stop"):
        return (_event(tenant_id, uid, chat_id, "", False, _ts(msg.get("date"))),
                {"chat_id": chat_id, "text":
                    "Done - no more messages here. Send /start to reconnect."})

    mcm = upd.get("my_chat_member") or {}
    status = ((mcm.get("new_chat_member") or {}).get("status") or "")
    mcm_chat = (mcm.get("chat") or {}).get("id")
    if mcm_chat and status in ("kicked", "left"):
        return _event(tenant_id, uid, mcm_chat, "", False,
                      _ts(mcm.get("date"))), None
    return None, None
