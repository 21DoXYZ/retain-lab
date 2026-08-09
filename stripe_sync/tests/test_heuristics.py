"""Скоры heur-v2: веса, краевые случаи и правки аудита качества.

v2 против v1: cold-start не хоронит новичков, несписание не двоится в скоре
(им владеет стадия DUNNING), LTV - через ожидаемую жизнь 1/p_churn, поведение
сниппета v2 (фрустрация, обвал времени) наконец скорится.
"""

from stripe_sync.heuristics import compute_scores, expected_months


def _f(**kw):
    base = {"sub_status": "", "plan_mrr": 0.0, "monthly_tokens": 0,
            "generations_total": 0, "generations_7d": 0, "generations_prev_7d": 0,
            "gen_days_this_month": 0, "paywall_views": 0, "checkout_starts": 0,
            "cancel_flow_14d": 0, "tokens_spent_month": 0, "days_since_seen": 0,
            "tenure_days": 30, "rage_clicks_7d": 0, "js_errors_7d": 0,
            "active_sec_7d": 0, "active_sec_prev_7d": 0,
            "pricing_visits": 0, "downloads_14d": 0, "inp_ms": 0,
            "apple_pay": 0,
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


def test_fresh_signup_is_not_a_corpse():
    """Cold-start: юзер зарегистрировался час назад, событий ещё нет.
    v1 подставлял days_since_seen=999 и прибивал p_convert к полу - новичок,
    которому продукт должен помочь активироваться, выглядел мёртвым."""
    dead = compute_scores(_f(days_since_seen=999, tenure_days=0))
    old = compute_scores(_f(days_since_seen=999, tenure_days=30))
    assert dead["p_convert"] == 0.05      # новичок: базовый шанс, не пол
    assert old["p_convert"] == 0.01       # месяц молчания - честно холодный


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
    # LTV = MRR x ожидаемая жизнь (1/p_churn), не фиксированные 6 месяцев
    assert s["ltv_estimate"] == round(49 * expected_months(0.68), 2)


def test_failed_payment_is_a_fact_not_a_score():
    """Несписание - факт стадии DUNNING (методология §3), в p_churn ему не
    место: раньше оно двоилось - и стадию включало, и скор поднимало."""
    with_fail = compute_scores(_f(sub_status="past_due", plan_mrr=19,
                                  failed_recent=1, tenure_days=60))
    without = compute_scores(_f(sub_status="past_due", plan_mrr=19,
                                tenure_days=60))
    assert with_fail["p_churn"] == without["p_churn"]


def test_idle_needs_tenure():
    """«Не пользуется 14 дней» имеет смысл, только если человек успел бы
    начать: у аккаунта младше 14 дней это не тишина, а юность."""
    young = compute_scores(_f(sub_status="active", plan_mrr=19, tenure_days=5))
    old = compute_scores(_f(sub_status="active", plan_mrr=19, tenure_days=60))
    assert young["p_churn"] == 0.08
    assert abs(old["p_churn"] - 0.23) < 1e-9      # 0.08 + 0.15


def test_frustration_signals_raise_churn():
    """Поведение сниппета v2: продукт падает (js_error) и бесит (rage) -
    человек уйдёт раньше, чем это увидят метрики использования."""
    calm = compute_scores(_f(sub_status="active", plan_mrr=49,
                             generations_7d=3, generations_prev_7d=3))
    angry = compute_scores(_f(sub_status="active", plan_mrr=49,
                              generations_7d=3, generations_prev_7d=3,
                              js_errors_7d=5, rage_clicks_7d=4))
    assert abs(angry["p_churn"] - (calm["p_churn"] + 0.20)) < 1e-9


def test_engagement_time_collapse_raises_churn():
    """Жил в продукте (10+ мин за неделю) и почти исчез - ранний сигнал."""
    s = compute_scores(_f(sub_status="active", plan_mrr=49,
                          generations_7d=2, generations_prev_7d=2,
                          active_sec_prev_7d=3600, active_sec_7d=300))
    assert abs(s["p_churn"] - 0.23) < 1e-9        # 0.08 + 0.15
    # мало жил раньше - обвал не считается (не с чего падать)
    s2 = compute_scores(_f(sub_status="active", plan_mrr=49,
                           generations_7d=2, generations_prev_7d=2,
                           active_sec_prev_7d=120, active_sec_7d=0))
    assert s2["p_churn"] == 0.08


def test_ltv_lifetime_is_survival_based_and_capped():
    assert expected_months(0.08) == 12.5          # 1/0.08
    assert expected_months(0.02) == 24.0          # кап сверху
    assert expected_months(0.95) >= 1.0           # кап снизу
    base = compute_scores(_f(sub_status="active", plan_mrr=100,
                             generations_7d=1, generations_prev_7d=1))
    assert base["ltv_estimate"] == round(100 * 12.5, 2)


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


def test_buy_intent_from_pricing_visits():
    """Кросс-сессионные заходы на прайсинг - сильнейший сигнал намерения."""
    base = compute_scores(_f(sub_status="active", plan_mrr=49))
    assert base["buy_intent"] == 0.0
    one = compute_scores(_f(sub_status="active", plan_mrr=49, pricing_visits=1))
    three = compute_scores(_f(sub_status="active", plan_mrr=49, pricing_visits=3))
    assert three["buy_intent"] > one["buy_intent"] > 0
    # чекаут + прайсинг складываются
    hot = compute_scores(_f(sub_status="active", plan_mrr=49,
                            pricing_visits=3, checkout_starts=1, paywall_views=1))
    assert hot["buy_intent"] >= 0.9


def test_slow_inp_raises_churn():
    """Тормозящий отклик (INP) - тихая фрустрация, поднимает риск."""
    calm = compute_scores(_f(sub_status="active", plan_mrr=49,
                             generations_7d=3, generations_prev_7d=3))
    slow = compute_scores(_f(sub_status="active", plan_mrr=49,
                             generations_7d=3, generations_prev_7d=3, inp_ms=1200))
    assert abs(slow["p_churn"] - (calm["p_churn"] + 0.10)) < 1e-9


def test_buy_intent_zero_for_no_signals():
    assert compute_scores(_f(sub_status="trialing"))["buy_intent"] == 0.0
