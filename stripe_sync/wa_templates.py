"""Шаблоны WhatsApp из текстов кампаний + connect-ссылка «сначала пишет человек».

ШАБЛОНЫ ИЗ КАМПАНИЙ. Вне 24-часового окна Cloud API принимает только заранее
одобренные шаблоны. Тексты касаний у нас уже есть (каркас + генерация под
продукт) - этот модуль превращает шаг кампании в шаблон Meta:
  - плейсхолдеры {{app_url}} -> позиционные {{1}}, {{2}} (формат Meta);
  - категория по кампании: дуннинг и триал - UTILITY (дёшево), винбэк и
    апгрейд - MARKETING. В UTILITY НИ СЛОВА ПРОМО: Meta переклассифицирует,
    и цена вырастает втрое;
  - имя versioned: retivo_<tenant>_<кампания>_s<шаг>_v<n> - правка текста
    означает НОВЫЙ шаблон на одобрение, старый работает до одобрения нового.

Реестр одобрений живёт в tenants.json (wa_templates: {имя: статус}) и
обновляется вебхуком message_template_status_update. Слать можно только
APPROVED - шаг с неодобренным шаблоном отбивается с причиной, а не молчит.

CONNECT-ССЫЛКА. wa.me/<номер>?text=<START_...> открывает у человека WhatsApp
с готовым сообщением. Отправив его, он делает три вещи сразу: даёт нам номер
и привязку к аккаунту (подписанный payload, как в telegram), даёт железный
opt-in (написал первым) и открывает 24-часовое окно бесплатных ответов.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import urllib.parse

try:                                    # борд импортирует пакетом, джобы плоско
    from email_delivery import UNSUB_SECRET
    from telegram_connect import _b64u, _b64u_decode
except ImportError:
    from stripe_sync.email_delivery import UNSUB_SECRET  # type: ignore
    from stripe_sync.telegram_connect import _b64u, _b64u_decode  # type: ignore

# Категория по кампании. Правило методологии: дуннинг - сервис, не реклама.
CAMPAIGN_CATEGORY = {
    "K1_activation": "UTILITY",         # человек зарегистрировался и не начал
    "K2_trial_conversion": "UTILITY",   # его триал заканчивается - факт аккаунта
    "K3_payment_recovery": "UTILITY",   # сломалась оплата
    "K4_save": "MARKETING",             # удержание - уже убеждение
    "K5_upgrade": "MARKETING",
    "K6_winback": "MARKETING",
}

# Слова, после которых Meta переклассифицирует UTILITY в MARKETING. Ловим ДО
# отправки на одобрение: отклонённый шаблон - минус к качеству WABA.
PROMO_WORDS = re.compile(
    r"\b(off|discount|sale|deal|promo|free|bonus|upgrade|offer|save \d|"
    r"скидк|акци|бонус|подарок|дар)\w*\b", re.IGNORECASE)


def to_meta_body(text: str) -> tuple[str, list[str]]:
    """Текст шага -> тело шаблона Meta + список имён параметров по порядку.

    Наши именованные плейсхолдеры ({{card_update_url}}) становятся
    позиционными ({{1}}) - Meta других не принимает. Имена возвращаются,
    чтобы отправка знала, ЧТО подставлять в какую позицию.
    """
    names: list[str] = []

    def swap(m: re.Match) -> str:
        names.append(m.group(1))
        return "{{" + str(len(names)) + "}}"

    body = re.sub(r"\{\{(\w+)\}\}", swap, str(text or "")).strip()
    return body[:1024], names


def template_name(tenant: str, campaign_id: str, step_idx: int,
                  version: int = 1) -> str:
    """Meta: только [a-z0-9_], до 512. Versioned: правка текста = новый шаблон."""
    slug = re.sub(r"[^a-z0-9_]", "_", f"{tenant}_{campaign_id}".lower())
    return f"retivo_{slug}_s{step_idx}_v{version}"[:512]


def build_from_step(tenant: str, campaign_id: str, step_idx: int,
                    step: dict, version: int = 1) -> tuple[dict | None, str]:
    """Шаг кампании -> заявка на шаблон. (payload, '') либо (None, причина).

    UTILITY-шаблон с промо-словами не отправляем на одобрение вовсе: Meta
    его переклассифицирует или отклонит, и то и другое бьёт по качеству WABA
    и по цене. Такой текст честнее переписать.
    """
    body, param_names = to_meta_body(str(step.get("body") or ""))
    if not body:
        return None, "empty_body"
    category = CAMPAIGN_CATEGORY.get(campaign_id, "MARKETING")
    if category == "UTILITY" and PROMO_WORDS.search(body):
        return None, "promo_words_in_utility"
    return {
        "name": template_name(tenant, campaign_id, step_idx, version),
        "category": category,
        "body": body,
        "param_names": param_names,
    }, ""


def approved(registry: dict, name: str) -> bool:
    """Можно ли слать этот шаблон. Реестр: {имя: 'APPROVED'|'PENDING'|...}."""
    return str((registry or {}).get(name) or "").upper() == "APPROVED"


# ── Connect-ссылка: человек пишет первым ─────────────────────────────────────

def _sig(tenant: str, uid: str, secret: str = "") -> str:
    key = (secret or UNSUB_SECRET).encode()
    return hmac.new(key, f"wa|{tenant}|{uid}".encode(),
                    hashlib.sha256).hexdigest()[:10]


def connect_text(tenant: str, uid: str, secret: str = "") -> str:
    """Готовый текст для wa.me: человекочитаемый + подписанный код привязки."""
    uid = str(uid or "").strip()
    if not uid:
        return ""
    code = f"START_{_b64u(uid.encode())}_{_sig(tenant, uid, secret)}"
    return f"Connect my account ({code})"


def parse_connect_text(tenant: str, text: str, secret: str = "") -> str:
    """Входящее сообщение -> uid, если в нём наш код привязки. '' - нет/подделка."""
    m = re.search(r"START_([A-Za-z0-9_-]+)_([0-9a-f]{10})", str(text or ""))
    if not m:
        return ""
    try:
        uid = _b64u_decode(m.group(1)).decode()
    except Exception:
        return ""
    if not hmac.compare_digest(m.group(2), _sig(tenant, uid, secret)):
        return ""
    return uid


def connect_url(phone_display: str, tenant: str, uid: str,
                secret: str = "") -> str:
    """Ссылка wa.me для конкретного юзера. '' - канал не настроен."""
    digits = re.sub(r"\D", "", str(phone_display or ""))
    text = connect_text(tenant, uid, secret)
    if not digits or not text:
        return ""
    return f"https://wa.me/{digits}?text={urllib.parse.quote(text)}"


def pick_template(registry, campaign_id: str, step_idx: int) -> tuple[str, tuple]:
    """Одобренный шаблон шага из реестра. ('', ()) - слать нечем.

    registry - кортеж (имя, статус, кампания, шаг, версия, params) из
    MessagingConfig (dataclass заморожен, поэтому не dict). Версий может быть
    несколько: правка текста = новый шаблон, работает старший ОДОБРЕННЫЙ.
    """
    best: tuple | None = None
    for row in registry or ():
        name, status, cid, idx, version, params = (tuple(row) + ("",) * 6)[:6]
        if str(cid) != str(campaign_id) or int(idx) != int(step_idx):
            continue
        if str(status).upper() != "APPROVED":
            continue
        if best is None or int(version) > int(best[4]):
            best = (name, status, cid, idx, int(version), tuple(params or ()))
    if best is None:
        return "", ()
    return str(best[0]), tuple(best[5])
