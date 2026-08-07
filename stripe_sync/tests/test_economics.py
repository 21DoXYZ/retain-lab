"""Экономика подарков: цифры считаются, а не выдумываются."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from economics import build, gift_cost, unit_price, verdict  # noqa: E402

HUB_PLANS = [{"name": "Trial", "price_usd": 0, "units_included": 150},
             {"name": "Creator", "price_usd": 39, "units_included": 800},
             {"name": "Pro", "price_usd": 99, "units_included": 2000}]


def test_unit_price_needs_both_numbers():
    assert unit_price(39, 800) == 0.04875
    assert unit_price(39, 0) is None and unit_price(0, 800) is None
    assert unit_price("нет", 800) is None


def test_bonus_cost_is_measured_in_real_money():
    """160 кредитов на тарифе $39/800 стоят ~$7.8 - это и есть цена подарка."""
    u = unit_price(39, 800)
    cost = gift_cost("bonus_units", {"units": 160}, 39, u)
    assert cost == 7.8
    v = verdict(cost, 39)
    assert v["share"] == 0.2 and v["payback_months"] == 0.2 and v["ok"] is True


def test_expensive_gift_is_called_expensive():
    v = verdict(gift_cost("discount", {"percent_off": 50, "months": 3}, 39, None), 39)
    assert v["ok"] is False and "дорого" in v["note"]


def test_trial_extension_costs_nothing_because_nobody_paid():
    assert gift_cost("trial_extension", {"days": 7}, 39, 0.04) == 0.0
    assert verdict(0.0, 39)["ok"] is True


def test_build_picks_the_typical_plan_and_lists_what_is_missing():
    econ = build(HUB_PLANS, {"max_discount_pct": 20, "has_trial": True, "trial_days": 7})
    assert econ["typical_plan"] == "Creator" and econ["monthly_price"] == 39
    assert econ["unit_price"] == 0.04875
    assert econ["levers"]["bonus_units"]["params"]["units"] == 160
    assert econ["levers"]["bonus_units"]["ok"] is True
    assert econ["levers"]["trial_extension"]["cost"] == 0.0
    assert econ["missing"] == []           # всё известно


def test_build_is_honest_when_numbers_are_missing():
    econ = build([], {})
    assert econ["monthly_price"] is None
    assert "цена типового тарифа" in econ["missing"]
    assert "потолок скидки" in econ["missing"]
