"""Клиентский флоу подключения каналов (управление из CRM, Phase 4).

Партнёрская модель: аккаунты провайдеров - НАШИ (один на платформу), клиент
подключает только ИДЕНТИЧНОСТЬ своего бренда:
  email    - его поддомен в нашем Resend (клиент ставит DNS-записи, мы верифицируем);
  sms/viber- его альфа-имя, которое мы регистрируем через менеджера DecisionTelecom
             (запрос фиксируется здесь, активация - платформой после подтверждения);
  telegram - его собственный бот (@BotFather), токен валидируем через getMe и
             вешаем вебхук на наш ingest;
  whatsapp - позже: WABA клиента через онбординг DT.

Всё состояние тенанта - secrets/tenants.json (см. tenants.json.example).
Сетевые вызовы fail-closed: без ключа/сети возвращаем (False, reason), ничего
не записываем наполовину.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request

_TIMEOUT = 20

# Cloudflare у провайдеров отбивает дефолтный Python-urllib с 403 - без
# собственного User-Agent не работали ни проверка ключа, ни ОТПРАВКА ПИСЕМ.
USER_AGENT = "RevenueAutopilot/1.0 (+https://retivo.digital)"

RESEND_API = "https://api.resend.com"
TG_API = "https://api.telegram.org"

TENANTS_FILE = os.environ.get("TENANTS_FILE", "/secrets/tenants.json")

DOMAIN_RE = re.compile(r"^(?=.{4,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
# Альфа-имя: правила операторов - латиница/цифры/пробел/точка/дефис, до 11 знаков.
ALPHA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .\-]{1,10}$")
BOT_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")


def _request(method: str, url: str, payload: dict | None,
             headers: dict) -> tuple[bool, str, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read().decode() or "{}"
            try:
                return True, f"http_{resp.status}", json.loads(body)
            except ValueError:
                return True, f"http_{resp.status}", {}
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode() or "{}")
        except Exception:
            detail = {}
        return False, f"http_{exc.code}", detail
    except Exception as exc:
        return False, type(exc).__name__, {}


# ── Resend: домен отправки клиента в НАШЕМ аккаунте ──────────────────────────

def _resend_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def resend_create_domain(domain: str, api_key: str) -> tuple[bool, str, dict]:
    return _request("POST", f"{RESEND_API}/domains", {"name": domain},
                    _resend_headers(api_key))


def resend_enable_tracking(domain_id: str, api_key: str) -> tuple[bool, str, dict]:
    """Включить open/click tracking на домене (2026-08-26).

    БЕЗ этого Resend НЕ шлёт события opened/clicked, даже если вебхук на них
    подписан - и вся аналитика открытий, A/B по кликам и догонялки «только
    неоткрывшим» тихо мертвы. Вызывается при подключении/верификации домена.
    """
    return _request("PATCH", f"{RESEND_API}/domains/{domain_id}",
                    {"open_tracking": True, "click_tracking": True},
                    _resend_headers(api_key))


def resend_find_domain(domain: str, api_key: str) -> dict:
    """Домен, УЖЕ заведённый в аккаунте клиента (часто он там есть и проверен).

    Без этого клиент с готовым доменом упирался в ошибку «уже существует» и
    вынужден был заводить лишний поддомен с новыми DNS-записями.
    """
    ok, _status, data = _request("GET", f"{RESEND_API}/domains", None,
                                 _resend_headers(api_key))
    if not ok:
        return {}
    for item in (data or {}).get("data", []) or []:
        if str(item.get("name", "")).lower() == domain.lower():
            return item
    return {}


def resend_get_domain(domain_id: str, api_key: str) -> tuple[bool, str, dict]:
    return _request("GET", f"{RESEND_API}/domains/{domain_id}", None,
                    _resend_headers(api_key))


def resend_verify_domain(domain_id: str, api_key: str) -> tuple[bool, str, dict]:
    return _request("POST", f"{RESEND_API}/domains/{domain_id}/verify", None,
                    _resend_headers(api_key))


def dns_rows(domain_obj: dict) -> list[dict]:
    """Записи Resend -> строки для таблицы в UI (что клиент несёт в свой DNS)."""
    rows = []
    for r in domain_obj.get("records") or []:
        row = {"record": str(r.get("record", "")),
               "type": str(r.get("type", "")),
               "name": str(r.get("name", "")),
               "value": str(r.get("value", "")),
               "status": str(r.get("status", ""))}
        if r.get("priority") is not None:
            row["priority"] = int(r["priority"])
        rows.append(row)
    return rows


# ── Telegram: бот клиента, вебхук на наш ingest ──────────────────────────────

def telegram_get_me(token: str) -> tuple[bool, str]:
    ok, status, data = _request("GET", f"{TG_API}/bot{token}/getMe", None, {})
    if not ok:
        return False, "telegram_invalid_token" if status == "http_401" else status
    username = ((data.get("result") or {}).get("username") or "").strip()
    return (True, username) if data.get("ok") and username else (False, "telegram_invalid_token")


def telegram_set_webhook(token: str, url: str, secret: str) -> tuple[bool, str]:
    ok, status, data = _request(
        "POST", f"{TG_API}/bot{token}/setWebhook",
        {"url": url, "secret_token": secret,
         "allowed_updates": ["message", "my_chat_member"]}, {})
    if ok and data.get("ok"):
        return True, "webhook_set"
    return False, status if not ok else str(data.get("description", "webhook_failed"))


def telegram_delete_webhook(token: str) -> tuple[bool, str]:
    ok, status, _ = _request("POST", f"{TG_API}/bot{token}/deleteWebhook", None, {})
    return ok, status


# ── tenants.json: атомарные обновления ───────────────────────────────────────

def load_tenants(path: str = "") -> dict:
    try:
        with open(path or TENANTS_FILE) as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def merged_tenant(existing: dict, patch: dict) -> dict:
    """Слияние конфига тенанта: None в patch удаляет ключ, остальное - заменяет."""
    out = dict(existing)
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def update_tenant(tenant_id: str, patch: dict, path: str = "") -> dict:
    """Читает файл, вливает patch в конфиг тенанта, атомарно переписывает
    (tmp + rename - сендеры в соседних процессах не увидят полфайла).
    Возвращает новый конфиг тенанта."""
    p = path or TENANTS_FILE
    data = load_tenants(p)
    conf = merged_tenant(data.get(tenant_id) or {}, patch)
    data[tenant_id] = conf
    d = os.path.dirname(p) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tenants-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return conf


# ── Машины состояний каналов (чистые - на них смотрит UI) ────────────────────

def email_state(conf: dict, platform_key: bool) -> str:
    """not_connected -> awaiting_provider|pending_dns -> verified -> active."""
    status = str(conf.get("email_domain_status", ""))
    if status == "verified":
        return "active" if conf.get("email_from") else "sender_needed"
    if status == "awaiting_provider":
        return "awaiting_provider" if not platform_key else "pending_dns"
    if status in ("pending_dns", "pending", "not_started", "failure", "temporary_failure"):
        return "pending_dns"
    return "not_connected"


def messaging_state(conf: dict, kind: str, platform_key: bool) -> str:
    """kind: sms|viber. Активен, когда платформа перенесла requested_* в *_sender
    (= альфа-имя подтверждено DecisionTelecom)."""
    if conf.get(f"{kind}_sender"):
        return "active" if platform_key else "awaiting_provider"
    if conf.get(f"requested_{kind}_sender"):
        return "pending_approval"
    return "not_connected"


def telegram_state(conf: dict) -> str:
    return "active" if conf.get("telegram_bot_token") else "not_connected"
