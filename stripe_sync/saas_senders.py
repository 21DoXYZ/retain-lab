"""Email-канал SaaS-кампаний: Resend API либо dry-run (дефолт, как senders.py).

DRY_RUN (SIGNALS_DRY_RUN=1 по умолчанию): письмо печатается, в сеть не уходит.
Реальный режим: RESEND_API_KEY + EMAIL_FROM (домен с DKIM/SPF — warm-up по
плану Phase 4). Плейсхолдеры {{...}} рендерятся из контекста; касание с
НЕРАЗРЕШЁННЫМ плейсхолдером отклоняется (unresolved_placeholder) - артефакт
шаблона живому человеку не отправляется ни в каком режиме.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

_TIMEOUT = 30

# Cloudflare у провайдеров отбивает дефолтный Python-urllib с 403 - без
# собственного User-Agent не работали ни проверка ключа, ни ОТПРАВКА ПИСЕМ.
USER_AGENT = "RevenueAutopilot/1.0 (+https://retivo.digital)"


@dataclass(frozen=True)
class EmailConfig:
    dry_run: bool = True
    resend_api_key: str = ""
    email_from: str = ""
    app_url: str = ""
    card_update_url: str = ""
    tenant_id: str = ""          # для ссылки отписки (подпись по тенанту)
    saas_host: str = ""          # домен платформы: там живёт /public/unsubscribe
    brand: str = ""              # имя продукта в подвале письма

    @classmethod
    def from_env(cls) -> "EmailConfig":
        return cls(
            dry_run=os.environ.get("SIGNALS_DRY_RUN", "1") not in ("0", "false", "False", ""),
            resend_api_key=os.environ.get("RESEND_API_KEY", "").strip(),
            email_from=os.environ.get("EMAIL_FROM", "").strip(),
            app_url=os.environ.get("APP_URL", "https://app.example.test").strip(),
            card_update_url=os.environ.get("BILLING_PORTAL_URL",
                                           "https://billing.example.test/portal").strip(),
            tenant_id=os.environ.get("TENANT_ID", "").strip(),
            saas_host=os.environ.get("SAAS_HOST", "").strip(),
        )


def render(template: str, ctx: dict) -> str:
    return re.sub(r"\{\{(\w+)\}\}",
                  lambda m: str(ctx.get(m.group(1), m.group(0))), template)


def unresolved(text: str) -> bool:
    """Остались ли в тексте сырые плейсхолдеры после рендера.

    «Reply to {{telegram_connect_url}}» с фигурными скобками в письме - это
    артефакт шаблона, показанный живому человеку: бот не подключён или в
    тексте опечатка. Такое касание честнее не отправить и сказать почему,
    чем отправить мусор.
    """
    return bool(re.search(r"\{\{\w+\}\}", text or ""))


def send_email(to: str, subject: str, body: str, cfg: EmailConfig,
               ctx: dict | None = None) -> tuple[bool, str]:
    context = {"app_url": cfg.app_url, "card_update_url": cfg.card_update_url}
    context.update(ctx or {})
    subject_r, body_r = render(subject, context), render(body, context)
    if unresolved(subject_r) or unresolved(body_r):
        # артефакт шаблона живому человеку не отправляем ни в каком режиме
        return False, "unresolved_placeholder"

    if cfg.dry_run:
        print(f"[email dry_run] to={to} subj={subject_r!r}", flush=True)
        return True, "dry_run"
    if not cfg.resend_api_key or not cfg.email_from:
        return False, "email_not_configured"

    try:
        from email_delivery import build_email_payload, unsub_url
    except ImportError:
        from stripe_sync.email_delivery import build_email_payload, unsub_url

    unsub = unsub_url(cfg.saas_host or "retivo.digital", cfg.tenant_id or "", to)
    payload = json.dumps(build_email_payload(
        to, subject_r, body_r, cfg.email_from, unsub, cfg.brand)).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": USER_AGENT,
                 "Authorization": f"Bearer {cfg.resend_api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode() or "{}")
            # id письма нужен, чтобы связать вебхуки доставки с касанием
            msg_id = str(body.get("id") or "")
            return (200 <= resp.status < 300), (msg_id or f"http_{resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:120]
        return False, f"http_{exc.code}:{detail}"
    except Exception as exc:
        return False, type(exc).__name__


# ── Каналы за пределами email: DecisionTelecom (SMS/Viber) + Telegram ─────────
# Провайдеры ПЛАТФОРМЕННЫЕ (ключи наши, один аккаунт на всех тенантов);
# клиент каналы не подключает - он поставляет КОНТАКТЫ и СОГЛАСИЯ
# (событие contact_update, см. INTEGRATION-SAAS.md §Каналы).

DECISION_SMS_URL = "https://web.it-decision.com/v1/api/send-sms"
DECISION_VIBER_URL = "https://web.it-decision.com/v1/api/send-viber"
TG_API = "https://api.telegram.org"


@dataclass(frozen=True)
class MessagingConfig:
    dry_run: bool = True
    decision_api_key: str = ""      # base64-ключ DT, идёт в Authorization: Basic
    sms_sender: str = ""            # альфа-имя, выдаёт менеджер DT
    viber_sender: str = ""
    viber_message_type: int = 106   # текстовый тип; сверить с аккаунтом DT
    telegram_bot_token: str = ""

    @classmethod
    def from_env(cls) -> "MessagingConfig":
        return cls(
            dry_run=os.environ.get("SIGNALS_DRY_RUN", "1") not in ("0", "false", "False", ""),
            decision_api_key=os.environ.get("DECISION_API_KEY", "").strip(),
            sms_sender=os.environ.get("DECISION_SMS_SENDER", "").strip(),
            viber_sender=os.environ.get("DECISION_VIBER_SENDER", "").strip(),
            viber_message_type=int(os.environ.get("DECISION_VIBER_TYPE", "106")),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        )


def _post_json(url: str, payload: dict, headers: dict) -> tuple[bool, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return (200 <= resp.status < 300), f"http_{resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:
        return False, type(exc).__name__


PHONE_CHARS = re.compile(r"^\+?[\d\s().-]{6,25}$")


def normalize_phone(raw: str) -> str:
    """'+38 (063) 111-22-33' -> '380631112233'; '' если это вообще не номер.

    Клиенты хранят телефоны как попало (пробелы, скобки, дефисы). Раньше сюда
    приходил int(phone) и НЕОБРАБОТАННЫЙ ValueError валил весь тик тенанта:
    один кривой контакт - и никто в этот прогон не получал касаний.
    """
    s = str(raw or "").strip()
    if not PHONE_CHARS.match(s):
        return ""
    digits = re.sub(r"\D", "", s)
    return digits if 8 <= len(digits) <= 15 else ""


def is_us_number(digits: str) -> bool:
    """Номер плана NANP (+1). TCPA: SMS без явного письменного согласия - иски
    $500-1500 за сообщение, поэтому в US шлём только email и in-app."""
    return len(digits) == 11 and digits.startswith("1")


# Длина сообщения зависит от канала и алфавита: в SMS латиница даёт 160
# знаков на сегмент, кириллица - 70 (UCS-2). Длинный текст оператор бьёт на
# части и берёт за каждую - поэтому режем сами и предсказуемо.
SMS_GSM, SMS_UNICODE, SMS_SEGMENTS = 160, 70, 2
TELEGRAM_LIMIT = 4096


def fit_sms(text: str) -> str:
    """Текст под SMS: два сегмента максимум, обрыв по слову."""
    body = " ".join(str(text or "").split())
    per = SMS_GSM if all(ord(ch) < 128 for ch in body) else SMS_UNICODE
    limit = per * SMS_SEGMENTS
    if len(body) <= limit:
        return body
    cut = body[:limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.6 else cut).rstrip(" ,.;:") + "…"


def fit_telegram(text: str) -> str:
    body = str(text or "").strip()
    return body if len(body) <= TELEGRAM_LIMIT else body[:TELEGRAM_LIMIT - 1] + "…"


def send_sms(phone: str, text: str, cfg: MessagingConfig) -> tuple[bool, str]:
    num = normalize_phone(phone)
    if not num:
        return False, "invalid_phone"
    if is_us_number(num):
        return False, "us_sms_blocked"
    if cfg.dry_run:
        print(f"[sms dry_run] to={num} text={text[:60]!r}", flush=True)
        return True, "dry_run"
    if not cfg.decision_api_key or not cfg.sms_sender:
        return False, "sms_not_configured"
    return _post_json(DECISION_SMS_URL,
                      {"phone": int(num), "sender": cfg.sms_sender,
                       "text": fit_sms(text)},
                      {"Authorization": f"Basic {cfg.decision_api_key}"})


def send_viber(phone: str, text: str, cfg: MessagingConfig) -> tuple[bool, str]:
    num = normalize_phone(phone)
    if not num:
        return False, "invalid_phone"
    if cfg.dry_run:
        print(f"[viber dry_run] to={num} text={text[:60]!r}", flush=True)
        return True, "dry_run"
    if not cfg.decision_api_key or not cfg.viber_sender:
        return False, "viber_not_configured"
    return _post_json(DECISION_VIBER_URL,
                      {"source_addr": cfg.viber_sender, "destination_addr": int(num),
                       "message_type": cfg.viber_message_type, "text": fit_telegram(text),
                       "source_type": 1, "validity_period": 3600},
                      {"Authorization": f"Basic {cfg.decision_api_key}"})


def send_whatsapp(phone: str, text: str, cfg: MessagingConfig) -> tuple[bool, str]:
    if not normalize_phone(phone):
        return False, "invalid_phone"
    if cfg.dry_run:
        print(f"[whatsapp dry_run] to={phone} text={text[:60]!r}", flush=True)
        return True, "dry_run"
    # WhatsApp Business требует онбординга номера/шаблонов у DT - включим после
    return False, "whatsapp_requires_waba_onboarding"


def send_telegram(chat_id: str, text: str, cfg: MessagingConfig) -> tuple[bool, str]:
    if cfg.dry_run:
        print(f"[telegram dry_run] chat={chat_id} text={text[:60]!r}", flush=True)
        return True, "dry_run"
    if not cfg.telegram_bot_token:
        return False, "telegram_not_configured"
    return _post_json(f"{TG_API}/bot{cfg.telegram_bot_token}/sendMessage",
                      {"chat_id": chat_id, "text": fit_telegram(text)}, {})


def route_message(channel: str, address: str, subject: str, body: str,
                  email_cfg: "EmailConfig", msg_cfg: MessagingConfig,
                  ctx: dict | None = None) -> tuple[bool, str]:
    """Единая точка отправки для campaign_tick: канал -> нужный сендер."""
    if channel == "email":
        return send_email(address, subject, body, email_cfg, ctx)
    text = render(body, {"app_url": email_cfg.app_url,
                         "card_update_url": email_cfg.card_update_url, **(ctx or {})})
    if unresolved(text):
        return False, "unresolved_placeholder"
    if channel == "sms":
        return send_sms(address, text, msg_cfg)
    if channel == "viber":
        return send_viber(address, text, msg_cfg)
    if channel == "whatsapp":
        return send_whatsapp(address, text, msg_cfg)
    if channel == "telegram":
        return send_telegram(address, text, msg_cfg)
    return False, f"unknown_channel:{channel}"


# ── Per-tenant отправители: инфраструктура наша - ИДЕНТИЧНОСТЬ клиента ────────
# Письма уходят с домена тенанта (DKIM/SPF на его поддомене, верифицированном
# в нашем Resend), SMS/Viber - с его альфа-имени, Telegram - его брендированный
# бот. Конфиг: secrets/tenants.json (в git не попадает, монтируется томом):
#   {"hubcontent": {"email_from": "Hub Content <care@mail.hubcontent.com>",
#                   "sms_sender": "HubContent", "viber_sender": "HubContent",
#                   "telegram_bot_token": "..."}}
# Env-переменные остаются платформенным фолбэком (dev/наши собственные письма).

TENANTS_FILE = os.environ.get("TENANTS_FILE", "/secrets/tenants.json")


def load_tenant_channels(tenant_id: str) -> dict:
    try:
        with open(TENANTS_FILE) as fh:
            return json.load(fh).get(tenant_id, {}) or {}
    except Exception:
        return {}


def tenant_configs(tenant_id: str, email_cfg: EmailConfig,
                   msg_cfg: MessagingConfig) -> tuple[EmailConfig, MessagingConfig]:
    """Поверх env-конфигов накладывает идентичность тенанта (from/имена/бот)."""
    from dataclasses import replace
    tc = load_tenant_channels(tenant_id)
    brand = str((tc.get("onboarding_answers") or {}).get("product_name")
                or tc.get("product_name") or "")
    email_cfg = replace(email_cfg, tenant_id=tenant_id, brand=brand)
    # Ключ Resend: СВОЙ аккаунт клиента важнее платформенного. Так клиент сам
    # платит за отправку, сам владеет репутацией домена и видит свою
    # статистику - а мы не отвечаем за чужой контент своим аккаунтом.
    if tc.get("resend_api_key"):
        email_cfg = replace(email_cfg, resend_api_key=str(tc["resend_api_key"]))
    if tc.get("email_from"):
        email_cfg = replace(email_cfg, email_from=str(tc["email_from"]))
    msg_over = {}
    for src, dst in (("sms_sender", "sms_sender"), ("viber_sender", "viber_sender"),
                     ("telegram_bot_token", "telegram_bot_token")):
        if tc.get(src):
            msg_over[dst] = str(tc[src])
    if msg_over:
        msg_cfg = replace(msg_cfg, **msg_over)
    return email_cfg, msg_cfg


# ── Что делать со сбоем отправки ─────────────────────────────────────────────
# Провайдер может лечь на минуту (5xx), придушить нас лимитом (429) или сеть
# моргнёт. Такое касание НЕЛЬЗЯ считать отработанным: письмо о несписании,
# потерянное из-за таймаута, стоит денег. Всё остальное (4xx, кривой номер,
# канал не настроен) повторять бессмысленно.
PERMANENT_REASONS = frozenset({
    "dry_run", "invalid_phone", "us_sms_blocked", "email_not_configured",
    "sms_not_configured", "viber_not_configured", "telegram_not_configured",
    "whatsapp_requires_waba_onboarding",
})


def transient_failure(detail: str) -> bool:
    """True - сбой временный, стоит повторить на следующем тике."""
    d = str(detail or "").strip()
    if not d or d in PERMANENT_REASONS or d.startswith("unknown_channel"):
        return False
    if d.startswith("http_"):
        code = d[5:8]
        return code == "429" or code.startswith("5")
    return True   # имя исключения: таймаут, DNS, обрыв соединения
