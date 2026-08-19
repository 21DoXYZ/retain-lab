"""Предполётный чеклист запуска: всё, что должно быть правдой ДО автопилота.

Каждая проверка отвечает на вопрос владельца «не опозоримся ли мы, когда
письма начнут доходить»: подписи и имена человечные, ссылки живые, тексты
без сырых плейсхолдеров и тире, предохранители на месте. Что можно проверить
кодом - проверяется кодом; что нельзя (ящик для ответов существует, DMARC у
клиента) - подтверждает владелец кнопкой, и это фиксируется.

Статусы: pass | warn | fail | manual (ждёт подтверждения владельца).
"""

from __future__ import annotations

import re

try:                                    # борд пакетом, джобы плоско
    from saas_senders import render, unresolved
except ImportError:
    from stripe_sync.saas_senders import render, unresolved  # type: ignore

# Полный контекст рендера: всё, что тик умеет подставлять. Плейсхолдер вне
# этого списка в тексте = письмо не уйдёт (fail-closed), значит fail здесь.
SAMPLE_CTX = {
    "app_url": "https://app.example.com",
    "card_update_url": "https://billing.example.com/update",
    "telegram_connect_url": "https://t.me/example_bot?start=x",
    "whatsapp_connect_url": "https://wa.me/1234?text=x",
    "credits_left": "0",
}

NOREPLY_RE = re.compile(r"no[-_.]?reply|donotreply", re.I)
HUMAN_FROM_RE = re.compile(r"^[^<>@]{2,60}<[^@\s]+@[^@\s]+>$")


def check_sender(email_from: str) -> dict:
    """Подпись отправителя: человечное имя + адрес, никаких noreply."""
    ef = str(email_from or "").strip()
    if not ef:
        return {"key": "sender", "status": "fail", "detail": ""}
    if NOREPLY_RE.search(ef):
        return {"key": "sender", "status": "fail", "detail": ef}
    if not HUMAN_FROM_RE.match(ef):
        return {"key": "sender", "status": "warn", "detail": ef}
    name = ef.split("<")[0].strip()
    # бренд-имя допустимо, но личное («Michael from X») читается человечнее
    status = "pass" if " " in name else "warn"
    return {"key": "sender", "status": status, "detail": ef}


def check_copy(conf: dict) -> list[dict]:
    """Тексты всех шагов: сырые плейсхолдеры (fail - письмо не уйдёт вовсе),
    длинные тире (правило бренда), пустые CTA."""
    bad_ph, dashes, bare_cta = [], [], []
    for camp in conf.get("campaigns", []):
        cid = camp.get("campaign_id", "")
        for i, s in enumerate(camp.get("steps", [])):
            if s.get("action") not in ("email", "inapp"):
                continue
            addr = f"{cid}#{i}"
            texts = [s.get("subject", ""), s.get("body", "")]
            for v in (s.get("variants") or []):
                texts += [v.get("subject", ""), v.get("body", "")]
            for txt in texts:
                if unresolved(render(str(txt or ""), SAMPLE_CTX)):
                    bad_ph.append(addr)
                if "—" in str(txt) or "–" in str(txt):
                    dashes.append(addr)
            if s.get("cta_url") and not s.get("cta_label"):
                bare_cta.append(addr)
    out = [{"key": "placeholders",
            "status": "fail" if bad_ph else "pass",
            "detail": ", ".join(sorted(set(bad_ph))[:6])}]
    out.append({"key": "dashes", "status": "warn" if dashes else "pass",
                "detail": ", ".join(sorted(set(dashes))[:6])})
    out.append({"key": "cta", "status": "warn" if bare_cta else "pass",
                "detail": ", ".join(sorted(set(bare_cta))[:6])})
    return out


def check_offers_bound(conf: dict) -> dict:
    """Каждый offer-шаг привязан: пустой offer_id = шаг молча отбивается."""
    empty = [f"{c.get('campaign_id')}#{i}"
             for c in conf.get("campaigns", [])
             for i, s in enumerate(c.get("steps", []))
             if s.get("action") == "offer" and not s.get("offer_id")]
    return {"key": "offers_bound", "status": "warn" if empty else "pass",
            "detail": ", ".join(empty[:6])}


def check_identity(tch: dict, tailored: bool) -> list[dict]:
    """Идентичность: имя продукта в текстах, домен, часовой пояс, app_url."""
    answers = tch.get("onboarding_answers") or {}
    out = [{"key": "tailored", "status": "pass" if tailored else "fail",
            "detail": str(answers.get("product_name") or "")}]
    out.append({"key": "domain",
                "status": "pass" if tch.get("email_domain_status") == "verified"
                else "fail",
                "detail": str(tch.get("email_domain") or "")})
    out.append({"key": "timezone",
                "status": "pass" if tch.get("timezone") else "warn",
                "detail": str(tch.get("timezone") or "UTC")})
    out.append({"key": "app_url",
                "status": "pass" if answers.get("app_url") else "fail",
                "detail": str(answers.get("app_url") or "")})
    return out


MANUAL_KEYS = ("reply_mailbox", "dmarc", "test_email_read")


def manual_items(confirms: dict) -> list[dict]:
    """Пункты, которые машина проверить не может - подтверждает владелец."""
    return [{"key": k,
             "status": "pass" if confirms.get(k) else "manual",
             "detail": ""} for k in MANUAL_KEYS]


def verdict(checks: list[dict]) -> str:
    """ready | almost | not_ready: fail всегда роняет, manual - «почти»."""
    statuses = {c["status"] for c in checks}
    if "fail" in statuses:
        return "not_ready"
    if "manual" in statuses or "warn" in statuses:
        return "almost"
    return "ready"
