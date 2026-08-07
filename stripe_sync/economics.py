"""Экономика подарков: во что удержание обходится и когда оно окупается.

ЗАЧЕМ. «Дадим 20% скидки» - это не решение, пока не сказано, во сколько оно
обходится и за сколько месяцев возвращается. Без этого предложения системы
остаются вкусовщиной, а владелец не может их сравнить.

ГЛАВНОЕ РАЗЛИЧЕНИЕ: ЦЕНА - НЕ СЕБЕСТОИМОСТЬ.
Первая версия этого модуля считала стоимость подарка по ЦЕНЕ юнита
(цена тарифа / включённый лимит) и окупаемость по ВЫРУЧКЕ (стоимость / чек).
На разборе реальной юнит-экономики клиента (видео-генерация, подписка продана
почти по себестоимости) обе цифры оказались неверны в разы:

  подарок 3000 кредитов на тарифе $99 / 15000 кредитов
  было:  цена юнита $0.0066 -> «стоит $19.80, окупается за 0.2 месяца, ок»
  стало: себестоимость $0.0059 -> $17.75 ЖИВЫХ денег провайдерам,
         а маржа тарифа всего $10.26/мес -> окупаемость 1.73 месяца

Ошибка в 8.6 раза - и в опасную сторону. Поэтому здесь два разных числа:

  cash    - деньги, которые УЙДУТ со счёта (себестоимость подаренных юнитов,
            денежный кредит на баланс). Их платят до того, как человек
            останется, и их не вернуть, если он всё равно уйдёт.
  revenue - деньги, которые НЕ ПРИДУТ (скидка, пауза). Из кармана ничего не
            уходит, риск меньше.

Окупаемость считается в месяцах МАРЖИ, а не выручки: тариф за $99 с валовой
маржой 10% приносит $10.26 в месяц, а не $99.

ЧИСТАЯ АРИФМЕТИКА, БЕЗ ДОГАДОК. Считаем только из того, что знаем: цены
тарифов (из биллинга или со страницы цен), включённые лимиты, ответы
владельца. Нет числа - не выдумываем: возвращаем None, помечаем basis='price'
и говорим, чего не хватает.

СЛОВАРЬ:
  цена юнита      - месячная цена тарифа / включённый лимит (что платит клиент);
  себестоимость   - что платим провайдерам за тот же юнит (что тратим мы);
  валовая маржа   - доля выручки, остающаяся после прямых расходов;
  маржа в месяц   - цена тарифа x валовая маржа: из чего реально окупается подарок;
  доля от чека    - подарок в процентах от месячного платежа (гигиена: больше
                    четверти чека - это уже не удержание, а раздача).
"""

from __future__ import annotations

SAFE_GIFT_SHARE = 0.25      # выше этого подарок съедает смысл удержания
MAX_PAYBACK_MONTHS = 3.0    # дольше - деньги замораживаются слишком надолго
THIN_MARGIN = 0.30          # ниже этого дарить себестоимость опасно


def unit_price(plan_price: float, units: float) -> float | None:
    """Во сколько обходится один юнит ценности КЛИЕНТУ на этом тарифе."""
    try:
        price, count = float(plan_price), float(units)
    except (TypeError, ValueError):
        return None
    if price <= 0 or count <= 0:
        return None
    return round(price / count, 6)


