"""База знаний о клиенте: не выписка с сайта, а разбор продукта.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ СКАНА. Скан достаёт ФАКТЫ: как называется продукт, что
написано на странице тарифов, сколько стоит. Этого мало: фраза с лендинга
(«AI video production platform that turns ideas into ready-to-publish content»)
- это их маркетинг, а не понимание, кого и чем мы будем удерживать.

Здесь второй проход: модель получает факты и текст сайта и отвечает на вопросы,
которые определяют ВСЮ дальнейшую механику удержания:
  • за что человек реально платит и что считается для него результатом;
  • когда наступает момент, после которого он остаётся (активация);
  • почему в этой категории уходят - и какой рычаг против этого работает;
  • чем НЕЛЬЗЯ дарить в этой модели (места в B2B, юниты при подписке за место).

РАЗДЕЛЕНИЕ ЧЕСТНОСТИ. facts - только то, что написано на сайте. analysis -
выводы модели, помеченные уверенностью. Ни один вывод не применяется сам:
он предзаполняет анкету и подсказывает офферы, решение за владельцем.

ПЕРЕСБОРКА. У клиента меняются тарифы и позиционирование. brief хранит версию
и время; refresh собирает заново и показывает, ЧТО ИМЕННО изменилось.
"""

from __future__ import annotations

import json

BRIEF_VERSION = 1

SYSTEM = """You are a retention strategist reading a SaaS company's own website.

You are NOT summarising the site. You are working out how this business keeps
customers, so that a retention system can act on it.

Output ONLY valid JSON:
{"what_it_does": "...", "who_for": "...", "job_to_be_done": "...",
 "value_unit": "...", "activation_moment": "...", "value_event_hint": "...",
 "pricing_model": "flat|per_seat|usage|unknown",
 "churn_drivers": ["...", "..."],
 "retention_levers": [{"lever": "bonus_units|trial_extension|pause|discount|credit",
                       "why": "...", "fit": "high|medium|low"}],
 "never_offer": ["..."],
 "confidence": "high|medium|low",
 "unknowns": ["..."]}

Rules:
- what_it_does: ONE plain sentence a person outside the industry understands.
  Strip marketing words. Not the tagline: what actually happens when someone
  uses it.
- job_to_be_done: the outcome the customer is buying, in their words, not the
  feature list.
- activation_moment: the first moment a new user gets real value. Concrete and
  observable in a product ("first video exported"), not vague ("understands
  the value").
- value_event_hint: what the tracking event for that moment would most likely
  be called in their product, lowercase with underscores.
- churn_drivers: 2-4 reasons people in THIS category stop paying, specific to
  this product and pricing model. No generic "bad onboarding".
- retention_levers: which incentives fit this business and why. In a per-seat
  product never propose gifting seats. In a usage product bonus units fit best.
  In a one-off-need product a pause fits better than a discount.
- never_offer: what would damage this business if given away.
- unknowns: what the site does not say but the owner must confirm.
- confidence: low when the site is thin or mostly marketing.
- No emoji, no em-dash. Never invent numbers - numbers come from the facts."""


def parse_brief(text: str) -> dict:
    """Ответ модели -> разбор с приведением типов. {} при кривом ответе."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        doc = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}

    def _s(key: str, limit: int) -> str:
        return str(doc.get(key) or "").replace("—", " - ").replace("–", "-").strip()[:limit]

    def _list(key: str, limit: int, item_len: int) -> list:
        raw = doc.get(key)
        if not isinstance(raw, list):
            return []
        return [str(x).replace("—", " - ").strip()[:item_len] for x in raw[:limit] if str(x).strip()]

    levers = []
    for item in (doc.get("retention_levers") or [])[:5]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("lever") or "").strip().lower()
        if name not in ("bonus_units", "trial_extension", "pause", "discount", "credit"):
            continue
        fit = str(item.get("fit") or "").lower()
        levers.append({"lever": name,
                       "why": str(item.get("why") or "").strip()[:200],
                       "fit": fit if fit in ("high", "medium", "low") else "medium"})

    model = _s("pricing_model", 20).lower()
    conf = _s("confidence", 10).lower()
    return {
        "what_it_does": _s("what_it_does", 240),
        "who_for": _s("who_for", 160),
        "job_to_be_done": _s("job_to_be_done", 200),
        "value_unit": _s("value_unit", 40).lower(),
        "activation_moment": _s("activation_moment", 160),
        "value_event_hint": _s("value_event_hint", 60).lower().replace(" ", "_"),
        "pricing_model": model if model in ("flat", "per_seat", "usage") else "unknown",
        "churn_drivers": _list("churn_drivers", 4, 160),
        "retention_levers": levers,
        "never_offer": _list("never_offer", 4, 120),
        "confidence": conf if conf in ("high", "medium", "low") else "low",
        "unknowns": _list("unknowns", 5, 120),
    }


def diff_briefs(old: dict, new: dict) -> list:
    """Что изменилось между разборами - человеческим языком, для экрана."""
    if not old:
        return []
    out = []
    labels = {
        "what_it_does": "описание продукта",
        "who_for": "аудитория",
        "value_unit": "единица ценности",
        "activation_moment": "момент активации",
        "pricing_model": "модель ценообразования",
    }
    for key, label in labels.items():
        was, now = str(old.get(key) or ""), str(new.get(key) or "")
        if was != now and now:
            out.append({"field": label, "was": was, "now": now})

    old_plans = {p.get("name", ""): p.get("price_usd") for p in (old.get("plans") or [])}
    new_plans = {p.get("name", ""): p.get("price_usd") for p in (new.get("plans") or [])}
    for name, price in new_plans.items():
        if name not in old_plans:
            out.append({"field": "новый тариф", "was": "", "now": f"{name}: ${price}"})
        elif old_plans[name] != price:
            out.append({"field": f"цена тарифа {name}",
                        "was": f"${old_plans[name]}", "now": f"${price}"})
    for name in old_plans:
        if name not in new_plans:
            out.append({"field": "тариф убран", "was": name, "now": ""})
    return out


def answers_from_brief(brief: dict, facts: dict) -> dict:
    """Предзаполнение анкеты: факты с сайта плюс выводы разбора.

    Разбор отвечает на то, чего на странице тарифов не написано словами -
    например, как назвать единицу ценности человеческим языком.
    """
    out = {}
    if facts.get("product_name"):
        out["product_name"] = facts["product_name"]
    # описание берём ИЗ РАЗБОРА: на сайте лежит маркетинговая фраза
    if brief.get("what_it_does"):
        out["product_desc"] = brief["what_it_does"]
    for key in ("value_unit", "monthly_units", "avg_plan_price", "trial_days"):
        if facts.get(key):
            out[key] = facts[key]
    if not out.get("value_unit") and brief.get("value_unit"):
        out["value_unit"] = brief["value_unit"]
    if facts.get("trial_days"):
        out["has_trial"] = True
    # в модели «за место» дарить юниты бессмысленно - подсказываем это анкете
    if brief.get("pricing_model") == "per_seat":
        out["client_api"] = False
    return out
