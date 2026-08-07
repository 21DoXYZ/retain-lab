"""Методология в исполняемом виде: каждый оффер проходит разбор.

Проверяем не «есть ли текст замечания», а что разбор ЛОВИТ ровно те ошибки,
ради которых методология писалась, и молчит там, где оффер хорош. Молчание в
хорошем случае не менее важно: разбор, который ругается всегда, перестают
читать через неделю.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offer_review import HARMFUL, NOTE, WEAK, review, review_catalog  # noqa: E402

# опорный клиент: тариф $99, валовая маржа 10%, маржа $10.26 в месяц
THIN = {"cost_basis": "stated", "gross_margin": 0.1036, "monthly_margin": 10.26,
        "gift_budget": 30.78, "stage": "ACTIVATE"}
FAT = {"cost_basis": "margin", "gross_margin": 0.85, "monthly_margin": 84.15,
       "gift_budget": 250.0, "stage": "ACTIVATE"}

BONUS = {"offer_id": "A_bonus", "executor": "client_callback", "monetary": True,
         "params": {"command": "credits_credit", "amount": 3000}}
DISCOUNT20 = {"offer_id": "A_d20", "executor": "stripe_coupon", "monetary": True,
              "params": {"percent_off": 20, "duration": "once"}}
PAUSE = {"offer_id": "A_pause", "executor": "pause_collection",
         "monetary": False, "params": {"months": 1}}
CREDIT = {"offer_id": "A_credit", "executor": "balance_credit", "monetary": True,
          "params": {"amount_usd": 7}}


def codes(result) -> set:
    return {f["code"] for f in result["flags"]}


def test_a_gift_bigger_than_the_customer_is_called_harmful():
    """$17.75 живых денег ради клиента, приносящего $10.26 маржи в месяц."""
    r = review(BONUS, {**THIN, "cash": 17.75})
    assert r["verdict"] == HARMFUL
    assert "gift_costs_more_than_the_customer" in codes(r)
    flag = next(f for f in r["flags"] if f["code"] == "gift_costs_more_than_the_customer")
    # замечание несёт ЧИСЛА, а не готовую фразу: текст живёт в словарях
    assert flag["params"]["cash"] == 17.75 and flag["params"]["margin"] == 10.26


def test_a_discount_deeper_than_the_margin_is_called_harmful():
    """При марже 10% скидка 20% делает удержанный месяц убыточным."""
    r = review(DISCOUNT20, THIN)
    assert r["verdict"] == HARMFUL
    assert "discount_sells_below_cost" in codes(r)
    # у клиента с широкой маржой та же скидка вопросов не вызывает
    assert "discount_sells_below_cost" not in codes(review(DISCOUNT20, FAT))


def test_a_discount_is_flagged_as_a_delay_not_a_customer():
    """Удержание скидкой кончается уходом: это надо говорить вслух."""
    r = review(DISCOUNT20, FAT)
    assert "buys_a_delay_not_a_customer" in codes(r)
    assert r["durability"] == 0.25


def test_cash_is_flagged_against_product_currency():
    r = review(CREDIT, {**FAT, "cash": 7.0})
    assert "cash_reads_as_a_payoff" in codes(r)


def test_a_good_offer_stays_quiet():
    """Разбор, который ругается всегда, перестают читать через неделю."""
    r = review(PAUSE, FAT)
    assert r["verdict"] == "ok"
    assert r["flags"] == [] and r["alternative"] is None


def test_an_assumed_cost_is_a_note_not_an_accusation():
    r = review(BONUS, {"cost_basis": "assumed", "monthly_margin": 40.0,
                       "gift_budget": 10.0, "cash": 2.0, "stage": "ACTIVATE"})
    assert r["verdict"] == "ok" or r["verdict"] == WEAK
    assert "cost_is_assumed" in codes(r)
    assert all(f["level"] == NOTE for f in r["flags"]
               if f["code"].startswith("cost_is_"))


def test_money_at_a_stage_that_is_only_a_guess_is_flagged():
    """SAVE - вывод по поведению; часть таких людей осталась бы сама."""
    assert "may_wake_a_sleeping_dog" in codes(review(DISCOUNT20, {**FAT, "stage": "SAVE"}))
    # на подтверждённом факте вопросов нет
    assert "may_wake_a_sleeping_dog" not in codes(
        review(DISCOUNT20, {**FAT, "stage": "DUNNING"}))
    # спокойным деньги не шлют вовсе
    r = review(DISCOUNT20, {**FAT, "stage": "MONITOR"})
    assert r["verdict"] == HARMFUL


def test_the_stated_reason_overrides_the_gift():
    r = review(DISCOUNT20, {**FAT, "stage": "SAVE", "reason": "missing_feature"})
    assert "reason_is_not_about_money" in codes(r)
    assert r["verdict"] == HARMFUL
    # под «дорого» скидка как раз уместна
    assert "reason_is_not_about_money" not in codes(
        review(DISCOUNT20, {**FAT, "stage": "SAVE", "reason": "price"}))


def test_a_cheaper_rung_in_the_catalog_is_pointed_out():
    r = review(DISCOUNT20, {**FAT, "available_tiers": {1, 3}})
    assert "cheaper_rung_exists" in codes(r)
    # если дешёвой ступени в каталоге нет - молчим, предлагать нечего
    assert "cheaper_rung_exists" not in codes(review(DISCOUNT20, {**FAT,
                                                     "available_tiers": {3}}))


def test_every_complaint_comes_with_a_replacement():
    """Разбор обязан предлагать выход, а не только ставить диагноз."""
    r = review(DISCOUNT20, {**THIN, "stage": "SAVE",
                            "can_execute": {"pause_collection"}})
    assert r["verdict"] != "ok"
    assert r["alternative"] and r["alternative"]["executor"] == "pause_collection"
    assert r["alternative"]["why"]


def test_pause_is_not_proposed_where_nobody_is_leaving():
    """Пауза лечит уход. Советовать её вместо активационного бонуса -
    бессмыслица: нечего ставить на паузу у того, кто не начал пользоваться."""
    activation = {**BONUS, "role": "activation"}
    r = review(activation, {**THIN, "cash": 17.75, "stage": "ACTIVATE",
                            "can_execute": {"pause_collection"}})
    assert r["verdict"] == "harmful"          # подарок дороже клиента
    assert r["alternative"] is None           # но пауза тут не замена
    # тому же офферу с докупкой в каталоге замена находится
    r2 = review(activation, {**THIN, "cash": 17.75, "stage": "ACTIVATE",
                             "has_topup": True,
                             "can_execute": {"client_callback"}})
    assert r2["alternative"]["why"] == "topup_costs_no_cash"


def test_catalog_view_does_not_cry_wolf_about_sleeping_dogs():
    """Каталог смотрят без конкретного человека - стадия неизвестна.

    Замечание про спящих собак на каждой карточке приучает его не читать.
    """
    assert "may_wake_a_sleeping_dog" not in codes(review(DISCOUNT20, FAT))
    assert "may_wake_a_sleeping_dog" not in codes(review(BONUS, {}))


def test_the_ladder_compares_within_a_role_not_across():
    """Активационному бонусу нельзя советовать ступень спасательной паузы."""
    from offer_review import review_catalog
    out = review_catalog(
        [{**BONUS, "role": "activation", "_cash": 5.0},
         {**PAUSE, "role": "save"}],
        {"cost_basis": "margin", "gross_margin": 0.85, "monthly_margin": 84.15,
         "gift_budget": 250.0})
    by_id = {r["offer_id"]: r for r in out}
    assert "cheaper_rung_exists" not in {f["code"] for f in by_id["A_bonus"]["flags"]}


def test_a_card_never_shows_more_than_three_flags():
    """Стена из пяти замечаний перестаёт читаться - главное уже наверху."""
    r = review({**CREDIT, "role": "save"},
               {**THIN, "cash": 40.0, "stage": "SAVE",
                "reason": "missing_feature", "available_tiers": {1, 4}})
    assert len(r["flags"]) <= 3
    assert r["flags"][0]["level"] == "harmful"


def test_the_replacement_only_offers_what_the_client_can_actually_do():
    """Без паузы в биллинге предлагать паузу - издевательство."""
    r = review(DISCOUNT20, {**THIN, "can_execute": {"stripe_coupon"}})
    assert r["alternative"] is None


def test_the_replacement_follows_the_stated_reason_first():
    r = review(DISCOUNT20, {**FAT, "stage": "SAVE", "reason": "one_time_need",
                            "can_execute": {"pause_collection", "stripe_coupon"}})
    assert r["alternative"]["executor"] == "pause_collection"


def test_cap_in_pieces_is_noted_when_there_is_no_budget():
    r = review(BONUS, {"cost_basis": "stated", "monthly_margin": 40.0,
                       "cash": 2.0, "stage": "ACTIVATE"})
    assert "cap_counted_in_pieces" in codes(r)
    assert "cap_counted_in_pieces" not in codes(review(BONUS, {**FAT, "cash": 2.0}))


def test_the_catalog_is_reviewed_as_a_whole():
    """«Есть рычаг дешевле» осмысленно только если он в каталоге ЕСТЬ."""
    out = review_catalog([{**PAUSE}, {**DISCOUNT20, "_cash": 0.0}], FAT)
    assert len(out) == 2
    by_id = {r["offer_id"]: r for r in out}
    assert by_id["A_pause"]["verdict"] == "ok"
    assert "cheaper_rung_exists" in {f["code"] for f in by_id["A_d20"]["flags"]}


def test_review_never_crashes_on_a_thin_context():
    """Разбор работает и когда про клиента не известно почти ничего."""
    for offer in (BONUS, DISCOUNT20, PAUSE, CREDIT):
        r = review(offer, {})
        assert r["verdict"] in (HARMFUL, WEAK, "ok")
        assert isinstance(r["flags"], list)


def test_no_check_ever_returns_prose():
    """Готовая фраза с сервера - ошибка, которую уже ловили трижды.

    Её нельзя показать на другом языке, нельзя проверить тестом и нельзя
    переформулировать, не трогая логику. С сервера уходят код и числа.
    """
    contexts = [THIN, FAT, {}, {**FAT, "stage": "SAVE", "reason": "missing_feature"},
                {**THIN, "cash": 17.75}, {**FAT, "stage": "MONITOR"}]
    for ctx in contexts:
        for offer in (BONUS, DISCOUNT20, PAUSE, CREDIT):
            r = review(offer, ctx)
            for f in r["flags"]:
                assert set(f) == {"code", "level", "params"}, f
                assert f["code"] and f["code"].isascii()
                for value in f["params"].values():
                    assert isinstance(value, (int, float, str))
                    # строки в параметрах - только машинные значения
                    if isinstance(value, str):
                        assert value.isascii() and " " not in value, f
            alt = r["alternative"]
            if alt:
                assert set(alt) <= {"executor", "why", "reason"}
                assert alt["why"].isascii() and " " not in alt["why"]


def test_client_wide_notes_are_shown_once_not_on_every_card():
    """«Себестоимость неизвестна» на пяти карточках читается как пять проблем."""
    from offer_review import split_catalog_notes
    reviewed = review_catalog([{**BONUS, "_cash": 1.0}, {**CREDIT, "_cash": 7.0}],
                              {"cost_basis": "price", "monthly_margin": 84.15,
                               "stage": "ACTIVATE"})
    reviewed, notes = split_catalog_notes(reviewed)
    assert {n["code"] for n in notes} == {"cost_is_list_price", "cap_counted_in_pieces"}
    for item in reviewed:
        assert not any(f["code"] in ("cost_is_list_price", "cap_counted_in_pieces")
                       for f in item["flags"])
    # то, что относится к самому подарку, остаётся на карточке
    by_id = {r["offer_id"]: r for r in reviewed}
    assert "cash_reads_as_a_payoff" in {f["code"] for f in by_id["A_credit"]["flags"]}