def unit_cost(answers: dict, price_per_unit: float | None) -> tuple[float | None, str]:
    """Себестоимость одного юнита и то, ОТКУДА мы её взяли.

    Четыре источника по убыванию точности:
      'stated'  - владелец назвал прямые расходы на юнит;
      'margin'  - вывели из валовой маржи: цена юнита x (1 - маржа);
      'assumed' - взяли коридор маржи по типу бизнеса с сайта (предположение,
                  живёт до первого ответа владельца);
      'price'   - не знаем ничего: остаётся цена, и об этом надо сказать вслух.

    Разница между 'assumed' и 'price' принципиальна: подставить цену вместо
    себестоимости - это молчаливое допущение «маржа ноль». Для обычного софта
    оно завышает стоимость подарка в разы, и система начинает отказываться от
    нормальных офферов, не сказав почему.
    """
    stated = answers.get("unit_cost_usd")
    if stated not in (None, ""):
        try:
            value = float(stated)
        except (TypeError, ValueError):
            value = -1.0
        if value >= 0:
            return round(value, 6), "stated"
    margin = gross_margin(answers)
    if margin is not None and price_per_unit:
        return round(price_per_unit * (1.0 - margin), 6), "margin"
    kind = str(answers.get("cost_archetype") or "").strip()
    if kind and price_per_unit:
        try:                            # борд импортирует пакетом, джобы плоско
            from archetypes import ARCHETYPES, assumed_margin
        except ImportError:
            from stripe_sync.archetypes import ARCHETYPES, assumed_margin  # type: ignore
        if kind in ARCHETYPES:
            return round(price_per_unit * (1.0 - assumed_margin(kind)), 6), "assumed"
    return (price_per_unit, "price") if price_per_unit else (None, "price")


def gross_margin(answers: dict) -> float | None:
    """Валовая маржа долей единицы. Нет ответа - None, не подставляем 100%."""
    raw = answers.get("gross_margin_pct")
    if raw in (None, ""):
        return None
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return None
    if not 0 < pct <= 100:
        return None
    return round(pct / 100.0, 4)


def gift_cost(kind: str, params: dict, plan_price: float,
              cost_per_unit: float | None,
              topup: dict | None = None,
              monthly_margin: float | None = None) -> dict:
    """Во что обходится ОДНА выдача: живыми деньгами и недополученной выручкой.

    Возвращает {'cash': x|None, 'revenue': y|None}. None - «не знаем», это НЕ
    ноль: молчаливый ноль превращает дорогой подарок в бесплатный.

    ТОНКОСТЬ, КОТОРУЮ ЛЕГКО ПРОПУСТИТЬ. Скидка и пауза выглядят одинаково
    («человек заплатил меньше»), но стоят разного. При скидке услуга ОКАЗАНА:
    расходы вы понесли полностью, потеряна вся сумма скидки. При паузе услуга
    НЕ оказана: вы не собрали выручку, но и не потратились на обслуживание -
    потеряна только маржа этого периода. На тарифе $99 с маржой 10% это
    разница между $99 и $10.26, то есть в десять раз.
    """
    price = float(plan_price or 0)

    if kind == "bonus_units":
        # ЖИВЫЕ ДЕНЬГИ: подаренные юниты кто-то должен произвести
        if cost_per_unit is None:
            return {"cash": None, "revenue": None}
        return {"cash": round(float(params.get("units") or 0) * cost_per_unit, 2),
                "revenue": 0.0}

    if kind == "discount":
        pct = float(params.get("percent_off") or 0) / 100.0
        months = float(params.get("months") or 1)
        return {"cash": 0.0,
                "revenue": round(price * pct * months, 2) if price else None}

    if kind == "topup_discount":
        # Скидка на пакет ДОКУПКИ: денег не уходит, режется только маржа пакета
        pack = float((topup or {}).get("price") or 0)
        pct = float(params.get("percent_off") or 0) / 100.0
        return {"cash": 0.0, "revenue": round(pack * pct, 2) if pack else None}

    if kind == "credit":
        # Деньги на баланс - прямой расход, никакой «условности»
        return {"cash": round(float(params.get("amount_usd") or 0), 2),
                "revenue": 0.0}

    if kind == "trial_extension":
        # НЕ БЕСПЛАТНО. Выручки действительно не теряем - человек ещё не платил.
        # Но продлённый триал ПОТРЕБЛЯЕТ: в продукте с реальной себестоимостью
        # каждый лишний день триала оплачивается провайдерам живыми деньгами.
        units = float(params.get("trial_units") or 0)
        if units and cost_per_unit is not None:
            return {"cash": round(units * cost_per_unit, 2), "revenue": 0.0}
        return {"cash": 0.0 if cost_per_unit is not None else None, "revenue": 0.0}

    if kind == "pause":
        # Пауза - ОТЛОЖЕННАЯ, а не потерянная выручка, и живых денег не уносит.
        # На паузе мы не обслуживаем человека, значит не платим за него
        # провайдерам: теряется маржа периода, а не его цена.
        months = float(params.get("months") or 1)
        if monthly_margin is not None:
            return {"cash": 0.0, "revenue": round(monthly_margin * months, 2)}
        return {"cash": 0.0,
                "revenue": round(price * months, 2) if price else None}

    return {"cash": None, "revenue": None}


