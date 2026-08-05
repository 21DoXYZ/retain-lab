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
    hist = [{"offer_id": "O1_tokens_100", "monetary": 1, "status": "dry_run"}]
    assert check_monetary_cap_14d(MONETARY, hist) == (False, "monetary_cap_14d")
    assert check_monetary_cap_14d(FREE, hist) == (True, "")
    # holdout и rejected не считаются выдачей
    hist2 = [{"offer_id": "O1", "monetary": 1, "status": "holdout"},
             {"offer_id": "O2", "monetary": 1, "status": "rejected"}]
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
