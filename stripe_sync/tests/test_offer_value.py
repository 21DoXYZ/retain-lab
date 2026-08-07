"""Универсальная логика офферов: сделка, а не список подарков.

Проверяем не «собрался ли каталог», а экономическое поведение: дешёвое раньше
дорогого, живые деньги дороже скидки, приз считается в марже, бюджет
масштабируется вместе с клиентом, и «не давать ничего» - допустимый ответ.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offer_value import (TIER_CASH, TIER_DEFER, TIER_OTHER_MARGIN,  # noqa: E402
                         TIER_OWN_REVENUE, choose, expected_value, gift_budget,
                         margin_at_stake, rank, tier_of, uplift_or_prior)

# пауза на тарифе $99 с маржой 10%: услуга не оказана, потеряна МАРЖА месяца,
# а не его цена - $10.26, а не $99
PAUSE = {"offer_id": "pause", "executor": "pause_collection", "cash": 0.0,
         "revenue": 10.26, "uplift": 0.12}
DISCOUNT = {"offer_id": "disc", "executor": "stripe_coupon", "cash": 0.0,
            "revenue": 19.8, "uplift": 0.06}
TOPUP = {"offer_id": "topup", "executor": "client_callback", "cash": 0.0,
         "revenue": 17.04, "uplift": 0.06,
         "params": {"command": "topup_discount"}}
BONUS = {"offer_id": "bonus", "executor": "client_callback", "cash": 17.75,
         "revenue": 0.0, "uplift": 0.06, "params": {"command": "credits_credit"}}


def test_tier_is_decided_by_what_we_pay_with_not_by_the_name():
    """Один исполнитель начисляет и скидку на докупку, и бонус себестоимостью."""
    assert tier_of(TOPUP, 0.0) == TIER_OTHER_MARGIN
    assert tier_of(BONUS, 17.75) == TIER_CASH
    assert tier_of(DISCOUNT) == TIER_OWN_REVENUE
    assert tier_of(PAUSE) == TIER_DEFER


def test_trial_extension_leaves_the_free_tier_when_it_actually_costs():
    """В продукте с реальной себестоимостью продлённый триал - живые деньги."""
    trial = {"executor": "trial_extend"}
    assert tier_of(trial, 0.0) == TIER_DEFER
    assert tier_of(trial, 5.92) == TIER_CASH


def test_the_prize_is_margin_not_revenue():
    """Считать приз в выручке - раздуть его и оправдать любую уступку."""
    assert margin_at_stake(10.26, 12) == 123.12
    assert margin_at_stake(99.0, 12) == 1188.0       # то же в выручке - в 10 раз больше
    # то, что и так почти наверняка уйдёт, стоит меньше
    assert margin_at_stake(10.26, 12, churn_risk=0.75) == 30.78
    assert margin_at_stake(None, 12) is None


def test_budget_scales_with_the_customer_instead_of_the_calendar():
    """«Раз в 30 дней» одинаково для клиента за $9 и за $399 - это неверно."""
    assert gift_budget(123.12) == 30.78
    assert gift_budget(1200.0) == 300.0
    assert gift_budget(123.12, spent=25.0) == 5.78
    assert gift_budget(123.12, spent=999.0) == 0.0   # в минус не уходим
    assert gift_budget(None) is None


def test_cash_is_paid_even_when_the_save_fails_but_a_discount_is_not():
    """ГЛАВНАЯ АСИММЕТРИЯ: скидка сама себя финансирует, себестоимость - нет."""
    stake = 123.12
    cash = expected_value(cash=17.75, revenue=0.0, uplift=0.06, stake=stake)
    disc = expected_value(cash=0.0, revenue=17.75, uplift=0.06, stake=stake)
    # одинаковая сумма и одинаковый эффект, но скидку платим только при успехе
    assert cash["cost"] == 17.75
    assert disc["cost"] == 9.94                       # 17.75 x вероятность остаться
    assert disc["ev"] > cash["ev"]


def test_expected_value_says_no_when_the_gift_costs_more_than_it_saves():
    poor = expected_value(cash=50.0, revenue=0.0, uplift=0.05, stake=100.0)
    assert poor["ev"] == -45.0 and "в минус" in poor["note"]
    assert expected_value(0.0, 0.0, None, 100.0)["ev"] is None


def test_cheap_rungs_come_before_expensive_ones():
    ranked = rank([BONUS, DISCOUNT, TOPUP, PAUSE], stake=400.0)
    assert [r["offer_id"] for r in ranked][:2] == ["pause", "topup"]
    # дорогое не выброшено, а отложено с объяснением
    bonus = next(r for r in ranked if r["offer_id"] == "bonus")
    assert bonus["blocked"]["code"] == "cheaper_rung_first"


def test_the_ladder_opens_up_as_cheaper_rungs_get_used():
    tried = {0, 1, 2}                                  # слово, отсрочка, чужая маржа
    ranked = rank([BONUS, DISCOUNT], stake=400.0, tried_tiers=tried)
    assert ranked[0]["offer_id"] == "disc" and not ranked[0]["blocked"]


def test_small_customers_never_get_cash():
    """На клиенте за $9/мес живые деньги не тратят ни при какой вероятности."""
    ranked = rank([BONUS], stake=20.0, tried_tiers={0, 1, 2, 3})
    assert ranked[0]["blocked"]["code"] == "stake_too_small"


def test_budget_blocks_what_the_person_can_no_longer_afford():
    ranked = rank([BONUS], stake=400.0, budget=5.0, tried_tiers={0, 1, 2, 3})
    assert ranked[0]["blocked"]["code"] == "budget_spent"


def test_giving_nothing_is_a_valid_answer():
    """Если всё в минусе, честнее промолчать, чем подарить деньги."""
    hopeless = {"offer_id": "x", "executor": "balance_credit", "cash": 90.0,
                "revenue": 0.0, "uplift": 0.05}
    assert choose([hopeless], stake=100.0, tried_tiers={0, 1, 2, 3}) is None
    assert choose([], stake=100.0) is None


def test_choose_picks_the_cheapest_offer_that_actually_pays_off():
    picked = choose([BONUS, DISCOUNT, TOPUP, PAUSE], stake=400.0)
    assert picked["offer_id"] == "pause"
    assert picked["ev"] > 0 and picked["tier"] == TIER_DEFER


def test_measurement_replaces_the_prior_and_says_so():
    """Догадка через месяц не должна читаться как факт."""
    value, src = uplift_or_prior(None, "stripe_coupon")
    assert src == "prior" and value == 0.06
    value, src = uplift_or_prior({"uplift": 0.19, "confident": True}, "stripe_coupon")
    assert src == "measured" and value == 0.19
    # незрелый замер не вытесняет прайор
    _, src = uplift_or_prior({"uplift": 0.9, "confident": False}, "stripe_coupon")
    assert src == "prior"


def test_the_hubcontent_case_resolves_the_way_the_spreadsheet_implies():
    """Опорный кейс: подписка по себестоимости, маржа в докупке.

    Правильный ответ - пауза, затем скидка на пакет докупки, и НИКОГДА бонус
    кредитами: он уносит $17.75 живых денег ради $10.26 маржи в месяц.
    """
    stake = margin_at_stake(10.26, 12)                 # $123.12 за год
    budget = gift_budget(stake)                        # $30.78
    ranked = rank([BONUS, DISCOUNT, TOPUP, PAUSE], stake, budget)
    order = [r["offer_id"] for r in ranked if not r["blocked"]]
    assert order[0] == "pause"
    assert "bonus" not in order
    bonus = next(r for r in ranked if r["offer_id"] == "bonus")
    assert bonus["cash"] == 17.75 and bonus["blocked"]
