"""Email-канал SaaS-кампаний: Resend API либо dry-run (дефолт, как senders.py).

DRY_RUN (SIGNALS_DRY_RUN=1 по умолчанию): письмо печатается, в сеть не уходит.
Реальный режим: RESEND_API_KEY + EMAIL_FROM (домен с DKIM/SPF — warm-up по
плану Phase 4). Плейсхолдеры {{...}} рендерятся из контекста; неизвестные
остаются как есть (видно в логе, что не хватает).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

_TIMEOUT = 30


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


def send_email(to: str, subject: str, body: str, cfg: EmailConfig,
               ctx: dict | None = None) -> tuple[bool, str]:
    context = {"app_url": cfg.app_url, "card_update_url": cfg.card_update_url}
    context.update(ctx or {})
    subject_r, body_r = render(subject, context), render(body, context)

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
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return (200 <= resp.status < 300), f"http_{resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:
        return False, type(exc).__name__


def send_sms(phone: str, text: str, cfg: MessagingConfig) -> tuple[bool, str]:
    if cfg.dry_run:
        print(f"[sms dry_run] to={phone} text={text[:60]!r}", flush=True)
        return True, "dry_run"
    if not cfg.decision_api_key or not cfg.sms_sender:
        return False, "sms_not_configured"
    return _post_json(DECISION_SMS_URL,
                      {"phone": int(phone), "sender": cfg.sms_sender, "text": text},
                      {"Authorization": f"Basic {cfg.decision_api_key}"})


def send_viber(phone: str, text: str, cfg: MessagingConfig) -> tuple[bool, str]:
    if cfg.dry_run:
        print(f"[viber dry_run] to={phone} text={text[:60]!r}", flush=True)
        return True, "dry_run"
    if not cfg.decision_api_key or not cfg.viber_sender:
        return False, "viber_not_configured"
    return _post_json(DECISION_VIBER_URL,
                      {"source_addr": cfg.viber_sender, "destination_addr": int(phone),
                       "message_type": cfg.viber_message_type, "text": text,
                       "source_type": 1, "validity_period": 3600},
                      {"Authorization": f"Basic {cfg.decision_api_key}"})


def send_whatsapp(phone: str, text: str, cfg: MessagingConfig) -> tuple[bool, str]:
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
                      {"chat_id": chat_id, "text": text}, {})


def route_message(channel: str, address: str, subject: str, body: str,
                  email_cfg: "EmailConfig", msg_cfg: MessagingConfig,
                  ctx: dict | None = None) -> tuple[bool, str]:
    """Единая точка отправки для campaign_tick: канал -> нужный сендер."""
    if channel == "email":
        return send_email(address, subject, body, email_cfg, ctx)
    text = render(body, {"app_url": email_cfg.app_url,
                         "card_update_url": email_cfg.card_update_url, **(ctx or {})})
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
