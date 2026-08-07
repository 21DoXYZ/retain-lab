"""Экономика подарков: сколько стоит удержание и когда оно окупается.

ЗАЧЕМ. «Дадим 20% скидки» - это не решение, пока не сказано, во сколько оно
обходится и за сколько месяцев возвращается. Без этого предложения системы
остаются вкусовщиной, а владелец не может их сравнить.

ЧИСТАЯ АРИФМЕТИКА, БЕЗ ДОГАДОК. Считаем только из того, что знаем: цены
тарифов (из биллинга или со страницы цен), включённые лимиты, ответы владельца.
Нет числа - не выдумываем, возвращаем None и говорим, чего не хватает.

СЛОВАРЬ:
  цена юнита      - месячная цена тарифа / включённый лимит;
  стоимость подарка - сколько выручки мы отдаём (для бонуса - по цене юнита,
                    для скидки - прямая недополученная сумма);
  окупаемость     - за сколько месяцев подписки подарок возвращается;
  доля от чека    - подарок в процентах от месячного платежа (гигиена: больше
                    четверти чека - это уже не удержание, а раздача).
"""

from __future__ import annotations

SAFE_GIFT_SHARE = 0.25      # выше этого подарок съедает смысл удержания
MAX_PAYBACK_MONTHS = 3.0    # дольше - деньги замораживаются слишком надолго


def unit_price(plan_price: float, units: float) -> float | None:
    """Во сколько обходится один юнит ценности на этом тарифе."""
    try:
        price, count = float(plan_price), float(units)
    except (TypeError, ValueError):
        return None
    if price <= 0 or count <= 0:
        return None
    return round(price / count, 6)


def gift_cost(kind: str, params: dict, plan_price: float,
              unit_cost: float | None) -> float | None:
    """Во что обходится ОДНА выдача подарка, в деньгах месячного тарифа."""
    price = float(plan_price or 0)
    if kind == "bonus_units":
        if unit_cost is None:
            return None
        return round(float(params.get("units") or 0) * unit_cost, 2)
    if kind == "discount":
        pct = float(params.get("percent_off") or 0) / 100.0
        months = float(params.get("months") or 1)
        return round(price * pct * months, 2) if price else None
    if kind == "credit":
        return round(float(params.get("amount_usd") or 0), 2)
    if kind == "trial_extension":
        # продление триала не стоит выручки: человек ещё не платил
        return 0.0
    if kind == "pause":
        # пауза - отложенная, а не потерянная выручка: считаем один месяц
        return round(price, 2) if price else None
    return None


def payback_months(cost: float | None, plan_price: float) -> float | None:
    """За сколько месяцев подписки подарок возвращается."""
    if cost is None or not plan_price:
        return None
    if cost <= 0:
        return 0.0
    return round(float(cost) / float(plan_price), 2)


def verdict(cost: float | None, plan_price: float) -> dict:
    """Оценка подарка: доля от чека, окупаемость и человеческий вывод."""
    if cost is None or not plan_price:
        return {"cost": None, "share": None, "payback_months": None,
                "ok": None, "note": "не хватает цены тарифа или лимита юнитов"}
    share = round(float(cost) / float(plan_price), 3)
    back = payback_months(cost, plan_price)
    ok = share <= SAFE_GIFT_SHARE and (back or 0) <= MAX_PAYBACK_MONTHS
    if cost == 0:
        note = "ничего не стоит: человек ещё не платил"
    elif ok:
        note = (f"{int(share * 100)}% месячного платежа, "
                f"окупается за {back} мес. подписки")
    else:
        note = (f"дорого: {int(share * 100)}% месячного платежа, "
                f"возврат {back} мес.")
    return {"cost": round(float(cost), 2), "share": share,
            "payback_months": back, "ok": ok, "note": note}


def build(plans: list, answers: dict) -> dict:
    """Экономическая карта клиента: цены юнитов по тарифам и стоимость рычагов.

    plans   - [{name, price_usd, units_included}] из биллинга или со страницы цен;
    answers - ответы владельца (лимит типового тарифа, потолок скидки).
    """
    paid = sorted([p for p in (plans or []) if float(p.get("price_usd") or 0) > 0],
                  key=lambda p: float(p["price_usd"]))
    typical = paid[len(paid) // 2] if len(paid) >= 3 else (paid[0] if paid else {})
    price = float(typical.get("price_usd") or answers.get("avg_plan_price") or 0)
    units = float(typical.get("units_included") or answers.get("monthly_units") or 0)
    u_cost = unit_price(price, units)

    ladder = []
    for p in paid:
        ladder.append({
            "name": p.get("name") or "",
            "price_usd": float(p["price_usd"]),
            "units_included": p.get("units_included"),
            "unit_price": unit_price(p["price_usd"], p.get("units_included") or 0),
        })

    ceiling = float(answers.get("max_discount_pct") or 0)
    levers = {}
    if u_cost is not None:
        bonus_units = max(1, round(units * 0.2))
        levers["bonus_units"] = {
            "params": {"units": bonus_units},
            **verdict(gift_cost("bonus_units", {"units": bonus_units}, price, u_cost), price),
        }
    if ceiling > 0:
        pct = min(20.0, ceiling)
        levers["discount"] = {
            "params": {"percent_off": pct, "months": 2},
            **verdict(gift_cost("discount", {"percent_off": pct, "months": 2}, price, u_cost), price),
        }
    if answers.get("has_trial"):
        levers["trial_extension"] = {
            "params": {"days": min(7, int(answers.get("trial_days") or 7))},
            **verdict(0.0, price),
        }
    if answers.get("can_pause"):
        levers["pause"] = {"params": {"months": 1},
                           **verdict(gift_cost("pause", {}, price, u_cost), price)}

    missing = []
    if not price:
        missing.append("цена типового тарифа")
    if not units:
        missing.append("сколько юнитов включено в тариф")
    if ceiling <= 0:
        missing.append("потолок скидки")

    return {
        "typical_plan": typical.get("name") or "",
        "monthly_price": round(price, 2) if price else None,
        "included_units": int(units) if units else None,
        "unit_price": u_cost,
        "ladder": ladder,
        "levers": levers,
        "missing": missing,
    }
