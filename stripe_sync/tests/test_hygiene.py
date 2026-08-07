"""Гигиена офферов и holdout: правила ТЗ §121 на фикстурах."""

from stripe_sync.hygiene import (
    check_monetary_cap_14d,
    check_offer_limit_30d,
    check_p_convert_cap,
    holdout_split,
    run_checks,
)

MONETARY = {"offer_id": "O2_discount20", "monetary": True, "max_per_user_30d": 1}
FREE = {"offer_id": "O5_priority_14d", "monetary": False, "max_per_user_30d": 1}
TRIAL_HOT = {"sub_status": "trialing", "p_convert": 0.85}
TRIAL_COLD = {"sub_status": "trialing", "p_convert": 0.2}
PAYING = {"sub_status": "past_due", "p_convert": 1.0}


def test_high_p_convert_blocks_monetary_for_non_paying():
    assert check_p_convert_cap(MONETARY, TRIAL_HOT, 0.7) == (False, "high_p_convert")
    assert check_p_convert_cap(MONETARY, TRIAL_COLD, 0.7) == (True, "")


def test_p_convert_cap_ignores_paying_and_free_offers():
    # DUNNING/SAVE: p_convert=1.0 по определению — скидку давать МОЖНО
    assert check_p_convert_cap(MONETARY, PAYING, 0.7) == (True, "")
    assert check_p_convert_cap(FREE, TRIAL_HOT, 0.7) == (True, "")


def test_monetary_cap_14d():
    hist = [{"offer_id": "O1_tokens_100", "monetary": 1, "status": "issued"}]
    assert check_monetary_cap_14d(MONETARY, hist) == (False, "monetary_cap_14d")
    assert check_monetary_cap_14d(FREE, hist) == (True, "")
    # holdout, rejected и прогон вхолостую выдачей не считаются
    hist2 = [{"offer_id": "O1", "monetary": 1, "status": "holdout"},
             {"offer_id": "O2", "monetary": 1, "status": "rejected"},
             {"offer_id": "O3", "monetary": 1, "status": "dry_run"}]
    assert check_monetary_cap_14d(MONETARY, hist2) == (True, "")


def test_offer_limit_30d_counts_same_offer_only():
    hist = [{"offer_id": "O2_discount20", "monetary": 1, "status": "issued"},
            {"offer_id": "O1_tokens_100", "monetary": 1, "status": "issued"}]
    assert check_offer_limit_30d(MONETARY, hist) == (False, "offer_limit_30d")
    assert check_offer_limit_30d({**MONETARY, "offer_id": "O7_annual25"}, hist) == (True, "")


def test_run_checks_first_failure_wins():
    ok, reason = run_checks(MONETARY, TRIAL_HOT, [], [], 0.7)
    assert (ok, reason) == (False, "high_p_convert")
    ok, reason = run_checks(FREE, TRIAL_HOT, [], [], 0.7)
    assert (ok, reason) == (True, "")


def test_holdout_deterministic_and_near_10pct():
    flags = [holdout_split("t", "K3", f"id-{i}", 10) for i in range(2000)]
    assert flags == [holdout_split("t", "K3", f"id-{i}", 10) for i in range(2000)]
    share = sum(flags) / len(flags)
    assert 0.07 < share < 0.13
    assert holdout_split("t", "K3", "x", 0) is False
    assert holdout_split("t", "K3", "x", 100) is True


def test_new_tenant_inherits_default_thresholds(tmp_path, monkeypatch):
    """Клиент без git-пресета обязан получить пороги экономики из _default:
    иначе churn_floor=0 и монетарные офферы летят тем, кто не собирался уходить."""
    import json
    import issue
    catalog = {"_default": {"control_pct": 10, "p_convert_cap": 0.7,
                            "churn_floor": 0.25, "offers": []}}
    path = tmp_path / "offers_catalog.json"
    path.write_text(json.dumps(catalog))
    monkeypatch.setattr(issue, "CATALOG_PATH", path)
    monkeypatch.setenv("CAMPAIGN_OVERRIDES_FILE", str(tmp_path / "overrides.json"))
    loaded = issue.load_catalog("brandnew")
    assert loaded["churn_floor"] == 0.25
    assert loaded["p_convert_cap"] == 0.7
    assert loaded["offers"] == []


def test_missing_score_does_not_block_money():
    """«Скора ещё не считали» - это не «риска нет». Раньше NULL превращался в 0
    запросом (coalesce) и монетарные офферы молча резались весь первый день."""
    from stripe_sync.hygiene import check_churn_floor
    offer = {"monetary": True}
    assert check_churn_floor(offer, {"sub_status": "active", "p_churn": None}, 0.25)[0]
    assert not check_churn_floor(offer, {"sub_status": "active", "p_churn": 0.08}, 0.25)[0]


def test_live_risk_stage_beats_yesterday_score():
    """Карта отвалилась утром - стадия DUNNING уже живая, а ночной скор ещё
    считает человека спокойным. Касание обязано уйти: риск тут ФАКТ."""
    from stripe_sync.hygiene import check_churn_floor
    offer = {"monetary": True}
    calm_score = {"sub_status": "active", "p_churn": 0.08}
    assert not check_churn_floor(offer, calm_score, 0.25)[0]
    for stage in ("DUNNING", "WINBACK"):
        assert check_churn_floor(offer, {**calm_score, "stage": stage}, 0.25)[0], stage
    assert not check_churn_floor(offer, {**calm_score, "stage": "MONITOR"}, 0.25)[0]


def test_save_stage_does_not_buy_off_someone_who_would_have_stayed():
    """SAVE - это ВЫВОД по поведению, а не свершившийся факт.

    Около 4-5% людей уходят именно потому, что их потревожили удержанием:
    подарок «мы заметили, что вы собираетесь уйти» напоминает, что они платят.
    Сидят такие ровно среди спокойных по скору, поэтому ДЕНЬГИ на SAVE
    спрашивают скор, а бесплатные рычаги уходят сразу.
    """
    from stripe_sync.hygiene import check_churn_floor
    calm = {"sub_status": "active", "p_churn": 0.08, "stage": "SAVE"}
    assert not check_churn_floor({"monetary": True}, calm, 0.25)[0]
    assert check_churn_floor({"monetary": False}, calm, 0.25)[0]
    # у кого риск настоящий - подарок проходит
    assert check_churn_floor({"monetary": True}, {**calm, "p_churn": 0.7}, 0.25)[0]


def test_safe_mode_does_not_eat_the_gift_budget():
    """Прогон вхолостую не должен расходовать лимиты: иначе в день реального
    запуска все подарки упрутся в «уже давали», хотя никто ничего не получал."""
    from stripe_sync.hygiene import check_monetary_cap_14d, check_offer_limit_30d
    offer = {"offer_id": "A_discount20", "monetary": True, "max_per_user_30d": 1}
    dry = [{"offer_id": "A_discount20", "monetary": True, "status": "dry_run"}]
    real = [{"offer_id": "A_discount20", "monetary": True, "status": "issued"}]
    assert check_monetary_cap_14d(offer, dry)[0]
    assert check_offer_limit_30d(offer, dry)[0]
    assert not check_monetary_cap_14d(offer, real)[0]
    assert not check_offer_limit_30d(offer, real)[0]
