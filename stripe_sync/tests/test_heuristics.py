"""Скоры heur-v1: веса Шпаргалки §3 и краевые случаи."""

from stripe_sync.heuristics import compute_scores


def _f(**kw):
    base = {"sub_status": "", "plan_mrr": 0.0, "monthly_tokens": 0,
            "generations_total": 0, "generations_7d": 0, "generations_prev_7d": 0,
            "gen_days_this_month": 0, "paywall_views": 0, "checkout_starts": 0,
            "cancel_flow_14d": 0, "tokens_spent_month": 0, "days_since_seen": 0,
            "failed_recent": 0, "cancel_scheduled": 0}
    base.update(kw)
    return base


def test_hot_trial_high_convert():
    s = compute_scores(_f(sub_status="trialing", plan_mrr=49,
                          generations_total=5, paywall_views=2, checkout_starts=1))
    assert s["p_convert"] >= 0.8
    assert s["p_churn"] == 0.0
    assert s["ltv_estimate"] == round(49 * 6 * s["p_convert"], 2)


def test_stale_visitor_low_convert():
    s = compute_scores(_f(days_since_seen=30))
    assert s["p_convert"] <= 0.05
    assert s["ltv_estimate"] == 0.0


def test_paying_convert_is_one_churn_baseline():
    s = compute_scores(_f(sub_status="active", plan_mrr=49, generations_7d=3,
                          generations_prev_7d=3))
    assert s["p_convert"] == 1.0
    assert s["p_churn"] == 0.08


def test_churn_stacks_cancel_and_decay():
    s = compute_scores(_f(sub_status="active", plan_mrr=49,
                          generations_prev_7d=6, generations_7d=1,
                          cancel_flow_14d=1))
    assert abs(s["p_churn"] - 0.68) < 1e-9        # 0.08 + 0.30 + 0.30
    assert s["ltv_estimate"] == round(49 * 6 * (1 - 0.68), 2)


def test_churn_idle_and_failed_payment():
    s = compute_scores(_f(sub_status="past_due", plan_mrr=19, failed_recent=1))
    assert abs(s["p_churn"] - (0.08 + 0.15 + 0.25)) < 1e-9


def test_power_burn_and_habit():
    s = compute_scores(_f(sub_status="active", plan_mrr=49, monthly_tokens=1500,
                          tokens_spent_month=1300, gen_days_this_month=16,
                          paywall_views=1))
    assert s["power_score"] == 1.0                # 0.5 + 0.3 + 0.2

    s = compute_scores(_f(sub_status="active", monthly_tokens=1500,
                          tokens_spent_month=1000))
    assert s["power_score"] == 0.2                # burn 0.66 → средняя ступень


def test_power_zero_for_non_paying():
    s = compute_scores(_f(sub_status="trialing", monthly_tokens=1500,
                          tokens_spent_month=1400))
    assert s["power_score"] == 0.0
