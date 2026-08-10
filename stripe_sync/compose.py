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
# client_callback УНИВЕРСАЛЕН: amount + unit - «сколько чего» дарим в валюте
# ЛЮБОГО продукта (tokens/videos/credits/seats...); command выводится сам
# (unit_credit), tokens - легаси-синоним amount у старых офферов.
EXECUTOR_SCHEMAS = {
    'client_callback': {'command': 'str?', 'amount': 'num?', 'unit': 'str?',
                        'tokens': 'num?', 'days': 'num?',
                        'expires_days': 'num?', 'feature': 'str?'},
    'stripe_coupon': {'percent_off': 'num', 'duration': 'enum:once,repeating,forever',
                      'duration_in_months': 'num?'},
    'trial_extend': {'days': 'num'},
    'pause_collection': {'months': 'num'},
    'balance_credit': {'amount_usd': 'num'},
    # спасение через даунгрейд: дешёвый план вместо отмены. Сохраняет часть
    # выручки, которую скидка бы просто сожгла, и не уносит живых денег.
    'stripe_downgrade': {'price_id': 'str'},
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
    if executor == 'client_callback':
        # универсальный подарок: должно быть ЧТО дарить; command выводим сами
        if not any(k in params for k in ('amount', 'tokens', 'days', 'feature')):
            return {}, 'param_required:amount'
        if not params.get('command'):
            params['command'] = f"{_slug(str(params.get('unit') or 'bonus'))}_credit"
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
    {"key": "product_name", "type": "str", "required": True},
    {"key": "product_desc", "type": "str", "required": False},
    {"key": "app_url", "type": "str", "required": False},
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
    # ── Себестоимость. Без неё стоимость подарка считается по ЦЕНЕ, а это
    # разные числа: в продукте с валовой маржой 10% подаренный юнит стоит
    # почти столько же, сколько за него платит клиент.
    {"key": "gross_margin_pct", "type": "num", "required": False, "min": 1, "max": 100,
     "example": "сколько остаётся со $100 выручки после оплаты провайдеров"},
    {"key": "unit_cost_usd", "type": "num", "required": False, "min": 0, "max": 10000,
     "example": "во сколько вам обходится один юнит"},
    {"key": "fixed_monthly_cost", "type": "num", "required": False, "min": 0},
    {"key": "trial_units", "type": "num", "required": False, "min": 0},
    # ── Докупка сверх тарифа: обычно именно там лежит маржа, и скидка на неё
    # не уносит живых денег.
    {"key": "topup_price", "type": "num", "required": False, "min": 1},
    {"key": "topup_units", "type": "num", "required": False, "min": 1},
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
    # Тип экономики не вопрос владельцу - он выведен из сайта. Но он управляет
    # всей арифметикой подарков, поэтому обязан пережить сабмит анкеты.
    try:
        from archetypes import ARCHETYPES
    except ImportError:
        from stripe_sync.archetypes import ARCHETYPES  # type: ignore
    kind = str(raw.get("cost_archetype") or "").strip()
    if kind in ARCHETYPES:
        out["cost_archetype"] = kind
    return out, ""


def dedupe_offers(offers: list) -> list:
    """Один и тот же подарок не должен лежать в каталоге дважды.

    Сборка выдавала «20% на месяц» отдельно для апгрейда и отдельно для
    винбэка - одинаковые по сути, разные по id. В каталоге это выглядит как
    ошибка, а в лимитах считается как два разных подарка. Схлопываем по
    исполнителю и параметрам, роли объединяем.
    """
    out, seen = [], {}
    for offer in offers or []:
        key = (offer.get("executor"),
               tuple(sorted((k, str(v)) for k, v in (offer.get("params") or {}).items())))
        if key in seen:
            kept = seen[key]
            roles = kept.setdefault("roles", [kept.get("role")] if kept.get("role") else [])
            if offer.get("role") and offer["role"] not in roles:
                roles.append(offer["role"])
            continue
        seen[key] = offer
        out.append(offer)
    for offer in out:
        if offer.get("roles") and len(offer["roles"]) > 1:
            offer["role"] = offer["roles"][0]
    return out


def compose_offers(answers: dict, avg_price: float = 0.0) -> list[dict]:
    """Ответы -> список офферов. Чистая функция, правила из докстринга модуля.
    avg_price - средний чек из Stripe-планов (важнее ручного ответа).

    Каждый подарок соразмеряется с МАРЖОЙ, из которой он оплачивается. Пока
    себестоимость неизвестна, поведение прежнее: считаем по цене - но тогда
    экономика помечена basis='price' и владелец видит, что число условное.
    """
    try:                                # борд импортирует пакетом, джобы плоско
        from economics import (affordable_units, gross_margin, safe_discount_pct,
                               topup_discount_pct, topup_pack, unit_cost, unit_price)
    except ImportError:
        from stripe_sync.economics import (affordable_units, gross_margin,  # type: ignore
                                           safe_discount_pct, topup_discount_pct,
                                           topup_pack, unit_cost, unit_price)

    price = float(avg_price or answers.get("avg_plan_price") or 0)
    ceiling = float(answers.get("max_discount_pct") or 0)
    unit = str(answers.get("value_unit") or "").strip()
    units = float(answers.get("monthly_units") or 0)

    u_price = unit_price(price, units)
    u_cost, cost_basis = unit_cost(answers, u_price)
    margin = gross_margin(answers)
    # ...в том числе когда себестоимость ПРЕДПОЛОЖЕНА по типу бизнеса: иначе
    # ограничения на размер подарка и глубину скидки молча не применяются
    if margin is None and cost_basis in ("measured", "stated", "assumed") \
            and u_price and u_cost is not None:
        margin = max(0.0, 1.0 - u_cost / u_price)
    monthly_margin = (price * margin) if (price and margin) else None
    margin_pct = round(margin * 100, 1) if margin else None
    out: list[dict] = []

    if answers.get("client_api") and unit and units:
        # размер подарка задаёт маржа, а не лимит тарифа
        bonus = affordable_units(monthly_margin, u_cost, round(units * 0.2))
        per_unit = u_cost if u_cost is not None else 0.0
        out.append({
            "offer_id": f"{AUTO_PREFIX}bonus_{_slug(unit)}", "role": "activation",
            "title": f"+{bonus} bonus {unit} (14d TTL)",
            "executor": "client_callback", "monetary": True,
            "cost_estimate": round(bonus * per_unit, 2),
            "max_per_user_30d": 2,
            "params": {"command": f"{_slug(unit)}_credit", "amount": bonus,
                       "unit": unit, "expires_days": 14},
        })

    # СКИДКА НА ДОКУПКУ - ПЕРВОЙ. Там, где подписка продана почти по
    # себестоимости, вся маржа лежит в пакетах сверх тарифа: скидка на пакет
    # не уносит живых денег и остаётся прибыльной. Порядок здесь не косметика -
    # к шагу цепочки привязывается ПЕРВЫЙ оффер роли, и это должен быть
    # самый дешёвый рычаг, а не самый привычный.
    pack = topup_pack(answers)
    if pack and answers.get("client_api") and ceiling > 0:
        pack_pct = topup_discount_pct(pack, ceiling)
        if pack_pct >= 5:
            out.append({
                "offer_id": f"{AUTO_PREFIX}topup{pack_pct}", "role": "upgrade",
                "title": f"{pack_pct}% off your next {unit or 'credit'} pack",
                "executor": "client_callback", "monetary": True,
                "cost_estimate": round(pack["price"] * pack_pct / 100, 2),
                "max_per_user_30d": 1,
                "params": {"command": "topup_discount", "amount": pack_pct,
                           "unit": "percent", "expires_days": 14},
            })

    # Скидка на подписку - только пока она не уводит месяц в убыток
    pct = safe_discount_pct(ceiling, margin_pct, want=20) if ceiling > 0 else 0
    if pct > 0:
        out.append({
            "offer_id": f"{AUTO_PREFIX}discount{pct}", "role": "upgrade",
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
            "offer_id": f"{AUTO_PREFIX}trial_plus{days}", "role": "conversion",
            "title": f"Trial extension +{days} days",
            "executor": "trial_extend", "monetary": False,
            "cost_estimate": 0.0, "max_per_user_30d": 1,
            "params": {"days": days},
        })

    if answers.get("can_pause"):
        out.append({
            "offer_id": f"{AUTO_PREFIX}pause_1m", "role": "save",
            "title": "Pause subscription for 1 month",
            "executor": "pause_collection", "monetary": False,
            "cost_estimate": 0.0, "max_per_user_30d": 1,
            "params": {"months": 1},
        })

    # Винбэк-скидка подчиняется ТОЙ ЖЕ гигиене маржи, что и основная: правило,
    # применённое в одном месте и забытое в соседнем - хуже отсутствия правила.
    pct_wb = safe_discount_pct(ceiling, margin_pct, want=30) if ceiling > 0 else 0
    if pct_wb > 0:
        out.append({
            "offer_id": f"{AUTO_PREFIX}winback{pct_wb}", "role": "winback",
            "title": f"{pct_wb}% off your first month back",
            "executor": "stripe_coupon", "monetary": True,
            "cost_estimate": round(price * pct_wb / 100, 2),
            "max_per_user_30d": 1,
            "params": {"percent_off": pct_wb, "duration": "once"},
        })

    if ceiling > 0 and price > 0:
        # Кредит - живые деньги: они уходят и когда человек всё равно ушёл.
        # Потолок - четверть МЕСЯЧНОЙ МАРЖИ, а не месячной цены: на марже 10%
        # «20% от чека» дарит вдвое больше, чем клиент приносит за месяц.
        credit_cap = price * 0.2
        if monthly_margin is not None:
            credit_cap = min(credit_cap, monthly_margin * 0.25)
        credit = int(min(25.0, credit_cap))
        if credit >= 1:
            out.append({
                "offer_id": f"{AUTO_PREFIX}credit_{credit}", "role": "dunning",
                "title": f"${credit} account credit",
                "executor": "balance_credit", "monetary": True,
                "cost_estimate": float(credit), "max_per_user_30d": 1,
                "params": {"amount_usd": credit},
            })

    return out


def compose_campaign_copy(answers: dict) -> dict:
    """Ответы -> тексты шагов K1-K5 под ЛЮБОЙ продукт (нейтральные шаблоны
    с подстановкой имени/юнита/URL). Структура цепочек - каркас платформы,
    здесь только КОПИРАЙТ. Формат: {campaign_id: {step_idx: {subject, body}}}.
    Плейсхолдеры {{card_update_url}}/{{app_url}} остаются живыми - их рендерит
    отправка."""
    # Имя продукта может быть ещё не заполнено: тогда тексты обязаны читаться
    # по-человечески («your account»), а не «your your product account».
    raw_name = str(answers.get("product_name") or "").strip()
    name = raw_name or "the product"
    yours = f"your {raw_name}" if raw_name else "your"
    unit = str(answers.get("value_unit") or "").strip()
    units = f" and your {unit}" if unit else ""
    app = str(answers.get("app_url") or "").strip() or "{{app_url}}"

    # Индексы = позиции шагов в saas_campaigns.json (после inapp-шагов).
    # In-app баннер - единственный канал, достающий людей без почты, поэтому
    # у него свой текст, а не копия письма: три строки, один глагол.
    return {
        "K1_activation": {
            0: {"subject": f"Your first {unit or 'result'} is minutes away",
                "body": "One small step to see it work - takes a few minutes."},
            1: {"subject": "Your first result is minutes away",
                "body": f"Hi! You signed up for {name} but have not tried it yet - "
                        f"the first result takes just a few minutes: {app}"},
            2: {"subject": "A quick way to start",
                "body": f"Most people start with the basics - open {app} and make "
                        "your first one. Reply to this email if anything is unclear."},
        },
        "K2_trial_conversion": {
            0: {"subject": "Your trial ends soon - keep your work",
                "body": "Everything you made stays with you on any paid plan."},
            1: {"subject": "Your trial ends soon - keep your work",
                "body": f"Your trial ends in a few days. Upgrade to keep access{units}: {app}"},
            3: {"subject": "We added extra trial days",
                "body": f"Need more time to decide? Your trial got extended. "
                        f"Meanwhile, try the advanced features: {app}"},
        },
        "K3_payment_recovery": {
            0: {"subject": "Payment issue - action needed",
                "body": "Your last payment did not go through. Update your card - "
                        "it takes 30 seconds, your work is safe."},
            1: {"subject": f"Payment issue - {yours} account is safe",
                "body": "Your last payment did not go through (this is usually a "
                        "card issue, not you). Update your card in 30 seconds: "
                        f"{{{{card_update_url}}}}. Your account{units} "
                        f"{'are' if units else 'is'} safe."},
            2: {"subject": "Reminder: update your card",
                "body": "Quick reminder to update your payment method: "
                        "{{card_update_url}}. We retry automatically once it is updated."},
            3: {"subject": "Last call before your plan pauses",
                "body": "We could not charge your card for 3 days. Update it now "
                        "to keep full access: {{card_update_url}}"},
        },
        "K4_save": {
            0: {"subject": "Need a break? Pause instead of canceling",
                "body": f"Keep your history{units}, pay nothing for a month."},
            1: {"subject": "Need a break? Pause instead of cancel",
                "body": f"You can pause your subscription for a month - keep your "
                        f"history{units}, pay nothing: {app}"},
            3: {"subject": f"What is new in {name}",
                "body": f"Here is what changed since you last visited: {app}"},
        },
        "K6_winback": {
            0: {"subject": f"A lot changed in {name} since you left",
                "body": f"Here is what is new since you canceled - worth a "
                        f"fresh look: {app}"},
            3: {"subject": "Your account is still here",
                "body": f"Your history{units} {'are' if units else 'is'} saved. "
                        f"Come back anytime: {app}"},
        },
        "K5_upgrade": {
            0: {"subject": "You are close to your plan limit",
                "body": f"On the next tier each {unit or 'unit'} costs less - "
                        "worth a look this month."},
            1: {"subject": "You are hitting your plan limit",
                "body": f"You used most of your plan this month. On the higher tier "
                        f"the unit economics are better: {app}"},
            3: {"subject": "Lock in a discount on annual",
                "body": f"Heavy months like this one are cheaper on annual - "
                        f"see the numbers: {app}"},
        },
    }


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:16] or "units"
