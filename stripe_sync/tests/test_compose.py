"""Селф-онбординг офферов: опросник -> детерминированная сборка + AI-валидация."""

import json
import os
import sys

from stripe_sync.compose import compose_offers, validate_answers, validate_offer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ai_compose import parse_ai_offers  # noqa: E402


FULL = {"product_name": "Hub Content", "value_unit": "tokens",
        "monthly_units": 500, "client_api": True,
        "has_trial": True, "trial_days": 14, "max_discount_pct": 25,
        "can_pause": True}


def test_validate_answers_types_and_required():
    a, r = validate_answers({**FULL, "client_api": "yes", "trial_days": "14"})
    assert r == "" and a["client_api"] is True and a["trial_days"] == 14
    _, r = validate_answers({"has_trial": True, "can_pause": False})
    assert r == "answer_required:product_name"
    _, r = validate_answers({"product_name": "X", "has_trial": True, "can_pause": False})
    assert r == "answer_required:client_api"
    _, r = validate_answers({**FULL, "max_discount_pct": 90})
    assert r == "invalid_answer:max_discount_pct"


def test_compose_full_answers_price():
    offers = compose_offers(FULL, avg_price=50.0)
    ids = {o["offer_id"]: o for o in offers}
    # бонус: 20% от 500 = 100 юнитов, себестоимость 100 * (50/500) = $10
    assert ids["A_bonus_tokens"]["params"]["amount"] == 100
    assert ids["A_bonus_tokens"]["params"]["unit"] == "tokens"
    assert ids["A_bonus_tokens"]["cost_estimate"] == 10.0
    # скидка: потолок 25 -> берём 20; 50 * 20% * 2 мес = $20
    assert ids["A_discount20"]["params"]["percent_off"] == 20
    assert ids["A_discount20"]["cost_estimate"] == 20.0
    assert ids["A_trial_plus7"]["params"]["days"] == 7
    assert ids["A_pause_1m"]["executor"] == "pause_collection"
    # кредит: 20% от чека = $10
    assert ids["A_credit_10"]["params"]["amount_usd"] == 10
    # все прошли бы ручную валидацию
    for o in offers:
        _, reason = validate_offer(o)
        assert reason == "", (o["offer_id"], reason)


def test_compose_zero_ceiling_kills_monetary():
    offers = compose_offers({**FULL, "max_discount_pct": 0}, avg_price=50.0)
    execs = {o["executor"] for o in offers}
    assert "stripe_coupon" not in execs and "balance_credit" not in execs
    assert "client_callback" in execs      # бонус юнитами остаётся


THIN = {**FULL, "monthly_units": 15000, "unit_cost_usd": 0.005916,
        "topup_price": 94.66, "topup_units": 10000, "max_discount_pct": 20}


def test_gift_size_is_set_by_the_margin_it_comes_out_of():
    """«20% от лимита» в тонкой марже - подарок дороже самого клиента.

    Тариф $99 при себестоимости $0.0059 за юнит приносит ~$10 маржи в месяц.
    Раздать 3000 юнитов значит потратить $17.75 живых денег ради $10 дохода.
    """
    offers = {o["offer_id"]: o for o in compose_offers(THIN, avg_price=99.0)}
    bonus = offers["A_bonus_tokens"]
    assert bonus["params"]["amount"] == 433          # не 3000
    assert bonus["cost_estimate"] == 2.56            # четверть месячной маржи


def test_discount_never_sells_the_subscription_below_cost():
    """При валовой марже 10% скидка в 20% делает удержанный месяц убыточным."""
    offers = {o["offer_id"]: o for o in compose_offers(THIN, avg_price=99.0)}
    assert "A_discount20" not in offers
    assert "A_discount5" in offers                   # половина маржи, не больше
    # там, где маржа широкая, ограничение не мешает
    wide = compose_offers({**THIN, "unit_cost_usd": 0.001}, avg_price=99.0)
    assert any(o["offer_id"] == "A_discount20" for o in wide)


def test_topup_discount_is_composed_and_goes_first():
    """К шагу цепочки привязывается ПЕРВЫЙ оффер роли - им должен быть дешёвый."""
    offers = compose_offers(THIN, avg_price=99.0)
    upgrade = [o["offer_id"] for o in offers if o["role"] == "upgrade"]
    assert upgrade[0] == "A_topup18"
    pack = next(o for o in offers if o["offer_id"] == "A_topup18")
    assert pack["params"]["command"] == "topup_discount"
    assert pack["cost_estimate"] == 17.04            # только маржа пакета
    for o in offers:                                 # схема исполнителя соблюдена
        assert validate_offer(o)[1] == ""


