"""Селф-онбординг офферов: опросник -> детерминированная сборка каталога.

ЛОГИКА (каждый ответ управляет конкретными офферами, без магии):

  Вопрос                        -> Что генерируется
  ─────────────────────────────────────────────────────────────────────────
  value_unit («токены»/«кредиты»/  A_bonus_units: client_callback, бонус
  «экспорты»...) + monthly_units    = 20% месячного лимита, сгорает 14д.
  (лимит типового плана)            Требует client_api=yes (иначе продукту
                                    некуда начислить). cost = 20% от цены
                                    плана (условно: юнит стоит цену/лимит).
  ─────────────────────────────────────────────────────────────────────────
  max_discount_pct (потолок       A_discount: stripe_coupon percent_off =
  скидки, который владелец         min(20, потолок), repeating 2 месяца,
  готов давать)                    лимит 1/30д. Потолок 0 -> скидок нет.
                                   cost = цена x % x 2 мес.
  ─────────────────────────────────────────────────────────────────────────
  has_trial + trial_days          A_trial_ext: trial_extend на
                                   min(7, trial_days) дней. Без триала - нет.
  ─────────────────────────────────────────────────────────────────────────
  can_pause (можно ли ставить     A_pause: pause_collection 1 месяц
  биллинг на паузу)                (спасение вместо отмены). cost 0.
  ─────────────────────────────────────────────────────────────────────────
  avg_plan_price (автоматически   A_credit: balance_credit = 20% чека,
  из Stripe-планов; вопрос -       округлённый до $, потолок $25 - «мягкая
  только фолбэк без данных)        компенсация» в дуннинге. Требует потолка
                                   скидки > 0 (это тоже денежная уступка).
  ─────────────────────────────────────────────────────────────────────────
  client_api + callback_url      Включает client_callback-исполнитель
                                   (начисления в продукте клиента). URL
                                   уходит в tenants.json -> executors.

Пересборка идемпотентна: авто-офферы имеют префикс A_ и полностью
заменяются при новом сабмите; ручные (C_) и git-пресетные не трогаются.
"""

from __future__ import annotations

# Схемы исполнителей - ЕДИНЫЙ источник (api/saas.py и ai_compose валидируют
# по ним; num? = необязательное число, enum: - выбор).
EXECUTOR_SCHEMAS = {
    'client_callback': {'command': 'str', 'tokens': 'num?', 'days': 'num?',
                        'expires_days': 'num?', 'feature': 'str?'},
    'stripe_coupon': {'percent_off': 'num', 'duration': 'enum:once,repeating,forever',
                      'duration_in_months': 'num?'},
    'trial_extend': {'days': 'num'},
    'pause_collection': {'months': 'num'},
    'balance_credit': {'amount_usd': 'num'},
}


def validate_offer(offer: dict) -> tuple[dict, str]:
    """Валидация ЛЮБОГО оффера (ручного или от LLM) по схеме исполнителя.
    Возвращает (чистый оффер, '') либо ({}, reason)."""
    title = str(offer.get('title', '')).strip()[:120]
    if not title:
        return {}, 'invalid_title'
    executor = str(offer.get('executor', ''))
    schema = EXECUTOR_SCHEMAS.get(executor)
    if schema is None:
        return {}, 'unknown_executor'
    params_in = offer.get('params') or {}
    params = {}
    for key, kind in schema.items():
        optional = kind.endswith('?')
        k = kind.rstrip('?')
        val = params_in.get(key)
        if val in (None, ''):
            if optional:
                continue
            return {}, f'param_required:{key}'
        if k == 'num':
            try:
                num = float(val)
            except (TypeError, ValueError):
                return {}, f'invalid_param:{key}'
            if not 0 <= num <= 1_000_000:
                return {}, f'invalid_param:{key}'
            params[key] = int(num) if float(num).is_integer() else num
        elif k.startswith('enum:'):
            if str(val) not in k.split(':', 1)[1].split(','):
                return {}, f'invalid_param:{key}'
            params[key] = str(val)
        else:
            params[key] = str(val).strip()[:120]
    extra = set(params_in) - set(schema)
    if extra:
        return {}, f'unknown_param:{sorted(extra)[0]}'
    try:
        cap = int(offer.get('max_per_user_30d', 1))
        cost = float(offer.get('cost_estimate', 0))
    except (TypeError, ValueError):
        return {}, 'invalid_cap'
    if not (0 <= cap <= 100 and 0 <= cost <= 100000):
        return {}, 'invalid_cap'
    return {'offer_id': str(offer.get('offer_id', '')).strip()[:48],
            'title': title, 'executor': executor,
            'monetary': bool(offer.get('monetary', True)),
            'cost_estimate': cost, 'max_per_user_30d': cap,
            'params': params}, ''


