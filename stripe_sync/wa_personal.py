"""Личный WhatsApp тенанта через WAHA: QR-подключение, только приём.

ЗАЧЕМ, ЕСЛИ ЕСТЬ CLOUD API. Официальный канал требует Business Manager,
верификации и шаблонов - для владельца это «полная бессмыслица из полей».
Личный номер подключается как WhatsApp Web: отсканировал QR - работает.
Диалоги видны, отвечать можно живым голосом основателя.

ГРАНИЦА РИСКА (методология, раздел «Границы»). Это неофициальный протокол
против ToS Meta: сессию могут забанить, банят ЛИЧНЫЙ номер клиента. Поэтому:
  1. подключение только с ЯВНЫМ подтверждением риска (accept_risk, время
     фиксируется в tenants.json);
  2. автокасания сюда не ходят ТЕХНИЧЕСКИ: route_message умеет только Cloud
     API, у этого модуля вообще нет пути «отправить по расписанию»;
  3. входящее с нашим подписанным кодом (та же ссылка wa.me, что у Cloud API)
     привязывает аккаунт и даёт согласие; голое входящее - только событие.

WAHA (free) держит одну сессию на инстанс - для первого клиента достаточно;
имя сессии tenant_<id> оставляет путь к мульти-сессии (WAHA Plus).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

try:                                    # борд импортирует пакетом, джобы плоско
    from email_delivery import UNSUB_SECRET
except ImportError:
    from stripe_sync.email_delivery import UNSUB_SECRET  # type: ignore

WAHA_URL = os.environ.get("WAHA_URL", "http://waha:3000").rstrip("/")
WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "").strip()
# вебхук WAHA -> борд по ВНУТРЕННЕЙ сети compose: наружу не выходит вовсе
BOARD_INTERNAL = os.environ.get("BOARD_INTERNAL_URL", "http://board:8050").rstrip("/")
_TIMEOUT = 30


def session_name(tenant: str) -> str:
    return f"tenant_{tenant}"


def webhook_hmac_key(tenant: str, secret: str = "") -> str:
    key = (secret or UNSUB_SECRET).encode()
    return hmac.new(key, f"wapersonal|{tenant}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def verify_webhook(tenant: str, body: bytes, header: str,
                   secret: str = "") -> bool:
    """WAHA подписывает сырое тело sha512-HMAC (X-Webhook-Hmac)."""
    if not header:
        return False
    expected = hmac.new(webhook_hmac_key(tenant, secret).encode(), body,
                        hashlib.sha512).hexdigest()
    return hmac.compare_digest(str(header), expected)


def _call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{WAHA_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Content-Type": "application/json",
                 "X-Api-Key": WAHA_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode() or "{}"
            try:
                return resp.status, json.loads(raw)
            except ValueError:
                return resp.status, {"raw": raw[:200]}
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except ValueError:
            return exc.code, {}
    except Exception as exc:  # noqa: BLE001 - WAHA лежит: причина наверх
        return 0, {"error": type(exc).__name__}


def start_session(tenant: str) -> tuple[bool, str]:
    """Создать и запустить сессию с вебхуком на борд. Идемпотентно."""
    payload = {
        "name": session_name(tenant),
        "start": True,
        "config": {
            # хранилище NOWEB: без него WAHA не отдаёт историю чатов, и
            # инбокс начинается с пустоты вместо реальной переписки
            "noweb": {"store": {"enabled": True, "fullSync": True}},
            "webhooks": [{
            "url": f"{BOARD_INTERNAL}/public/wa/personal/{tenant}",
            # message.any даёт и входящие, и исходящие (ручные ответы тоже
            # видны); message отдельно НЕ подписываем - были бы дубли
            "events": ["message.any", "session.status"],
                "hmac": {"key": webhook_hmac_key(tenant)},
            }]},
    }
    status, doc = _call("POST", "/api/sessions", payload)
    if status in (200, 201):
        return True, str(doc.get("status") or "STARTING")
    if status in (409, 422):
        # Сессия уже существует. Живая (ждёт скан / работает) - это не ошибка.
        # А вот УПАВШУЮ надо пересоздать: иначе кнопка «Показать QR» вечно
        # утыкается в 422 и молча возвращает FAILED.
        current = get_status(tenant)[1]
        if current not in ("FAILED", "STOPPED"):
            return True, current
        drop_session(tenant)
        status, doc = _call("POST", "/api/sessions", payload)
        if status in (200, 201):
            return True, str(doc.get("status") or "STARTING")
    return False, f"waha_{status}:{str(doc)[:120]}"


def get_status(tenant: str) -> tuple[bool, str, str]:
    """(ok, status, номер). SCAN_QR_CODE | WORKING | STARTING | FAILED..."""
    status, doc = _call("GET", f"/api/sessions/{session_name(tenant)}")
    if status == 404:
        return True, "NOT_STARTED", ""
    if 200 <= status < 300:
        me = doc.get("me") or {}
        number = str(me.get("id") or "").split("@")[0]
        return True, str(doc.get("status") or ""), number
    return False, f"waha_{status}", ""


def get_qr_png(tenant: str) -> str:
    """QR картинкой (base64 png) - фронт показывает <img>, без QR-библиотек."""
    req = urllib.request.Request(
        f"{WAHA_URL}/api/{session_name(tenant)}/auth/qr?format=image",
        headers={"X-Api-Key": WAHA_API_KEY, "Accept": "image/png"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                return ""
            import base64
            return base64.b64encode(resp.read()).decode()
    except Exception:  # noqa: BLE001 - QR ещё не готов/сессия не в том статусе
        return ""


def drop_session(tenant: str) -> None:
    """Логаут + удаление: телефон клиента отвязывается от платформы."""
    _call("POST", f"/api/sessions/{session_name(tenant)}/logout")
    _call("DELETE", f"/api/sessions/{session_name(tenant)}")


def parse_event(doc: dict) -> dict:
    """Событие WAHA -> плоский вид. Чистая функция.

    {'kind': 'status'|'inbound'|'ignore', ...}. Исходящие (fromMe) и не-текст
    пишутся как ignore: v1 - только приём и привязка по коду.
    """
    event = str((doc or {}).get("event") or "")
    payload = (doc or {}).get("payload") or {}
    if event == "session.status":
        me = payload.get("me") or {}
        return {"kind": "status",
                "status": str(payload.get("status") or ""),
                "number": str(me.get("id") or "").split("@")[0]}
    if event in ("message", "message.any"):
        sender = str(payload.get("from") or "")
        to = str(payload.get("to") or "")
        # status@broadcast - статусы контактов, не переписка: в инбоксе это
        # выглядело чатом по имени «status» с чужими сторис внутри
        if "@broadcast" in sender or "@broadcast" in to:
            return {"kind": "ignore", "why": "broadcast"}
        try:
            # время САМОГО сообщения: при переподключении WAHA досылает
            # пропущенное, и время получения вебхука ломало бы порядок треда
            ts_unix = int(payload.get("timestamp") or 0)
        except (TypeError, ValueError):
            ts_unix = 0
        base = {
            "wa_msg_id": str(payload.get("id") or ""),
            "text": str(payload.get("body") or "")[:4096],
            "name": str(payload.get("pushName") or payload.get("notifyName")
                        or "")[:80],
            "ts_unix": ts_unix if 10**9 < ts_unix < 10**11 else 0,
        }
        if payload.get("fromMe"):
            # СВОИ ответы (из инбокса или прямо с телефона) тоже в тред:
            # без них переписка на экране - половина разговора
            return {"kind": "outbound", "chat_id": to or sender, **base}
        return {"kind": "inbound", "chat_id": sender,
                "from": sender.split("@")[0], **base}
    return {"kind": "ignore", "why": event or "empty"}


# ── Ручной ответ из инбокса ──────────────────────────────────────────────────
# ЕДИНСТВЕННЫЙ путь отправки в личный канал - и он требует явного текста от
# живого человека в интерфейсе. У кампаний доступа сюда нет: route_message
# этот модуль не импортирует, и тест-страж это проверяет.

def reply_as_human(tenant: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Отправить ответ в чат. chat_id - ПОЛНЫЙ (с @lid/@c.us).

    Запись в тред не делаем: подписка message.any вернёт эхо собственного
    сообщения вебхуком, и оно ляжет в wa_messages обычным путём - без
    дублей и с настоящим id.
    """
    text = str(text or "").strip()
    if not text or not chat_id:
        return False, "empty"
    status, doc = _call("POST", "/api/sendText", {
        "session": session_name(tenant), "chatId": chat_id, "text": text[:4096]})
    if 200 <= status < 300:
        return True, "sent"
    return False, f"waha_{status}:{str(doc)[:120]}"