def test_limits_apply_to_an_assumed_margin_too():
    """Предположение по типу бизнеса обязано ОГРАНИЧИВАТЬ, а не только украшать.

    Иначе оно живёт на экране, а подарок собирается по-старому - «20% от
    лимита» и «20% скидки», как будто маржа стопроцентная.
    """
    guessed = {**FULL, "monthly_units": 15000, "cost_archetype": "ai_usage"}
    offers = {o["offer_id"]: o for o in compose_offers(guessed, avg_price=99.0)}
    assert offers["A_bonus_tokens"]["params"]["amount"] == 1249     # не 3000
    assert "A_discount20" not in offers and "A_discount12" in offers


def test_archetype_survives_the_questionnaire_submit():
    """Тип экономики выведен из сайта, а не спрошен - и обязан пережить сабмит."""
    a, r = validate_answers({**FULL, "cost_archetype": "ai_usage"})
    assert r == "" and a["cost_archetype"] == "ai_usage"
    a, _ = validate_answers({**FULL, "cost_archetype": "не существует"})
    assert "cost_archetype" not in a


def test_compose_no_api_no_bonus():
    offers = compose_offers({**FULL, "client_api": False}, avg_price=50.0)
    assert all(o["executor"] != "client_callback" for o in offers)


def test_parse_ai_offers_validates_and_caps():
    text = json.dumps({"offers": [
        {"offer_id": "big_discount", "title": "50% off", "executor": "stripe_coupon",
         "monetary": True, "cost_estimate": 50, "max_per_user_30d": 1,
         "params": {"percent_off": 50, "duration": "once"}},
        {"offer_id": "good_bonus", "title": "+100 tokens", "executor": "client_callback",
         "monetary": True, "cost_estimate": 5, "max_per_user_30d": 2,
         "params": {"command": "tokens_credit", "tokens": 100}},
        {"offer_id": "hacked", "title": "x", "executor": "shell",
         "params": {"cmd": "rm"}},
    ]})
    offers, rejected = parse_ai_offers(text, max_discount_pct=25)
    assert [o["offer_id"] for o in offers] == ["AI_good_bonus"]
    assert any("discount_over_ceiling" in r for r in rejected)
    assert any("unknown_executor" in r for r in rejected)


def test_parse_ai_offers_bad_json():
    offers, rejected = parse_ai_offers("sorry, no json here", 20)
    assert offers == [] and rejected == ["ai_json_parse_failed"]


def test_validate_offer_universal_units_derives_command():
    clean, r = validate_offer({"title": "+50 bonus exports", "executor": "client_callback",
                               "params": {"amount": 50, "unit": "exports"}})
    assert r == "" and clean["params"]["command"] == "exports_credit"
    _, r = validate_offer({"title": "x", "executor": "client_callback",
                           "params": {"unit": "exports"}})
    assert r == "param_required:amount"


def test_compose_campaign_copy_any_product():
    from stripe_sync.compose import compose_campaign_copy
    c = compose_campaign_copy({"product_name": "PicSeat", "value_unit": "seats",
                               "app_url": "https://app.picseat.io"})
    # индекс 0 - inapp-баннер: коротко, без ссылок; письма - с индекса 1
    assert "seats" in c["K1_activation"][0]["subject"]
    assert "PicSeat" in c["K1_activation"][1]["body"]
    assert "https://app.picseat.io" in c["K2_trial_conversion"][1]["body"]
    assert "{{" not in c["K2_trial_conversion"][0]["body"]     # баннер без ссылок
    assert "{{card_update_url}}" in c["K3_payment_recovery"][1]["body"]
    assert "seats" in c["K3_payment_recovery"][1]["body"]
    assert "seats" in c["K5_upgrade"][0]["body"]


def test_default_campaigns_block_is_neutral():
    import json
    from pathlib import Path
    data = json.loads((Path("stripe_sync") / "saas_campaigns.json").read_text())
    d = data["_default"]
    txt = json.dumps(d)
    assert "video" not in txt and "token" not in txt.replace("tokens_credit", "")
    offer_steps = [s for c in d["campaigns"] for s in c["steps"] if s["action"] == "offer"]
    assert offer_steps and all(s["offer_id"] == "" for s in offer_steps)


