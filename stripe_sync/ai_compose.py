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

try:
    # плоский контекст (saas-ops контейнер: /app = stripe_sync)
    from compose import AUTO_PREFIX, EXECUTOR_SCHEMAS, validate_offer
except ImportError:
    # пакетный контекст (board: /app = корень репо)
    from stripe_sync.compose import AUTO_PREFIX, EXECUTOR_SCHEMAS, validate_offer

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
_TIMEOUT = 60

AI_PREFIX = "AI_"


def resolve_provider(env: dict | None = None) -> tuple[str, str]:
    """(provider, api_key). Anthropic приоритетнее, OpenAI - фолбэк.
    ('', '') = AI выключен."""
    e = env if env is not None else os.environ
    a = str(e.get("ANTHROPIC_API_KEY", "") or "").strip()
    if a:
        return "anthropic", a
    o = str(e.get("OPENAI_API_KEY", "") or "").strip()
    if o:
        return "openai", o
    return "", ""

# Мастер-промпт офферов v2. База: knowledge/lifecycle_playbook.md (§2 иерархия,
# §4 типы бизнесов, §6 ограничители). role - для точной привязки к кампаниям.
SYSTEM = """You are a subscription-retention economist composing the incentive
catalog for ONE SaaS product. Output ONLY valid JSON:
{"offers": [{"offer_id": "...", "role": "...", "title": "...", "executor": "...",
"monetary": true, "cost_estimate": 0.0, "max_per_user_30d": 1, "params": {...}}]}

Executors and their exact params (no other keys allowed):
- client_callback: amount (number - how many units to grant), unit (string - the
  product's own value unit), expires_days (number, optional), days (number,
  optional - for time-limited feature unlock), feature (string, optional).
  Use ONLY if client_api=true. This credits value INSIDE the client's product.
- stripe_coupon: percent_off (number), duration ("once"|"repeating"|"forever"),
  duration_in_months (number, required when duration="repeating").
- trial_extend: days (number).
- pause_collection: months (number).
- balance_credit: amount_usd (number).

role - which lifecycle lever this offer serves (exactly one of):
"activation" | "conversion" | "dunning" | "save" | "upgrade" | "winback"

Offer-selection doctrine (value-first hierarchy, follow it):
1. Product units (client_callback) - cheapest real value; first choice for
   activation on usage-based products. Grant ~15-25% of a monthly allowance,
   expiring in 14 days.
2. Time (trial_extend) - zero cost; first choice for conversion when a trial
   exists (extend by min(7, trial length)).
3. Pause (pause_collection, 1 month) - first choice for save when allowed.
4. Balance credit (~20% of one month, cap $25) - dunning softener or save
   gesture; requires discounts to be allowed.
5. Discount (stripe_coupon) - LAST resort, trains bargain-hunting: use only
   for upgrade (annual switch) or as the final save/conversion push.
   Never above max_discount_pct; if it is 0 - no coupons and no balance_credit.

Business-type adaptation:
- B2B seat-based (unit is seats/members/users): NEVER create a
  client_callback offer whose amount grants seats/members/users - that is raw
  revenue, it will be rejected. Gift time (trial_extend) or a feature unlock
  (client_callback with feature + days, NO amount) instead; formal tone.
- Usage-based (tokens/credits/renders/shoots): unit gifts everywhere.
- Prosumer low-price (<$15): prefer content/feature unlocks and pause over
  discounts.

Economics: cost_estimate is honest USD (coupon = price x pct x months; units =
price/allowance x amount). Monetary offers max_per_user_30d = 1; non-monetary
up to 2. Payback rule: one issue must pay back within 3 months of saved MRR.

Naming: offer_id = descriptive snake_case with the number in it (bonus_shoots_6,
discount20_2mo, trial_plus7) - no prefixes, unique. Titles are shown to the
client's USERS in the product's own language: short, concrete, name the unit.
No emoji, no em-dash.

Winback (canceled 30+ days ago): one strong ONE-TIME discount (duration
"once", up to max_discount_pct, cap 30) - the single case where a bold
discount is correct.

Produce 4-7 offers covering DIFFERENT roles (at least activation, conversion,
save, upgrade, winback when the answers allow them)."""


def build_user_prompt(answers: dict, avg_price: float) -> str:
    return (
        "Product answers (questionnaire):\n" + json.dumps(answers, ensure_ascii=False)
        + f"\nAverage plan price from Stripe: ${avg_price:.2f}"
        + "\nCompose the offer set now."
    )