def payback_months(total: float | None, monthly_margin: float | None) -> float | None:
    """За сколько месяцев МАРЖИ подарок возвращается (не месяцев выручки)."""
    if total is None or not monthly_margin:
        return None
    if total <= 0:
        return 0.0
    return round(float(total) / float(monthly_margin), 2)


def verdict(cost: float | None, plan_price: float,
            margin: float | None = None, cash: float | None = None) -> dict:
    """Оценка подарка: сколько стоит, из чего окупается и человеческий вывод.

    cost   - полная величина уступки (живые деньги + недополученная выручка);
    margin - валовая маржа долей единицы; None - не знаем, считаем по выручке
             и честно помечаем basis='price';
    cash   - какая часть уступки уходит ЖИВЫМИ деньгами.
    """
    if cost is None or not plan_price:
        return {"cost": None, "cash": cash, "share": None, "payback_months": None,
                "monthly_margin": None, "basis": "price", "ok": None,
                "note": "не хватает цены тарифа или лимита юнитов"}

    price = float(plan_price)
    basis = "margin" if margin else "price"
    monthly_margin = round(price * margin, 2) if margin else price
    share = round(float(cost) / price, 3)
    back = payback_months(cost, monthly_margin)
    ok = share <= SAFE_GIFT_SHARE and (back or 0) <= MAX_PAYBACK_MONTHS

    if cost == 0:
        note = "ничего не стоит: человек ещё не платил"
    elif ok:
        note = (f"{int(share * 100)}% месячного платежа, "
                f"окупается за {back} мес. маржи")
    else:
        note = (f"дорого: {int(share * 100)}% месячного платежа, "
                f"возврат {back} мес. маржи")
    # Живые деньги дороже недополученной выручки: их платят вперёд и не
    # возвращают, если человек всё равно ушёл. Об этом говорим отдельно.
    if cash and margin and cash > monthly_margin:
        ok = False
        note = (f"уносит ${cash:.2f} живыми деньгами при марже "
                f"${monthly_margin:.2f} в месяц - выдача дороже, чем месяц клиента")

    return {"cost": round(float(cost), 2), "cash": None if cash is None else round(cash, 2),
            "share": share, "payback_months": back,
            "monthly_margin": monthly_margin, "basis": basis,
            "ok": ok, "note": note}


def _verdict_for(kind: str, params: dict, price: float, u_cost: float | None,
                 margin: float | None, topup: dict | None = None) -> dict:
    """Стоимость рычага -> вердикт. Общий путь для всех рычагов."""
    monthly_margin = (price * margin) if (price and margin) else None
    money = gift_cost(kind, params, price, u_cost, topup, monthly_margin)
    cash, rev = money["cash"], money["revenue"]
    total = None if cash is None and rev is None else (cash or 0) + (rev or 0)
    out = verdict(total, price, margin, cash)
    out["cash"] = None if cash is None else round(cash, 2)
    out["revenue"] = None if rev is None else round(rev, 2)
    return out


