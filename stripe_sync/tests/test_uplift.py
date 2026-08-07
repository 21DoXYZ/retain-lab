"""Uplift-математика и draft-approval гейт."""

from stripe_sync.campaign_tick import effective_configs
from stripe_sync.executors import ExecConfig
from stripe_sync.saas_senders import EmailConfig
from stripe_sync.uplift_report import uplift_math


def test_uplift_positive_case():
    m = uplift_math(n_target=7, n_control=1, conv_target_cnt=3,
                    conv_control_cnt=0, avg_check=49.0)
    assert m["conv_target"] == round(3 / 7, 4)
    assert m["conv_control"] == 0.0
    assert m["incremental_usd"] == round((3 / 7) * 7 * 49.0, 2)


def test_uplift_negative_shown_as_is():
    m = uplift_math(5, 5, 1, 3, 20.0)
    assert m["incremental_usd"] == round((0.2 - 0.6) * 5 * 20.0, 2)


def test_uplift_empty_holdout_is_na_not_zero():
    m = uplift_math(10, 0, 5, 0, 30.0)
    assert m["incremental_usd"] is None
    assert m["conv_control"] == 0.0


def test_uplift_invert_for_churn_goal():
    # цель K4: НЕ отменился. 1/4 таргета отменился, 1/2 контроля отменился.
    m = uplift_math(4, 2, 1, 1, 40.0, invert=True)
    assert m["conv_target"] == 0.75 and m["conv_control"] == 0.5
    assert m["incremental_usd"] == round(0.25 * 4 * 40.0, 2)


def test_autopilot_gate_forces_dry_run():
    live_email = EmailConfig(dry_run=False, resend_api_key="k", email_from="a@b")
    live_exec = ExecConfig(dry_run=False, stripe_api_key="sk")
    e, x = effective_configs({"autopilot": False}, live_email, live_exec)
    assert e.dry_run is True and x.dry_run is True
    e, x = effective_configs({}, live_email, live_exec)     # нет флага = false
    assert e.dry_run is True and x.dry_run is True
    e, x = effective_configs({"autopilot": True}, live_email, live_exec)
    assert e.dry_run is False and x.dry_run is False


def test_small_groups_are_marked_as_early_signal():
    """Семь человек против семи - это не измерение, а шум. Цифру показываем,
    но помечаем: иначе владелец примет случайность за результат."""
    from stripe_sync.uplift_report import CONFIDENT_MIN_GROUP, uplift_math
    small = uplift_math(7, 7, 3, 1, 49.0)
    assert small["incremental_usd"] is not None
    assert small["confident"] is False
    big = uplift_math(CONFIDENT_MIN_GROUP, CONFIDENT_MIN_GROUP, 12, 6, 49.0)
    assert big["confident"] is True


def test_invert_goal_counts_staying_not_leaving():
    """K4: цель - НЕ отменить. Меньше отмен в target = положительный эффект."""
    from stripe_sync.uplift_report import uplift_math
    r = uplift_math(100, 100, 10, 25, 50.0, invert=True)
    assert r["conv_target"] == 0.9 and r["conv_control"] == 0.75
    assert r["incremental_usd"] == 750.0


def test_site_plans_seed_the_ladder_before_billing():
    """Пока Stripe не подключён, лестницу тарифов даёт страница цен клиента -
    иначе «недобор апгрейдов» и экономика подарков молчат неделями."""
    from stripe_sync.plans_sync import site_plan_rows
    rows = site_plan_rows(
        [{"name": "Free", "price_usd": 0, "units_included": None},
         {"name": "Pro", "price_usd": 29, "units_included": 500},
         {"name": "Scale", "price_usd": 99, "units_included": None}],
        monthly_units=100, tenant="t", now="2026-08-06 00:00:00.000")
    assert [r[1] for r in rows] == ["site:pro", "site:scale"]   # бесплатный не в счёт
    assert [r[3] for r in rows] == [29.0, 99.0]
    assert rows[0][2] == 500      # лимит со страницы тарифов
    assert rows[1][2] == 100      # не указан - берём ответ клиента
