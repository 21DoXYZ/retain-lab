"""Подписанные ссылки подписки на Telegram-бота тенанта.

КАК РАБОТАЕТ ФЛОУ ЦЕЛИКОМ (принимающая сторона уже есть):
  ссылка t.me/<бот>?start=<payload> (письмо {{telegram_connect_url}}, in-app
  баннер, кнопка data-ra-telegram на сайте) -> Telegram шлёт /start на вебхук
  ingest (/ingest/saas/tg/<tenant>) -> tg_events превращает его в событие
  contact_update -> contacts_sync пишет контакт с согласием. Канал telegram
  для человека становится живым.

ЗАЧЕМ ПОДПИСЬ. Голый client_user_id в payload значит: любой, кто узнал чужой
id, уводит чужие уведомления в свой чат. Ссылки, которые генерируем МЫ
(письма, inbox), несут подписанный payload:
    s<base64url(uid)>_<hmac10>
Старые сниппеты шлют голый uid - его принимаем как «легаси» и проверяем по
базе тенанта, прежде чем писать контакт.

Алфавит payload Telegram: [A-Za-z0-9_-], максимум 64 символа. Слишком длинный
uid в подписанный формат не влезает - тогда легаси-ссылка (если алфавит
позволяет) либо ничего.

ЗЕРКАЛО В INGEST. Шлюз собирается из ./ingest без stripe_sync, поэтому разбор
payload продублирован в ingest/tg_events.py. Паритет двух реализаций держит
тест test_telegram_connect.py::test_ingest_mirror_stays_in_sync.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.request

try:                                    # борд импортирует пакетом, джобы плоско
    from email_delivery import UNSUB_SECRET
except ImportError:
    from stripe_sync.email_delivery import UNSUB_SECRET  # type: ignore

PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SIGNED_RE = re.compile(r"^s([A-Za-z0-9_-]+)_([0-9a-f]{10})$")


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sig(tenant: str, uid: str, secret: str = "") -> str:
    key = (secret or UNSUB_SECRET).encode()
    return hmac.new(key, f"tg|{tenant}|{uid}".encode(),
                    hashlib.sha256).hexdigest()[:10]


def sign_payload(tenant: str, uid: str, secret: str = "") -> str:
    """Подписанный payload для /start. '' - uid не влезает в 64 символа."""
    uid = str(uid or "").strip()
    if not uid:
        return ""
    payload = f"s{_b64u(uid.encode())}_{_sig(tenant, uid, secret)}"
    return payload if len(payload) <= 64 else ""


def parse_start(tenant: str, payload: str, secret: str = "") -> tuple[str, str]:
    """payload из /start -> (uid, 'signed'|'legacy') либо ('', причина).

    'legacy' (голый uid от старых сниппетов) обязывает вызывающего проверить
    существование uid в базе тенанта, прежде чем записывать контакт.
    """
    payload = str(payload or "").strip()
    if not payload:
        return "", "empty"
    signed = SIGNED_RE.match(payload)
    if signed:
        try:
            uid = _b64u_decode(signed.group(1)).decode()
        except Exception:
            return "", "bad_encoding"
        if not hmac.compare_digest(signed.group(2), _sig(tenant, uid, secret)):
            return "", "bad_signature"
        return uid, "signed"
    if PAYLOAD_RE.match(payload):
        return payload, "legacy"
    return "", "bad_payload"


def connect_url(bot_username: str, tenant: str, uid: str, secret: str = "") -> str:
    """Ссылка подписки для конкретного юзера. '' - канал не настроен."""
    bot = str(bot_username or "").strip().lstrip("@")
    uid = str(uid or "").strip()
    if not bot or not uid:
        return ""
    payload = sign_payload(tenant, uid, secret)
    if not payload:
        if not PAYLOAD_RE.match(uid):
            return ""
        payload = uid                    # длинный uid: легаси с проверкой по базе
    return f"https://t.me/{bot}?start={payload}"