QUESTIONS = [
    {"key": "value_unit", "type": "str", "required": False,
     "example": "tokens / credits / exports"},
    {"key": "monthly_units", "type": "num", "required": False, "min": 1},
    {"key": "client_api", "type": "bool", "required": True},
    {"key": "callback_url", "type": "str", "required": False},
    {"key": "has_trial", "type": "bool", "required": True},
    {"key": "trial_days", "type": "num", "required": False, "min": 1, "max": 90},
    {"key": "max_discount_pct", "type": "num", "required": True, "min": 0, "max": 80},
    {"key": "can_pause", "type": "bool", "required": True},
    {"key": "avg_plan_price", "type": "num", "required": False, "min": 1},
]

AUTO_PREFIX = "A_"


def validate_answers(raw: dict) -> tuple[dict, str]:
    """Приведение типов + проверки. Возвращает (answers, '') либо ({}, reason)."""
    out = {}
    for q in QUESTIONS:
        val = raw.get(q["key"])
        if val in (None, ""):
            if q["required"]:
                return {}, f"answer_required:{q['key']}"
            continue
        if q["type"] == "bool":
            out[q["key"]] = bool(val) if isinstance(val, bool) else str(val).lower() in ("1", "true", "yes", "да")
        elif q["type"] == "num":
            try:
                num = float(val)
            except (TypeError, ValueError):
                return {}, f"invalid_answer:{q['key']}"
            if not (q.get("min", 0) <= num <= q.get("max", 1_000_000)):
                return {}, f"invalid_answer:{q['key']}"
            out[q["key"]] = int(num) if num.is_integer() else num
        else:
            out[q["key"]] = str(val).strip()[:200]
    if out.get("client_api") and not out.get("value_unit"):
        # API есть, но юнит не назван - бонус-оффер собрать не из чего
        out["client_api"] = out["client_api"]  # допустимо: просто не будет бонуса
    if out.get("has_trial") and not out.get("trial_days"):
        out["trial_days"] = 14
    return out, ""


def compose_offers(answers: dict, avg_price: float = 0.0) -> list[dict]:
    """Ответы -> список офферов. Чистая функция, правила из докстринга модуля.
    avg_price - средний чек из Stripe-планов (важнее ручного ответа)."""
    price = float(avg_price or answers.get("avg_plan_price") or 0)
    ceiling = float(answers.get("max_discount_pct") or 0)
    unit = str(answers.get("value_unit") or "").strip()
    out: list[dict] = []

    if answers.get("client_api") and unit and answers.get("monthly_units"):
        bonus = max(1, round(float(answers["monthly_units"]) * 0.2))
        unit_cost = (price / float(answers["monthly_units"])) if price else 0.0
        out.append({
            "offer_id": f"{AUTO_PREFIX}bonus_{_slug(unit)}",
            "title": f"+{bonus} bonus {unit} (14d TTL)",
            "executor": "client_callback", "monetary": True,
            "cost_estimate": round(bonus * unit_cost, 2),
            "max_per_user_30d": 2,
            "params": {"command": f"{_slug(unit)}_credit", "tokens": bonus,
                       "expires_days": 14},
        })

    if ceiling > 0:
        pct = int(min(20, ceiling))
        out.append({
            "offer_id": f"{AUTO_PREFIX}discount{pct}",
            "title": f"{pct}% off for 2 months",
            "executor": "stripe_coupon", "monetary": True,
            "cost_estimate": round(price * pct / 100 * 2, 2),
            "max_per_user_30d": 1,
            "params": {"percent_off": pct, "duration": "repeating",
                       "duration_in_months": 2},
        })

    if answers.get("has_trial"):
        days = int(min(7, float(answers.get("trial_days") or 14)))
        out.append({
            "offer_id": f"{AUTO_PREFIX}trial_plus{days}",
            "title": f"Trial extension +{days} days",
            "executor": "trial_extend", "monetary": False,
            "cost_estimate": 0.0, "max_per_user_30d": 1,
            "params": {"days": days},
        })

    if answers.get("can_pause"):
        out.append({
            "offer_id": f"{AUTO_PREFIX}pause_1m",
            "title": "Pause subscription for 1 month",
            "executor": "pause_collection", "monetary": False,
            "cost_estimate": 0.0, "max_per_user_30d": 1,
            "params": {"months": 1},
        })

    if ceiling > 0 and price > 0:
        credit = round(min(25.0, price * 0.2))
        if credit >= 1:
            out.append({
                "offer_id": f"{AUTO_PREFIX}credit_{int(credit)}",
                "title": f"${int(credit)} account credit",
                "executor": "balance_credit", "monetary": True,
                "cost_estimate": float(credit), "max_per_user_30d": 1,
                "params": {"amount_usd": int(credit)},
            })

    return out


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:16] or "units"
