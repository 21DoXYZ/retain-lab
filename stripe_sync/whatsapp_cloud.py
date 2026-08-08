"""WhatsApp Cloud API: официальный транспорт Meta, per-tenant.

МОДЕЛЬ - как с Resend: WABA и номер принадлежат КЛИЕНТУ, мы шлём его
постоянным токеном (System User). Клиент платит Meta напрямую, владеет
репутацией номера и видит свою статистику. Конфиг в tenants.json:
  wa_token            - постоянный токен System User
  wa_phone_number_id  - id номера в Cloud API (не сам номер!)
  wa_phone_display    - номер человеком (+9715...), для ссылок wa.me
  wa_app_secret       - app secret для подписи вебхука (X-Hub-Signature-256)
  wa_waba_id          - id WABA (создание шаблонов)

ПОЧЕМУ ТОЛЬКО ШАБЛОНЫ. Вне 24-часового окна после сообщения человека Meta
принимает ТОЛЬКО заранее одобренный шаблон. Кампании удержания почти всегда
пишут первыми, поэтому v1 честно шлёт только шаблоны - это работает всегда и
не зависит от состояния окна. Свободный текст в окне - слой инбокса, потом.

ПОЧЕМУ НЕ WAHA/BAILEYS. Неофициальный протокол банит номер клиента за 2-8
недель, а дуннинг - сообщение, которое обязано дойти. Плюс это нарушение ToS:
по нашей методологии канал, который работает, пока Meta не заметила, в
продукт не попадает.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request

GRAPH = "https://graph.facebook.com/v23.0"
_TIMEOUT = 30

# Ошибки Meta, после которых человеку больше не пишем (fail-closed, как
# email-супрессии). 131050 - пользователь запретил маркетинг этому бизнесу.
SUPPRESS_ERROR_CODES = {131050, 131051}
# Временные: перегрузка/лимит - шаг переживёт ретрай, а не сгорит
TRANSIENT_ERROR_CODES = {130429, 131048, 131056, 80007, 1, 2}


def _post(url: str, token: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except ValueError:
            return exc.code, {}
    except Exception as exc:  # noqa: BLE001 - сеть: причина уходит вызывающему
        return 0, {"error": {"message": type(exc).__name__, "code": 1}}


def normalize_wa_phone(raw: str) -> str:
    """Телефон -> формат Cloud API (цифры с кодом страны, без +)."""
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits if 8 <= len(digits) <= 15 else ""


def send_template(token: str, phone_number_id: str, to: str,
                  template: str, lang: str = "en",
                  params: list | None = None) -> tuple[bool, str]:
    """Отправка одобренного шаблона. (ok, detail).

    detail успешной отправки = wa-id сообщения (по нему вебхуки статусов
    находят касание). Ошибка - 'wa_<code>:<message>'; supress/transient
    разбирает вызывающий по коду.
    """
    to_n = normalize_wa_phone(to)
    if not to_n:
        return False, "invalid_phone"
    payload: dict = {
        "messaging_product": "whatsapp", "to": to_n, "type": "template",
        "template": {"name": template, "language": {"code": lang}},
    }
    if params:
        payload["template"]["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)[:1024]}
                           for p in params],
        }]
    status, doc = _post(f"{GRAPH}/{phone_number_id}/messages", token, payload)
    if 200 <= status < 300:
        msgs = doc.get("messages") or [{}]
        return True, str(msgs[0].get("id") or f"http_{status}")
    err = (doc.get("error") or {})
    return False, f"wa_{err.get('code', status)}:{str(err.get('message'))[:120]}"


def is_transient(detail: str) -> bool:
    m = re.match(r"^wa_(\d+):", str(detail or ""))
    return bool(m) and int(m.group(1)) in TRANSIENT_ERROR_CODES


def should_suppress(detail: str) -> bool:
    m = re.match(r"^wa_(\d+):", str(detail or ""))
    return bool(m) and int(m.group(1)) in SUPPRESS_ERROR_CODES


def create_template(token: str, waba_id: str, name: str, category: str,
                    body: str, lang: str = "en") -> tuple[bool, str]:
    """Создать шаблон на одобрение. category: UTILITY | MARKETING.

    Статус одобрения приходит вебхуком message_template_status_update -
    создание НЕ означает, что слать уже можно.
    """
    payload = {
        "name": name, "category": category, "language": lang,
        # Meta вправе переклассифицировать (utility -> marketing и наоборот);
        # без этого флага пограничный шаблон просто отклоняется
        "allow_category_change": True,
        "components": [{"type": "BODY", "text": body}],
    }
    status, doc = _post(f"{GRAPH}/{waba_id}/message_templates", token, payload)
    if 200 <= status < 300:
        return True, str(doc.get("id") or "")
    err = (doc.get("error") or {})
    return False, f"wa_{err.get('code', status)}:{str(err.get('message'))[:120]}"


# ── Вебхук Meta: подпись и разбор ────────────────────────────────────────────

def verify_signature(app_secret: str, body: bytes, header: str) -> bool:
    """X-Hub-Signature-256: 'sha256=<hmac>' от сырого тела запроса."""
    if not app_secret or not str(header or "").startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(str(header)[7:], expected)


def parse_webhook(doc: dict) -> dict:
    """Апдейт Meta -> плоские списки, по одному на тип. Чистая функция.

    statuses  - [{wa_msg_id, status, ts, recipient, error_code}]
    inbound   - [{wa_msg_id, from, ts, text, type}]
    templates - [{name, event, reason}]  (одобрение/отклонение/пауза шаблона)
    """
    statuses, inbound, templates = [], [], []
    for entry in (doc or {}).get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            field = change.get("field") or ""
            if field == "message_template_status_update":
                templates.append({
                    "name": str(value.get("message_template_name") or ""),
                    "event": str(value.get("event") or "").upper(),
                    "reason": str(value.get("reason") or ""),
                })
                continue
            for st in value.get("statuses") or []:
                err = (st.get("errors") or [{}])[0]
                statuses.append({
                    "wa_msg_id": str(st.get("id") or ""),
                    "status": str(st.get("status") or ""),
                    "ts": str(st.get("timestamp") or ""),
                    "recipient": str(st.get("recipient_id") or ""),
                    "error_code": int(err.get("code") or 0),
                })
            for msg in value.get("messages") or []:
                inbound.append({
                    "wa_msg_id": str(msg.get("id") or ""),
                    "from": str(msg.get("from") or ""),
                    "ts": str(msg.get("timestamp") or ""),
                    "type": str(msg.get("type") or ""),
                    "text": str(((msg.get("text") or {}).get("body")) or "")[:4096],
                })
    return {"statuses": statuses, "inbound": inbound, "templates": templates}


def _get(url: str, token: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except ValueError:
            return exc.code, {}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": {"message": type(exc).__name__, "code": 1}}


def probe_number(token: str, phone_number_id: str) -> tuple[bool, str]:
    """Живая проверка конфига: токен видит номер? (ok, display_phone|причина).

    Сохранить нерабочий конфиг - значит узнать об этом в момент несписания
    у клиента, поэтому проверяем при сохранении, а не при первой отправке.
    """
    status, doc = _get(f"{GRAPH}/{phone_number_id}"
                       f"?fields=display_phone_number,verified_name", token)
    if 200 <= status < 300:
        return True, str(doc.get("display_phone_number") or "")
    err = doc.get("error") or {}
    return False, f"wa_{err.get('code', status)}:{str(err.get('message'))[:120]}"
