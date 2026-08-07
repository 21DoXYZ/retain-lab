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
    # ставка крупная: на мелком клиенте скидка не окупается сама по себе
    ranked = rank([BONUS, DISCOUNT], stake=2000.0, tried_tiers=tried)
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


# ── Поправки по внешним замерам: долговечность, спящие собаки, причина ───────

def test_a_discount_saves_people_who_leave_anyway():
    """Удержание скидкой кончается уходом в 70-80% случаев.

    Без поправки на долговечность скидка всегда побеждает паузу на бумаге:
    у неё дешевле выдача. На деле она покупает не клиента, а отсрочку.
    """
    from offer_value import durable_gain
    assert durable_gain(1000.0, 0.1, "stripe_coupon") == 25.0
    assert durable_gain(1000.0, 0.1, "pause_collection") == 75.0
    # при равном эффекте пауза сохраняет втрое больше
    coupon = expected_value(0.0, 20.0, 0.1, 1000.0, executor="stripe_coupon")
    pause = expected_value(0.0, 20.0, 0.1, 1000.0, executor="pause_collection")
    assert pause["ev"] > coupon["ev"]
    assert coupon["durability"] == 0.25


def test_we_do_not_wake_someone_who_was_going_to_stay():
    """4-5% людей уходят ИМЕННО потому, что их потревожили.

    Целиться по «риску ухода» - худший способ их найти: там они и сидят.
    """
    from offer_value import wakes_a_sleeping_dog
    assert wakes_a_sleeping_dog("stripe_coupon", churn_risk=0.05) is True
    assert wakes_a_sleeping_dog("stripe_coupon", churn_risk=0.80) is False
    assert wakes_a_sleeping_dog("message", churn_risk=0.05) is False
    # риск неизвестен - не выдумываем и не блокируем
    assert wakes_a_sleeping_dog("stripe_coupon", churn_risk=None) is False

    ranked = rank([DISCOUNT], stake=2000.0, tried_tiers={0, 1, 2}, churn_risk=0.05)
    assert ranked[0]["blocked"]["code"] == "would_stay_anyway"


def test_the_offer_matches_the_reason_the_person_gave():
    """Общий оффер спасает 5-10% уходящих, подобранный под причину - 15-30%."""
    from offer_value import offer_for_reason
    assert offer_for_reason("price")["executor"] == "stripe_coupon"
    assert offer_for_reason("one_time_need")["executor"] == "pause_collection"
    assert offer_for_reason("switched")["executor"] == "pause_collection"
    # причина неизвестна - обычный порядок лестницы, гадать вредно
    assert offer_for_reason("")["matched"] is False


def test_money_is_not_offered_where_money_does_not_help():
    """Ушедшему из-за отсутствующей функции скидка не помогает.

    Настаивать подарком в этом случае - превращать удержание в тёмный
    паттерн: человеку нужна функция, а не деньги.
    """
    for reason in ("missing_feature", "quality", "support"):
        ranked = rank([DISCOUNT], stake=2000.0, tried_tiers={0, 1, 2},
                      churn_risk=0.9, reason=reason)
        assert ranked[0]["blocked"]["code"] == "reason_needs_no_gift", reason


def test_the_stated_reason_overrides_the_default_ladder():
    """«Задача кончилась» - это пауза, а не скидка, сколько бы ни было маржи."""
    ranked = rank([DISCOUNT, PAUSE], stake=2000.0, churn_risk=0.9,
                  reason="one_time_need")
    picked = [r for r in ranked if not r["blocked"]]
    assert picked and picked[0]["offer_id"] == "pause"
    disc = next(r for r in ranked if r["offer_id"] == "disc")
    assert disc["blocked"]["code"] == "reason_wants_another_lever"
    assert disc["blocked"]["executor"] == "pause_collection"


def test_price_is_the_one_reason_where_a_discount_belongs():
    ranked = rank([DISCOUNT], stake=2000.0, tried_tiers={0, 1, 2},
                  churn_risk=0.9, reason="price")
    assert not ranked[0]["blocked"]


# ── Опыт ниш с самым долгим стажем удержания (iGaming, free-to-play) ─────────

def test_product_currency_beats_cash_of_the_same_value():
    """A/B на 2000 спящих: валюта продукта вернула 14.9%, деньги - 5.4%.

    Деньги читаются как откуп, валюта продукта - как повод вернуться в
    продукт. Поэтому прайор у неё выше, хотя щедрость меньше.
    """
    from offer_value import uplift_or_prior
    units, _ = uplift_or_prior(None, "client_callback")
    cash, _ = uplift_or_prior(None, "balance_credit")
    assert units > cash * 2


def test_quiet_means_different_things_to_different_customers():
    """Неделя тишины у крупного клиента - тревога, у разового - норма.

    Один порог для всех - это одновременно ложная тревога по мелким и
    опоздание по крупным.
    """
    from offer_value import quiet_window, value_tier
    assert value_tier(400.0, 100.0) == "top"          # вдвое дороже медианы
    assert value_tier(90.0, 100.0) == "regular"
    assert value_tier(20.0, 100.0) == "light"
    # медианы нет - не выдумываем, все обычные
    assert value_tier(400.0, None) == "regular"
    assert quiet_window("top") == 7
    assert quiet_window("light") == 30
    assert quiet_window("неизвестно") == 14


def test_we_stop_paying_for_someone_who_has_decided():
    """Предел попыток: без него бюджет уходит незаметно.

    Каждая отдельная выдача выглядит оправданной - именно поэтому предел
    должен стоять на счётчике, а не на здравом смысле.
    """
    from offer_value import give_up
    assert give_up(3) is False
    assert give_up(4) is True
    assert give_up(4, "top") is False        # крупному одна попытка сверху
    assert give_up(5, "top") is True

    ranked = rank([DISCOUNT], stake=2000.0, tried_tiers={0, 1, 2},
                  churn_risk=0.9, attempts=4)
    assert ranked[0]["blocked"]["code"] == "enough_attempts"
    # бесплатное слово предел не трогает: оно ничего не стоит
    ranked = rank([{"offer_id": "m", "executor": "message", "cash": 0.0,
                    "revenue": 0.0, "uplift": 0.03}], stake=2000.0, attempts=9)
    assert not ranked[0]["blocked"]