def test_plan_rows_maps_stripe_price_and_client_limit():
    """Цена - из Stripe (годовые /12), лимит - из ответа клиента."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from plans_sync import plan_rows

    rows = plan_rows([("pro_monthly", 49, "month"),
                      ("agency_yearly", 1500, "year"),
                      ("", 10, "month")],          # без plan_id - пропускаем
                     monthly_units=500, tenant="hub", now="2026-08-05 10:00:00.000")
    assert len(rows) == 2
    by_id = {r[1]: r for r in rows}
    assert by_id["pro_monthly"][3] == 49.0
    assert by_id["agency_yearly"][3] == 125.0      # 1500/12
    assert all(r[2] == 500 for r in rows)          # лимит из опросника
    # без ответа клиента лимит 0 - burn_rate останется 0 (честно)
    assert plan_rows([("p", 10, "month")], 0, "hub", "t")[0][2] == 0


def test_compose_covers_all_campaign_roles():
    """Детерминированный набор закрывает все роли, нужные цепочкам с офферами."""
    offers = compose_offers(FULL, avg_price=49.0)
    roles = {o.get("role") for o in offers}
    assert {"activation", "conversion", "save", "upgrade", "winback"} <= roles


def test_ai_copy_strips_em_dash():
    """Длинное тире запрещено правилами бренда - режем в коде, не в промпте."""
    import json as _json
    from ai_compose import parse_ai_copy
    out = parse_ai_copy(_json.dumps({"K1_activation": {"0": {
        "subject": "Don't lose your work—upgrade now",
        "body": "Your trial ends soon–act now: {{app_url}}"}}}))
    assert "—" not in out["K1_activation"][0]["subject"]
    assert "–" not in out["K1_activation"][0]["body"]
    assert " - " in out["K1_activation"][0]["subject"]


def test_site_scan_guards_private_hosts():
    """SSRF: внутренние адреса не читаем ни своим запросом, ни фолбэком."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from site_scan import fallback_reader, fetch, host_is_public, normalize_url

    assert host_is_public("localhost") is False
    assert host_is_public("127.0.0.1") is False
    assert host_is_public("10.0.0.5") is False
    assert host_is_public("169.254.169.254") is False      # облачные метаданные
    assert fetch("http://127.0.0.1:8123") == ""
    assert fallback_reader("http://127.0.0.1:8123") == ""
    assert normalize_url("hubcontent.ai") == "https://hubcontent.ai/"
    assert normalize_url("ftp://x.com") == ""
    assert normalize_url("") == ""


def test_copy_reads_correctly_without_a_value_unit():
    """Без юнита ценности шаблоны не должны выдавать «Your account are safe»:
    клиент видит эти тексты на экране кампаний до всякой генерации."""
    import re
    from stripe_sync.compose import compose_campaign_copy
    for answers in ({}, {"value_unit": "reports"}):
        copy = compose_campaign_copy(answers)
        for cid, steps in copy.items():
            for idx, step in steps.items():
                for field in ("subject", "body"):
                    text = step[field]
                    assert not re.search(r"\b(account|history|work) are\b", text), \
                        f"{cid}:{idx}:{field} -> {text}"
                    assert "your your" not in text.lower()


def test_winback_discount_obeys_the_same_margin_hygiene():
    """Правило, применённое к одной скидке и забытое у соседней - хуже
    отсутствия правила: на марже 10% собирался «20% off first month back»,
    который продаёт возвращённый месяц ниже себестоимости."""
    offers = {o["offer_id"]: o for o in compose_offers(THIN, avg_price=99.0)}
    assert "A_winback20" not in offers and "A_winback30" not in offers
    assert "A_winback5" in offers                     # половина маржи


def test_credit_is_capped_by_margin_not_by_price():
    """«20% от чека» на марже 10% дарит вдвое больше месячной маржи клиента."""
    offers = {o["offer_id"]: o for o in compose_offers(THIN, avg_price=99.0)}
    credits = [o for o in offers.values() if o["executor"] == "balance_credit"]
    assert credits and credits[0]["cost_estimate"] <= 10.26 * 0.25 + 1
    # без данных о марже поведение прежнее - от цены
    wide = {o["offer_id"]: o for o in compose_offers(FULL, avg_price=50.0)}
    assert wide["A_credit_10"]["cost_estimate"] == 10.0