def _call_anthropic(api_key: str, system: str, user: str) -> str:
    payload = json.dumps({
        "model": ANTHROPIC_MODEL, "max_tokens": 1500,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": api_key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    return "".join(b.get("text", "") for b in data.get("content", []))


def _call_openai(api_key: str, system: str, user: str) -> str:
    payload = json.dumps({
        "model": OPENAI_MODEL, "max_tokens": 1500,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        OPENAI_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")


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
        role = str(raw.pop("role", "") or "").lower()
        if role not in ("activation", "conversion", "dunning", "save", "upgrade", "winback"):
            role = ""
        clean, reason = validate_offer(raw)
        if reason:
            rejected.append(f"{raw.get('offer_id', '?')}:{reason}")
            continue
        if role:
            clean["role"] = role
        clean["title"] = _sanitize(clean["title"])
        seatish = str(clean["params"].get("unit", "")).lower()
        if (clean["executor"] == "client_callback" and clean["params"].get("amount")
                and seatish in ("seat", "seats", "member", "members", "user", "users",
                                "место", "места", "мест")):
            rejected.append(f"{clean['offer_id']}:seats_gift_banned")
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


# Мастер-промпт копирайта v2. База: knowledge/lifecycle_playbook.md (§3
# психология по типам, §5 каркас). Структура цепочек фиксирована кодом.
COPY_SYSTEM = """You are a lifecycle copywriter. Write retention email/banner
copy for ONE SaaS product, in ITS voice, to ITS users. Output ONLY valid JSON:
{"K1_activation": {"0": {"subject": "...", "body": "..."}, "2": {...}},
 "K2_trial_conversion": {"0": {...}, "2": {...}},
 "K3_payment_recovery": {"0": {...}, "1": {...}, "2": {...}, "3": {...}},
 "K4_save": {"1": {...}, "2": {...}}, "K5_upgrade": {"0": {...}, "2": {...}},
 "K6_winback": {"0": {...}, "2": {...}}}

The skeleton is fixed - write copy ONLY for these steps, with this intent:

K1 activation (signed up, no first result in 48h):
  step 0 email: remove friction - name the ONE next action and how few minutes
    it takes; mention the starter bonus they received.
  step 2 email (48h later): social proof path - what most users do first;
    invite a reply if stuck.
K2 trial ending (<=3 days, unpaid):
  step 0 email: loss aversion - what they LOSE (their work, settings, history),
    explicit deadline, upgrade as the way to keep it.
  step 2 email: "we added extra days" - frame the extension as care, suggest
    trying one advanced feature meanwhile.
K3 payment failed (dunning):
  step 0 in-app banner: one calm line + card update action, 30 seconds.
  step 1 email (same hour): reassure - card issue not their fault, work is
    safe, we retry automatically. MUST contain {{card_update_url}}.
  step 2 email (24h): short reminder, zero drama. MUST contain
    {{card_update_url}}.
  step 3 email (72h): honest last call - access pauses soon, still 30 seconds
    to fix. Firm but never threatening. MUST contain {{card_update_url}}.
K4 save (STILL SUBSCRIBED, opened cancel flow or went quiet):
  step 1 email: acknowledge the right to leave; pause for a month as the
    no-cost alternative (keep history and data, pay nothing).
  step 2 email (72h): their investment - what they already built here - plus
    one recent improvement they have not tried yet. They have NOT left: never
    write as if the subscription is already over.
K5 upgrade (80%+ of plan limit):
  step 0 email: compliment the power use, then the math - the higher tier is
    cheaper per unit at their volume.
  step 2 email: the annual option in plain numbers for heavy months.
K6 winback (canceled 30+ days ago):
  step 0 email: no guilt - what is NEW in the product since they left, one
    concrete improvement.
  step 2 email: their account and history are safe, the door is open.

Hard rules:
- Past-departure voice ("since you left", "welcome back", "come back to us",
  "now that you are gone") belongs ONLY to K6 winback. In K1-K5 the person is
  still a user or still paying - addressing them as a leaver is a factual
  error and the step gets thrown away.
- Subjects under 60 chars, bodies 1-3 sentences, ONE call to action per email.
- Use the product name and its value unit naturally - never a generic
  "your product" voice.
- Keep placeholders {{card_update_url}} and {{app_url}} EXACTLY where a link
  belongs (double curly braces, verbatim). Every K3 email step (1,2,3) MUST
  include {{card_update_url}} - an email asking to update a card without the
  link is a broken email. No other placeholders.
- Never invent numbers, discounts or bonus amounts - offers are attached by
  the platform separately. Refer to them generically ("your starter bonus").
- No emoji, no em-dash, no ALL CAPS, no fake urgency, no guilt-tripping.
- If "site_profile" is present in the input, ground the copy in it: speak
  to its audience, and in K1 point at the aha_moment as the first action.
"""


def _sanitize(txt: str) -> str:
    """Правила бренда жёстко в коде, а не на доверии к модели: длинные тире
    (em/en) -> обычный дефис. Промпт просит - код гарантирует."""
    return (txt.replace("\u2014", " - ").replace("\u2013", "-")
               .replace("  ", " ").strip())


LEAVER_PHRASES = (
    "since you left", "since you've left", "since you have left",
    "after you left", "when you left", "you left us",
    "welcome back", "come back to us", "now that you are gone",
    "now that you're gone", "since you cancel", "after you cancel",
    "your former", "you used to be",
)


def _talks_to_leaver(text: str) -> bool:
    """Речь про уже ушедшего юзера. Уместна только в винбэке."""
    low = " ".join(str(text or "").lower().split())
    return any(p in low for p in LEAVER_PHRASES)


def parse_ai_copy(text: str) -> dict:
    """JSON модели -> {campaign_id: {int_idx: {subject, body}}} с обрезкой длин.
    Кривой JSON -> {} (вызывающий остаётся на детерминированных шаблонах)."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        doc = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}
    out = {}
    for cid, steps in (doc or {}).items():
        if not isinstance(steps, dict):
            continue
        clean = {}
        for idx, txt in steps.items():
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            if not isinstance(txt, dict):
                continue
            subject = _sanitize(str(txt.get("subject", "")))[:200]
            body = _sanitize(str(txt.get("body", "")))[:2000]
            if not body:
                continue
            # дуннинг-письма обязаны нести ссылку обновления карты - иначе
            # письмо без действия; шаг отбрасывается (останется шаблон)
            if str(cid) == "K3_payment_recovery" and i in (1, 2, 3)                     and "{{card_update_url}}" not in body:
                continue
            # баннер без заголовка - обрубок; шаг уходит на шаблон
            if str(cid) == "K3_payment_recovery" and i == 0 and not subject:
                continue
            # «с тех пор как вы ушли» человеку, который НЕ уходил: фактическая
            # ошибка модели. Такое письмо обесценивает всю рассылку - шаг
            # выбрасываем, остаётся нейтральный шаблон.
            if str(cid) != "K6_winback" and _talks_to_leaver(subject + " " + body):
                continue
            clean[i] = {"subject": subject, "body": body}
        if clean:
            out[str(cid)] = clean
    return out


def ai_compose_copy(answers: dict) -> tuple[dict, str]:
    """Тексты кампаний под продукт. ({}, note) при сбое - остаёмся на шаблонах."""
    provider, api_key = resolve_provider()
    if not provider:
        return {}, "ai_not_configured"
    call = _call_anthropic if provider == "anthropic" else _call_openai
    user = ("Product profile:\n" + json.dumps(answers, ensure_ascii=False)
            + "\nWrite the copy now.")
    try:
        text = call(api_key, COPY_SYSTEM, user)
    except urllib.error.HTTPError as exc:
        return {}, f"ai_http_{exc.code}"
    except Exception as exc:
        return {}, f"ai_{type(exc).__name__}"
    out = parse_ai_copy(text)
    return out, "" if out else "ai_empty"


def ai_compose(answers: dict, avg_price: float) -> tuple[list[dict], str]:
    """(офферы, note). Пустой список + note при любом сбое - вызывающий
    остаётся на детерминированной сборке."""
    provider, api_key = resolve_provider()
    if not provider:
        return [], "ai_not_configured"
    call = _call_anthropic if provider == "anthropic" else _call_openai
    try:
        text = call(api_key, SYSTEM, build_user_prompt(answers, avg_price))
    except urllib.error.HTTPError as exc:
        return [], f"ai_http_{exc.code}"
    except Exception as exc:
        return [], f"ai_{type(exc).__name__}"
    offers, rejected = parse_ai_offers(text, float(answers.get("max_discount_pct") or 0))
    if rejected:
        print(f"[ai_compose] отбраковано: {rejected}", flush=True)
    return offers, "" if offers else "ai_empty"