def update_session_config(tenant: str) -> tuple[bool, str]:
    """Обновить конфиг живой сессии (PUT) без пересоздания.

    Авторизация лежит в volume - после restart сессия поднимается без
    повторного скана QR. Нужен для включения хранилища истории на сессии,
    созданной до этого конфига.
    """
    payload = {
        "config": {
            "noweb": {"store": {"enabled": True, "fullSync": True}},
            "webhooks": [{
                "url": f"{BOARD_INTERNAL}/public/wa/personal/{tenant}",
                "events": ["message.any", "session.status"],
                "hmac": {"key": webhook_hmac_key(tenant)},
            }]},
    }
    status, doc = _call("PUT", f"/api/sessions/{session_name(tenant)}", payload)
    if not (200 <= status < 300):
        return False, f"waha_{status}:{str(doc)[:120]}"
    status, doc = _call("POST", f"/api/sessions/{session_name(tenant)}/restart")
    if 200 <= status < 300:
        return True, "restarted"
    return False, f"waha_{status}:{str(doc)[:120]}"


def fetch_history(tenant: str, chat_limit: int = 30,
                  msg_limit: int = 100) -> list[dict]:
    """История переписки из хранилища WAHA - для бэкфилла wa_messages.

    [{chat_id, wa_msg_id, direction, text, name, ts_unix}]. Статусы
    (@broadcast) выброшены. Пустой список - хранилище ещё не синхронизировано.
    """
    sess = session_name(tenant)
    status, chats = _call("GET", f"/api/{sess}/chats?limit={chat_limit}")
    if status != 200 or not isinstance(chats, list):
        return []
    out: list[dict] = []
    for chat in chats:
        cid = chat.get("id")
        if isinstance(cid, dict):
            cid = cid.get("_serialized") or ""
        cid = str(cid or "")
        if not cid or "@broadcast" in cid:
            continue
        status, msgs = _call(
            "GET", f"/api/{sess}/chats/{cid}/messages?limit={msg_limit}"
                   f"&downloadMedia=false")
        if status != 200 or not isinstance(msgs, list):
            continue
        for m in msgs:
            body = str(m.get("body") or "")
            if not body:
                continue                     # медиа без текста - v1 пропускает
            try:
                ts = int(m.get("timestamp") or 0)
            except (TypeError, ValueError):
                ts = 0
            out.append({
                "chat_id": cid,
                "wa_msg_id": str(m.get("id") or ""),
                "direction": "out" if m.get("fromMe") else "in",
                "text": body[:4096],
                "name": "" if m.get("fromMe") else str(m.get("notifyName")
                                                       or "")[:80],
                "ts_unix": ts if 10**9 < ts < 10**11 else 0,
            })
    return out


