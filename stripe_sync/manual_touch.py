"""Ручные действия из карточки юзера: контакты и касания руками владельца.

Карточка - место, где владелец действует ТОЧЕЧНО: добавил телефон, написал
одному человеку, зачислил его в кампанию. Политика отличается от автопилота
ровно в одном: ручное касание - решение живого человека, поэтому выключенный
автопилот его НЕ глушит (глобальный SIGNALS_DRY_RUN остаётся рубильником).
Всё остальное общее: согласие обязательно, супрессии соблюдаются, сырой
плейсхолдер человеку не уходит.

WhatsApp здесь не шлётся: свободный текст живёт только в инбоксе
(reply_as_human) - эндпоинт карточки зовёт его сам, минуя этот модуль,
чтобы конвейерные сендеры так и не узнали о личном канале.
"""

from __future__ import annotations

import re

try:                                # борд пакетом, джобы плоско
    from saas_senders import normalize_phone, route_message
except ImportError:
    from stripe_sync.saas_senders import normalize_phone, route_message  # type: ignore

# Каналы, которые можно завести руками. Email не здесь: он живёт в identity
# (из Stripe/импорта), а не в contacts. WhatsApp-контакт руками завести можно -
# слать в него будет либо инбокс (личный номер), либо Cloud-шаблоны кампаний.
CONTACT_CHANNELS = ("sms", "viber", "whatsapp", "telegram")

# Ручные касания в логе живут под этим id: uplift-отчёт их не смешивает
# с кампаниями, а частотные капы автопилота их видят как обычные касания.
MANUAL_CAMPAIGN = "manual"

_TG_CHAT = re.compile(r"^-?\d{5,15}$")


def validate_contact(channel: str, address: str) -> tuple[str, str]:
    """(нормализованный адрес, '') либо ('', код ошибки)."""
    ch = str(channel or "").strip().lower()
    if ch not in CONTACT_CHANNELS:
        return "", "unknown_channel"
    raw = str(address or "").strip()
    if not raw:
        return "", "empty_address"
    if ch == "telegram":
        # chat_id выдаёт бот после /start; произвольный номер туда не годится
        return (raw, "") if _TG_CHAT.match(raw) else ("", "invalid_telegram_chat_id")
    num = normalize_phone(raw)
    return (num, "") if num else ("", "invalid_phone")


# Каналы ручной отправки текстом. inapp и whatsapp - отдельные пути в API
# (очередь баннеров и инбокс соответственно), сюда не заходят.
SEND_CHANNELS = ("email", "sms", "viber", "telegram")


def manual_send(channel: str, address: str, subject: str, body: str,
                email_cfg, msg_cfg) -> tuple[bool, str]:
    """Отправить одно ручное сообщение. Транспорт общий с кампаниями
    (route_message): те же лимиты длины, тот же плейсхолдер-гард."""
    if channel not in SEND_CHANNELS:
        return False, "unknown_channel"
    if not str(body or "").strip():
        return False, "empty"
    if channel == "email" and not str(subject or "").strip():
        return False, "subject_required"
    return route_message(channel, address, subject, body, email_cfg, msg_cfg)


SEND_LOG_COLUMNS = ["tenant_id", "campaign_id", "identity_id", "step_idx",
                    "action", "detail", "status", "reason", "provider_id", "ts"]


def send_log_row(tenant: str, identity: str, channel: str, subject: str,
                 body: str, status: str, reason: str, now,
                 provider_id: str = "") -> list:
    """Строка campaign_send_log для ручного касания (step_idx = -1)."""
    detail = str(subject or "").strip() or " ".join(str(body or "").split())[:80]
    return [tenant, MANUAL_CAMPAIGN, identity, -1, channel, detail,
            status, reason, provider_id, now]
