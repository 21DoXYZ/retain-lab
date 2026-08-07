"""Доставляемость email: HTML-письмо, отписка, подпись вебхуков Resend.

ПОЧЕМУ ЭТО ОБЯЗАТЕЛЬНО, а не «потом»:
  • без ссылки отписки и заголовка List-Unsubscribe почтовики (Gmail, Outlook)
    режут репутацию домена клиента - письма уходят в спам ВСЕМ;
  • без обработки жалоб (complained) мы продолжаем писать тем, кто нажал
    «спам» - домен клиента попадает в чёрные списки;
  • без обработки жёстких баунсов мы бьёмся в несуществующие адреса, что
    тоже роняет репутацию.
Всё это - домен КЛИЕНТА (письма уходят от его бренда), поэтому цена ошибки
ложится на него.

Здесь только чистые функции: рендер письма, подпись/проверка токена отписки,
проверка подписи вебхука. Сеть - в saas_senders (отправка) и api/public.py
(приём вебхука).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html as _html
import os
import re
import time

# Секрет для токенов отписки. Отдельный от прочих: утечка одного не должна
# позволять отписывать чужих. Фолбэк на INGEST-секрет только для dev.
UNSUB_SECRET = (os.environ.get("UNSUB_SECRET")
                or os.environ.get("SUPABASE_JWT_SECRET")
                or "dev-unsub-secret")

LINK_RE = re.compile(r"https?://[^\s<>\"')]+")


# ── Токен отписки ────────────────────────────────────────────────────────────

def unsub_token(tenant: str, address: str, secret: str = "") -> str:
    """Короткая подпись (tenant|address). Без срока: ссылка в старом письме
    обязана работать всегда - это требование к отписке."""
    msg = f"{tenant}|{address.strip().lower()}".encode()
    key = (secret or UNSUB_SECRET).encode()
    return base64.urlsafe_b64encode(hmac.new(key, msg, hashlib.sha256).digest()[:18]).decode()


def unsub_token_valid(tenant: str, address: str, token: str, secret: str = "") -> bool:
    """compare_digest падает на не-ASCII, а токен приходит из URL: сравниваем
    байты, чтобы кривая ссылка давала честный отказ, а не 500."""
    expected = unsub_token(tenant, address, secret).encode()
    got = str(token or "").encode("utf-8", errors="ignore")
    return hmac.compare_digest(expected, got)


def unsub_url(host: str, tenant: str, address: str, secret: str = "") -> str:
    from urllib.parse import quote
    tok = unsub_token(tenant, address, secret)
    return (f"https://{host}/public/unsubscribe?t={quote(tenant)}"
            f"&a={quote(address)}&s={quote(tok)}")


# ── Письмо ───────────────────────────────────────────────────────────────────

def text_to_html(body: str, unsubscribe: str, brand: str = "") -> str:
    """Простой, надёжно отображаемый HTML: инлайн-стили, одна колонка,
    ссылки кликабельны, внизу - отписка. Без картинок и внешних ресурсов:
    такие письма реже режутся фильтрами и грузятся везде."""
    safe = _html.escape(body.strip())
    safe = LINK_RE.sub(
        lambda m: f'<a href="{m.group(0)}" style="color:#2563eb">{m.group(0)}</a>', safe)
    paragraphs = "".join(
        f'<p style="margin:0 0 14px;line-height:1.55">{p}</p>'
        for p in safe.split("\n") if p.strip())
    footer_brand = _html.escape(brand) if brand else ""
    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#f6f7f9">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f6f7f9;padding:24px 12px"><tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:520px;background:#ffffff;border-radius:12px;'
        'padding:28px 26px;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;'
        'font-size:15px;color:#101828"><tr><td>'
        f'{paragraphs}'
        '<div style="margin-top:22px;padding-top:16px;border-top:1px solid #eaecf0;'
        'font-size:12px;color:#98a2b3">'
        f'{footer_brand}{" · " if footer_brand else ""}'
        f'<a href="{unsubscribe}" style="color:#98a2b3">Unsubscribe</a>'
        '</div></td></tr></table></td></tr></table></body></html>'
    )


def build_email_payload(to: str, subject: str, body: str, email_from: str,
                        unsubscribe: str, brand: str = "", cta_label: str = "",
                        brand_color: str = "") -> dict:
    """Тело запроса к Resend: и HTML, и текст (клиенты без HTML), плюс
    заголовки отписки - их читают Gmail/Outlook и показывают свою кнопку."""
    try:                                    # борд импортирует пакетом, джобы плоско
        from email_template import render
    except ImportError:
        from stripe_sync.email_template import render
    return {
        "from": email_from,
        "to": [to],
        "subject": subject,
        "html": render(subject, body, unsubscribe, brand, cta_label, brand_color),
        "text": f"{body.strip()}\n\n---\nUnsubscribe: {unsubscribe}",
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }


# ── Подпись вебхука Resend (Svix) ────────────────────────────────────────────

def verify_svix(secret: str, msg_id: str, timestamp: str, body: bytes,
                signature_header: str, tolerance_s: int = 300,
                now: float | None = None) -> bool:
    """Проверка подписи вебхука (схема Svix, её использует Resend).

    Подписывается строка "<id>.<timestamp>.<body>" ключом из secret
    (после префикса whsec_ - base64). Заголовок svix-signature может нести
    несколько подписей через пробел: "v1,<b64> v1,<b64>".
    Fail-closed: нет секрета/заголовков или разошлось время - отказ.
    """
    if not secret or not msg_id or not timestamp or not signature_header:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - ts) > tolerance_s:
        return False

    raw = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw)
    except Exception:  # noqa: BLE001
        return False

    signed = b"%s.%s.%s" % (msg_id.encode(), timestamp.encode(), body)
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in str(signature_header).split():
        _, _, sig = part.partition(",")
        if sig and hmac.compare_digest(sig, expected):
            return True
    return False


# ── Классификация событий доставки ───────────────────────────────────────────

SUPPRESSING = {
    "email.bounced": "bounced",       # адрес не существует / отказ сервера
    "email.complained": "complained",  # нажал «спам» - писать нельзя
}
KNOWN_EVENTS = {"email.sent", "email.delivered", "email.delivery_delayed",
                "email.opened", "email.clicked", "email.bounced",
                "email.complained"}


def parse_webhook(doc: dict) -> dict:
    """Полезное из тела вебхука. {} - событие не наше/непонятное."""
    etype = str(doc.get("type") or "")
    if etype not in KNOWN_EVENTS:
        return {}
    data = doc.get("data") or {}
    to = data.get("to")
    address = (to[0] if isinstance(to, list) and to else str(to or "")).strip().lower()
    return {
        "event_type": etype,
        "provider_id": str(data.get("email_id") or data.get("id") or ""),
        "address": address,
        "subject": str(data.get("subject") or "")[:200],
        "detail": str((data.get("bounce") or {}).get("message")
                      or data.get("reason") or "")[:300],
        "suppress_reason": SUPPRESSING.get(etype, ""),
    }
