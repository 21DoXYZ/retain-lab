"""AI-компоновщик офферов: LLM поверх опросника (Anthropic Messages API).

Роль LLM - ПРЕДЛОЖИТЬ офферы под конкретный продукт (названия, щедрость,
комбинации), но НИЧЕГО не исполняет: каждый ответ прогоняется через
compose.validate_offer (те же схемы исполнителей, что и у ручного создания)
и гигиенические потолки. Невалидное отбрасывается с логом. Fail-soft: нет
ANTHROPIC_API_KEY / сеть упала / JSON кривой -> вызывающий код спокойно
остаётся на детерминированном compose_offers.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from compose import AUTO_PREFIX, EXECUTOR_SCHEMAS, validate_offer

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
_TIMEOUT = 60

AI_PREFIX = "AI_"

SYSTEM = """You compose retention offers for a SaaS product. You output ONLY valid JSON:
{"offers": [{"offer_id": "...", "title": "...", "executor": "...", "monetary": true,
"cost_estimate": 0.0, "max_per_user_30d": 1, "params": {...}}]}

Executors and their exact params (no other keys allowed):
- client_callback: command (string, e.g. "tokens_credit"), tokens (number, optional),
  days (number, optional), expires_days (number, optional), feature (string, optional).
  Use ONLY if the client has an API (client_api=true). This credits value inside their product.
- stripe_coupon: percent_off (number), duration ("once"|"repeating"|"forever"),
  duration_in_months (number, required when duration="repeating").
- trial_extend: days (number).
- pause_collection: months (number).
- balance_credit: amount_usd (number).

Hard rules:
- 3 to 6 offers, each a DIFFERENT retention lever (activation nudge, dunning softener,
  save alternative, conversion push, upgrade reward).
- percent_off never above max_discount_pct from the answers; if it is 0, no coupons and
  no balance_credit at all.
- cost_estimate = realistic $ cost of one issue (coupon: price x pct x months).
- max_per_user_30d: 1 for monetary offers, up to 2 for non-monetary.
- offer_id: short snake_case, unique, no prefix (it is added by the platform).
- Titles are shown to the CLIENT's users - write them in the product's language
  (use the value unit name), short and concrete. No emoji, no em-dash.
"""


def build_user_prompt(answers: dict, avg_price: float) -> str:
    return (
        "Product answers (questionnaire):\n" + json.dumps(answers, ensure_ascii=False)
        + f"\nAverage plan price from Stripe: ${avg_price:.2f}"
        + "\nCompose the offer set now."
    )


def _call(api_key: str, system: str, user: str) -> str:
    payload = json.dumps({
        "model": MODEL, "max_tokens": 1500,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        API_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": api_key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    return "".join(b.get("text", "") for b in data.get("content", []))


def parse_ai_offers(text: str, max_discount_pct: float) -> tuple[list[dict], list[str]]:
    """JSON от модели -> валидные офферы (+ причины отбраковки). Чистая."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        doc = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return [], ["ai_json_parse_failed"]

    out, rejected = [], []
    seen = set()
    for raw in (doc.get("offers") or [])[:6]:
        clean, reason = validate_offer(raw)
        if reason:
            rejected.append(f"{raw.get('offer_id', '?')}:{reason}")
            continue
        # потолок скидки - железный, что бы модель ни решила
        pct = clean["params"].get("percent_off")
        if pct is not None and float(pct) > float(max_discount_pct):
            rejected.append(f"{clean['offer_id']}:discount_over_ceiling")
            continue
        if float(max_discount_pct) <= 0 and clean["executor"] in ("stripe_coupon", "balance_credit"):
            rejected.append(f"{clean['offer_id']}:monetary_not_allowed")
            continue
        oid = AI_PREFIX + (clean["offer_id"] or "offer").removeprefix(AI_PREFIX).removeprefix(AUTO_PREFIX)
        if oid in seen:
            rejected.append(f"{oid}:duplicate")
            continue
        seen.add(oid)
        clean["offer_id"] = oid
        out.append(clean)
    return out, rejected


def ai_compose(answers: dict, avg_price: float) -> tuple[list[dict], str]:
    """(офферы, note). Пустой список + note при любом сбое - вызывающий
    остаётся на детерминированной сборке."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return [], "ai_not_configured"
    try:
        text = _call(api_key, SYSTEM, build_user_prompt(answers, avg_price))
    except urllib.error.HTTPError as exc:
        return [], f"ai_http_{exc.code}"
    except Exception as exc:
        return [], f"ai_{type(exc).__name__}"
    offers, rejected = parse_ai_offers(text, float(answers.get("max_discount_pct") or 0))
    if rejected:
        print(f"[ai_compose] отбраковано: {rejected}", flush=True)
    return offers, "" if offers else "ai_empty"