def list_lids(tenant: str) -> dict:
    """{цифры LID: цифры номера} - разгадка приватных идентификаторов.

    WhatsApp прячет номер за LID (258...@lid), но связанное устройство знает
    соответствие - WAHA отдаёт его целиком. Без этого карточка контакта
    показывает бессмысленный LID вместо телефона.
    """
    status, doc = _call("GET", f"/api/{session_name(tenant)}/lids?limit=500")
    if status != 200 or not isinstance(doc, list):
        return {}
    out = {}
    for row in doc:
        lid = str(row.get("lid") or "").split("@")[0]
        pn = str(row.get("pn") or "").split("@")[0]
        if lid and pn:
            out[lid] = pn
    return out


def check_number(tenant: str, phone: str) -> tuple[bool, str]:
    """Есть ли номер в WhatsApp вообще. (exists, канонический chat_id).

    Писать первым на номер, которого нет в WhatsApp, - сообщение в пустоту;
    а канонический chat_id важен, потому что часть аккаунтов живёт за @lid.
    """
    import re as _re
    digits = _re.sub(r"\D", "", str(phone or ""))
    if not 8 <= len(digits) <= 15:
        return False, ""
    status, doc = _call(
        "GET", f"/api/contacts/check-exists?phone={digits}"
               f"&session={session_name(tenant)}")
    if status != 200 or not isinstance(doc, dict):
        return False, ""
    if not doc.get("numberExists"):
        return False, ""
    chat_id = doc.get("chatId")
    if isinstance(chat_id, dict):
        chat_id = chat_id.get("_serialized")
    return True, str(chat_id or f"{digits}@c.us")