def build(plans: list, answers: dict) -> dict:
    """Экономическая карта клиента: цены, себестоимость и стоимость рычагов.

    plans   - [{name, price_usd, units_included}] из биллинга или со страницы цен;
    answers - ответы владельца (лимит типового тарифа, потолок скидки, маржа).
    """
    paid = sorted([p for p in (plans or []) if float(p.get("price_usd") or 0) > 0],
                  key=lambda p: float(p["price_usd"]))
    typical = paid[len(paid) // 2] if len(paid) >= 3 else (paid[0] if paid else {})
    price = float(typical.get("price_usd") or answers.get("avg_plan_price") or 0)
    units = float(typical.get("units_included") or answers.get("monthly_units") or 0)
    u_price = unit_price(price, units)
    u_cost, cost_basis = unit_cost(answers, u_price)
    margin = gross_margin(answers)
    # Себестоимость назвали (или предположили по типу бизнеса), а маржу нет -
    # выводим маржу из неё самой
    if margin is None and cost_basis in ("stated", "assumed") \
            and u_price and u_cost is not None:
        margin = round(max(0.0, 1.0 - u_cost / u_price), 4)

    monthly_margin = round(price * margin, 2) if (price and margin) else None

    ladder = []
    for p in paid:
        p_price = float(p["price_usd"])
        p_units = p.get("units_included") or 0
        p_unit_price = unit_price(p_price, p_units)
        ladder.append({
            "name": p.get("name") or "",
            "price_usd": p_price,
            "units_included": p_units,
            "unit_price": p_unit_price,
            # маржа считается ПО КАЖДОМУ тарифу: в usage-продукте старший тариф
            # часто зарабатывает меньше младшего, и дарить на нём опаснее
            "unit_cost": u_cost,
            "margin_pct": (round(100 * (1 - u_cost * p_units / p_price), 1)
                           if u_cost is not None and p_units and p_price else None),
        })

    topup = topup_pack(answers)
    ceiling = float(answers.get("max_discount_pct") or 0)
    levers = {}
    if u_cost is not None and units:
        bonus = max(1, round(units * 0.2))
        levers["bonus_units"] = {"params": {"units": bonus},
                                 **_verdict_for("bonus_units", {"units": bonus},
                                                price, u_cost, margin)}
    if ceiling > 0:
        pct = min(20.0, ceiling)
        levers["discount"] = {"params": {"percent_off": pct, "months": 2},
                              **_verdict_for("discount", {"percent_off": pct, "months": 2},
                                             price, u_cost, margin)}
    if topup and ceiling > 0:
        pct = topup_discount_pct(topup, ceiling)
        if pct > 0:
            levers["topup_discount"] = {
                "params": {"percent_off": pct},
                **_verdict_for("topup_discount", {"percent_off": pct},
                               price, u_cost, margin, topup)}
    if answers.get("has_trial"):
        days = min(7, int(answers.get("trial_days") or 7))
        trial_units = float(answers.get("trial_units") or 0)
        # сколько юнитов съест ПРОДЛЕНИЕ, а не весь триал
        share = (days / float(answers.get("trial_days") or days)) if answers.get("trial_days") else 1.0
        levers["trial_extension"] = {
            "params": {"days": days},
            **_verdict_for("trial_extension",
                           {"trial_units": round(trial_units * share)},
                           price, u_cost, margin)}
    if answers.get("can_pause"):
        levers["pause"] = {"params": {"months": 1},
                           **_verdict_for("pause", {"months": 1}, price, u_cost, margin)}

    # Откуда взялась себестоимость - видно в КАЖДОМ вердикте, а не только в
    # сводке: иначе предположение по типу бизнеса читается как измеренный факт.
    for lever in levers.values():
        lever["basis"] = cost_basis

    missing = []
    if not price:
        missing.append("цена типового тарифа")
    if not units:
        missing.append("сколько юнитов включено в тариф")
    if ceiling <= 0:
        missing.append("потолок скидки")
    if cost_basis in ("price", "assumed"):
        # без этого числа стоимость подарка остаётся догадкой
        missing.append("валовая маржа или себестоимость юнита")

    return {
        "typical_plan": typical.get("name") or "",
        "monthly_price": round(price, 2) if price else None,
        "included_units": int(units) if units else None,
        "unit_price": u_price,
        "unit_cost": u_cost,
        "cost_basis": cost_basis,
        "cost_archetype": str(answers.get("cost_archetype") or "") or None,
        "gross_margin": margin,
        "monthly_margin": monthly_margin,
        "thin_margin": bool(margin is not None and margin < THIN_MARGIN),
        "fixed_monthly_cost": _num(answers.get("fixed_monthly_cost")),
        "breakeven_customers": _breakeven(answers, monthly_margin),
        "topup": topup,
        "ladder": ladder,
        "levers": levers,
        "missing": missing,
    }


def _num(raw) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def topup_pack(answers: dict) -> dict | None:
    """Пакет докупки сверх тарифа - если он есть, там и лежит маржа.

    В продукте, где подписка продана почти по себестоимости, докупка обычно
    продаётся с нормальной наценкой. Скидка на неё не уносит живых денег и
    остаётся прибыльной - это самый дешёвый рычаг из существующих.
    """
    price = _num(answers.get("topup_price"))
    units = _num(answers.get("topup_units"))
    if not price or not units:
        return None
    cost_per_unit, _ = unit_cost(answers, None)
    pack_cost = round(cost_per_unit * units, 2) if cost_per_unit is not None else None
    margin_pct = (round(100 * (price - pack_cost) / price, 1)
                  if pack_cost is not None and price else None)
    return {"price": round(price, 2), "units": int(units),
            "cost": pack_cost, "margin_pct": margin_pct}


def safe_discount_pct(ceiling: float, margin_pct: float | None = None,
                      want: float = 20.0) -> int:
    """Скидка на ПОДПИСКУ, которая не продаёт её ниже себестоимости.

    Скидка режет выручку, а расходы остаются: при валовой марже 10% скидка в
    20% означает, что каждый удержанный месяц клиента приносит убыток. Больше
    половины маржи не отдаём никогда, сколько бы владелец ни разрешил.
    """
    limit = min(float(want), float(ceiling))
    if margin_pct is not None:
        limit = min(limit, float(margin_pct) / 2.0)
    return int(max(0, limit))


def affordable_units(monthly_margin: float | None, cost_per_unit: float | None,
                     wanted: float) -> int:
    """Сколько юнитов можно подарить, не проедая месяц клиента.

    Размер подарка задаётся МАРЖОЙ, из которой он оплачивается, а не лимитом
    тарифа. «20% от лимита» в продукте с тонкой маржой - это подарок дороже
    самого клиента.
    """
    size = max(1, int(wanted))
    if monthly_margin and cost_per_unit:
        afford = int((monthly_margin * SAFE_GIFT_SHARE) / cost_per_unit)
        size = max(1, min(size, afford))
    return size


def topup_discount_pct(topup: dict, ceiling: float) -> int:
    """Безопасная скидка на пакет докупки.

    Не больше половины маржи пакета: иначе скидка съедает смысл продажи, а на
    глубине больше маржи пакет уходит ниже себестоимости. И не больше того
    потолка, который назвал владелец.
    """
    margin_pct = topup.get("margin_pct")
    limit = (margin_pct / 2.0) if margin_pct else ceiling
    return int(max(0, min(ceiling, limit)))


def _breakeven(answers: dict, monthly_margin: float | None) -> int | None:
    """Сколько платящих нужно, чтобы покрыть постоянные расходы.

    Число, которое меняет отношение к подаркам: пока клиентов меньше этого,
    каждый доллар подарка - это доллар из кармана владельца, а не из прибыли.
    """
    fixed = _num(answers.get("fixed_monthly_cost"))
    if not fixed or not monthly_margin:
        return None
    return int(-(-fixed // monthly_margin))
