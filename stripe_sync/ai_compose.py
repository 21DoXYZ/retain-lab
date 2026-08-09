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


def build_user_prompt(answers: dict, avg_price: float,
                      context: dict | None = None) -> str:
    """context - полный бизнес-контекст (business_context): без него промпт
    остаётся на анкете, и это допустимо только там, где базы нет (тесты)."""
    try:
        from business_context import context_block
    except ImportError:
        from stripe_sync.business_context import context_block  # type: ignore
    ctx = context if context is not None else {"claimed": answers, "measured": {}}
    return (
        context_block(ctx)
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
COPY_SYSTEM = """You are a top-tier lifecycle copywriter (the person who
writes save-flows and dunning for the best subscription companies). Write
retention email and in-app banner copy for ONE SaaS product, in ITS voice, to
ITS users. Output ONLY valid JSON:
{"K1_activation": {"0": {"subject": "...", "body": "..."}, "1": {...}, "2": {...}},
 "K2_trial_conversion": {"0": {...}, "1": {...}, "3": {...}},
 "K3_payment_recovery": {"0": {...}, "1": {...}, "2": {...}, "3": {...}},
 "K4_save": {"0": {...}, "1": {...}, "3": {...}},
 "K5_upgrade": {"0": {...}, "1": {...}, "3": {...}},
 "K6_winback": {"0": {...}, "3": {...}}}

THE FORMULA - every email body follows four beats, 40-120 words total:
1. HOOK: the reader's concrete outcome or pain, first sentence. Never open
   with what THEY did ("you signed up") - open with what they GET ("that
   brief on your desk is already a video").
2. SPECIFICITY: at least one real fact from the product profile - the value
   unit, the aha moment, a plan's included volume, a time contrast ("the work
   that normally eats an afternoon"). An email with zero product facts is
   generic filler and will be discarded.
3. ONE ACTION: exactly one link placeholder. The platform renders it as a
   button.
4. DE-RISK: close with safety - "reply, a person reads this" / "nothing was
   deleted" / "cancel anytime". Replies are how the platform learns WHY
   people leave; invite them wherever it is natural.

WHAT EACH CAMPAIGN SELLS (the message, not the feature):
K1 activation: the CONTRAST - hours of manual work vs minutes in the product.
  Motivate trying it on their ugliest real task. Step 2: how most users
  start. Final step subject is a question ("Did we get something wrong?") -
  blame-absorbing, asking for a one-line reply.
K2 trial ending: the MATH - what a paid month costs vs what one delivered
  piece of client work earns. Everything they made carries over. Never
  threaten deletion; state honestly that work stays saved.
K3 dunning: SAFETY and EASE - card issue is not their fault, work is safe,
  fix takes 30 seconds. Calm escalation: reminder -> access will pause if it
  keeps declining -> two weeks, nothing deleted -> final note that says the
  reminders stop. MUST contain {{card_update_url}} in every email step.
K4 save (STILL SUBSCRIBED): FIX THE REASON - something specific broke for
  them (quality, price, missing feature). Ask for a one-line reply about
  what is off; promise a straight human answer. Only mention pausing if the
  profile says can_pause is true - promising a pause the product cannot do
  is a lie on autopilot.
K5 upgrade: the GOOD PROBLEM - they burned through their plan because the
  product carries real volume. Sell headroom with the actual tier ratio from
  the profile plans (e.g. "2.5x the credits"). Step 3: annual math, hedged
  ("usually works out cheaper") unless plans prove it.
K6 winback: NOTHING IS LOST - their workspace is untouched, coming back is
  cheaper than starting over. One email asks the honest question "what made
  you leave?". The final email promises to stop - and means it.

HARD RULES (a validator rejects violations):
- Exactly one link placeholder per email: {{app_url}} or {{card_update_url}},
  double curly braces verbatim. No other placeholders. In-app banner bodies:
  ONE sentence, no links.
- No exclamation marks anywhere. No ALL CAPS. No hurry/act now/last
  chance/limited time. Fake urgency reads as spam and dies in the filter.
- Never promise capabilities absent from the profile: no pause when
  can_pause is false, no trial extensions, no invented discounts or numbers.
  Offers are attached by the platform separately.
- Past-departure voice ("since you left", "welcome back") ONLY in K6.
- Subjects under 60 chars, concrete, no colon-litter. Questions welcome
  where the email asks one.
- No emoji, no em-dash. Write like a founder who respects the reader, not
  a marketing department.
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


def parse_ai_copy(text: str, profile: dict | None = None) -> dict:
    """JSON модели -> {campaign_id: {int_idx: {subject, body}}} с обрезкой длин.
    Кривой JSON -> {} (вызывающий остаётся на детерминированных шаблонах).
    Каждый шаг дополнительно проходит методологию текстов (copy_review):
    fatal-флаг = шаг выброшен, останется нейтральный шаблон."""
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
            if i == 0 and not subject and str(cid) in (
                    "K1_activation", "K2_trial_conversion",
                    "K3_payment_recovery", "K4_save", "K5_upgrade"):
                continue
            # «с тех пор как вы ушли» человеку, который НЕ уходил: фактическая
            # ошибка модели. Такое письмо обесценивает всю рассылку - шаг
            # выбрасываем, остаётся нейтральный шаблон.
            if str(cid) != "K6_winback" and _talks_to_leaver(subject + " " + body):
                continue
            if profile is not None:
                try:
                    from copy_review import fatal, review_step
                except ImportError:
                    from stripe_sync.copy_review import fatal, review_step  # type: ignore
                role = "inapp" if i == 0 and str(cid) != "K6_winback" else "email"
                if fatal(review_step(subject, body, str(cid), role, profile)):
                    continue
            clean[i] = {"subject": subject, "body": body}
        if clean:
            out[str(cid)] = clean
    return out


def ai_compose_copy(answers: dict, context: dict | None = None) -> tuple[dict, str]:
    """Тексты кампаний под продукт. ({}, note) при сбое - остаёмся на шаблонах."""
    provider, api_key = resolve_provider()
    if not provider:
        return {}, "ai_not_configured"
    call = _call_anthropic if provider == "anthropic" else _call_openai
    try:
        from business_context import context_block
    except ImportError:
        from stripe_sync.business_context import context_block  # type: ignore
    ctx = context if context is not None else {"claimed": answers, "measured": {}}
    user = context_block(ctx) + "\nWrite the copy now."
    try:
        text = call(api_key, COPY_SYSTEM, user)
    except urllib.error.HTTPError as exc:
        return {}, f"ai_http_{exc.code}"
    except Exception as exc:
        return {}, f"ai_{type(exc).__name__}"
    out = parse_ai_copy(text, profile=answers)
    return out, "" if out else "ai_empty"


def ai_compose(answers: dict, avg_price: float,
               context: dict | None = None) -> tuple[list[dict], str]:
    """(офферы, note). Пустой список + note при любом сбое - вызывающий
    остаётся на детерминированной сборке."""
    provider, api_key = resolve_provider()
    if not provider:
        return [], "ai_not_configured"
    call = _call_anthropic if provider == "anthropic" else _call_openai
    try:
        text = call(api_key, SYSTEM, build_user_prompt(answers, avg_price, context))
    except urllib.error.HTTPError as exc:
        return [], f"ai_http_{exc.code}"
    except Exception as exc:
        return [], f"ai_{type(exc).__name__}"
    offers, rejected = parse_ai_offers(text, float(answers.get("max_discount_pct") or 0))
    if rejected:
        print(f"[ai_compose] отбраковано: {rejected}", flush=True)
    return offers, "" if offers else "ai_empty"
