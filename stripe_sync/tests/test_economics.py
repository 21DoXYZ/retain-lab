"""Экономика подарков: цифры считаются, а не выдумываются.

Опорный случай - реальная юнит-экономика клиента с видео-генерацией: подписка
продана почти по себестоимости, вся маржа лежит в докупке пакетов. На таком
клиенте прежняя методика (стоимость по цене, окупаемость по выручке) ошибалась
в 8.6 раза в опасную сторону, поэтому он зафиксирован тестом.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from economics import (build, gift_cost, topup_discount_pct, unit_cost,  # noqa: E402
                       unit_price, verdict)

HUB_PLANS = [{"name": "Trial", "price_usd": 0, "units_included": 1000},
             {"name": "Creator", "price_usd": 39, "units_included": 6000},
             {"name": "Pro", "price_usd": 99, "units_included": 15000},
             {"name": "Studio", "price_usd": 399, "units_included": 65000}]
# $2.958 за генерацию / 500 кредитов = себестоимость одного кредита
HUB_ANSWERS = {"unit_cost_usd": 0.005916, "max_discount_pct": 20,
               "has_trial": True, "trial_days": 14, "trial_units": 1000,
               "topup_price": 94.66, "topup_units": 10000,
               "fixed_monthly_cost": 1400}


def test_unit_price_needs_both_numbers():
    assert unit_price(39, 800) == 0.04875
    assert unit_price(39, 0) is None and unit_price(0, 800) is None
    assert unit_price("нет", 800) is None


def test_unit_cost_says_where_the_number_came_from():
    assert unit_cost({"unit_cost_usd": 0.006}, 0.0066) == (0.006, "stated")
    assert unit_cost({"gross_margin_pct": 80}, 0.05) == (0.01, "margin")
    # ничего не назвали - остаётся цена, и это помечено честно
    assert unit_cost({}, 0.05) == (0.05, "price")
    assert unit_cost({}, None) == (None, "price")


def test_bonus_units_cost_live_money_not_foregone_revenue():
    """Подаренные юниты кто-то производит: это списание, а не недополучение."""
    money = gift_cost("bonus_units", {"units": 3000}, 99, 0.005916)
    assert money == {"cash": 17.75, "revenue": 0.0}


def test_discount_costs_revenue_but_no_cash():
    money = gift_cost("discount", {"percent_off": 20, "months": 2}, 99, 0.005916)
    assert money == {"cash": 0.0, "revenue": 39.6}


def test_unknown_unit_cost_is_none_not_zero():
    """Молчаливый ноль превращает дорогой подарок в бесплатный - так нельзя."""
    assert gift_cost("bonus_units", {"units": 3000}, 99, None)["cash"] is None


def test_payback_is_counted_in_months_of_margin():
    """Тариф $99 с валовой маржой 10% приносит $10.26 в месяц, а не $99."""
    v = verdict(17.75, 99, margin=0.1036, cash=17.75)
    assert v["monthly_margin"] == 10.26
    assert v["payback_months"] == 1.73
    assert v["basis"] == "margin"
    # без маржи считаем по выручке, но обязаны в этом признаться
    assert verdict(17.75, 99)["basis"] == "price"
    assert verdict(17.75, 99)["payback_months"] == 0.18


def test_gift_bigger_than_a_month_of_margin_is_rejected():
    v = verdict(35.0, 99, margin=0.1036, cash=35.0)
    assert v["ok"] is False and "живыми деньгами" in v["note"]


def test_expensive_gift_is_called_expensive():
    money = gift_cost("discount", {"percent_off": 50, "months": 3}, 39, None)
    assert verdict(money["revenue"], 39)["ok"] is False


def test_trial_extension_is_not_free_in_a_usage_product():
    """Выручки не теряем, но провайдерам за продлённый триал платим живыми."""
    money = gift_cost("trial_extension", {"trial_units": 500}, 39, 0.005916)
    assert money["cash"] == 2.96 and money["revenue"] == 0.0
    # там, где потребления нет, продление действительно ничего не стоит
    assert gift_cost("trial_extension", {}, 39, 0.005916)["cash"] == 0.0


def test_pause_never_takes_cash_out():
    money = gift_cost("pause", {"months": 1}, 99, 0.005916)
    assert money["cash"] == 0.0 and money["revenue"] == 99.0


def test_a_pause_costs_margin_while_a_discount_costs_the_whole_amount():
    """Выглядят одинаково («заплатил меньше»), стоят разного.

    При скидке услуга ОКАЗАНА: расходы понесены, потеряна вся сумма скидки.
    При паузе услуга НЕ оказана: не собрали выручку, но и не потратились -
    потеряна только маржа периода. На $99 с маржой 10% это $99 против $10.26.
    """
    paused = gift_cost("pause", {"months": 1}, 99, 0.005916, monthly_margin=10.26)
    assert paused["revenue"] == 10.26
    discounted = gift_cost("discount", {"percent_off": 100, "months": 1}, 99, None)
    assert discounted["revenue"] == 99.0
    # в собранной карте рычагов пауза считается уже по марже
    econ = build(HUB_PLANS, {**HUB_ANSWERS, "can_pause": True})
    assert econ["levers"]["pause"]["revenue"] == 10.26


def test_topup_discount_stays_above_cost():
    """Скидка на пакет режет маржу пакета, но не уводит его ниже себестоимости."""
    econ = build(HUB_PLANS, HUB_ANSWERS)
    pack = econ["topup"]
    assert pack["cost"] == 59.16 and pack["margin_pct"] == 37.5
    pct = topup_discount_pct(pack, 20)
    assert pct == 18                       # половина маржи, но не выше потолка
    lever = econ["levers"]["topup_discount"]
    assert lever["cash"] == 0.0 and lever["revenue"] == 17.04


def test_thin_margin_client_is_flagged():
    econ = build(HUB_PLANS, HUB_ANSWERS)
    assert econ["typical_plan"] == "Pro" and econ["monthly_price"] == 99
    assert econ["unit_cost"] == 0.005916 and econ["cost_basis"] == "stated"
    assert econ["gross_margin"] == 0.1036          # выведена из себестоимости
    assert econ["monthly_margin"] == 10.26
    assert econ["thin_margin"] is True
    assert econ["breakeven_customers"] == 137      # $1400 постоянных / $10.26


def test_per_plan_margin_shows_the_top_tier_earns_least():
    """В usage-продукте старший тариф часто зарабатывает меньше младшего."""
    ladder = {p["name"]: p["margin_pct"] for p in build(HUB_PLANS, HUB_ANSWERS)["ladder"]}
    assert ladder["Creator"] == 9.0 and ladder["Studio"] == 3.6


def test_the_expensive_gift_loses_to_the_cheap_one():
    """Главный вывод методики: дарить себестоимость дороже, чем резать маржу."""
    levers = build(HUB_PLANS, HUB_ANSWERS)["levers"]
    assert levers["bonus_units"]["cash"] == 17.75
    assert levers["bonus_units"]["ok"] is False    # дороже месяца маржи
    assert levers["topup_discount"]["cash"] == 0.0
    assert levers["topup_discount"]["ok"] is True


def test_build_is_honest_when_numbers_are_missing():
    econ = build([], {})
    assert econ["monthly_price"] is None
    assert "цена типового тарифа" in econ["missing"]
    assert "потолок скидки" in econ["missing"]
    assert "валовая маржа или себестоимость юнита" in econ["missing"]
    assert econ["thin_margin"] is False            # не знаем - не обвиняем
