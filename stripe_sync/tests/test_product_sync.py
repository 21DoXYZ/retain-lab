"""product_sync: продуктовые события экспорта + измеренная экономика."""

from product_sync import (credit_event, job_event, plan_change_event,
                          subscription_event)


def test_done_job_becomes_value_action():
    """Скоринг ждёт generation_completed - джоб обязан прийти именно им."""
    e = job_event({"id": "j1", "user_id": "u1", "type": "asset_image",
                   "status": "done", "provider": "gpt_images",
                   "credits_cost": 4, "provider_cost_micro_usd": 170000,
                   "created_at": "2026-06-10T12:35:28.5+00:00",
                   "finished_at": "2026-06-10T13:18:37.2+00:00"}, "t")
    assert e[2] == "generation_completed" and e[4] == "u1" and e[7] == "product"
    assert e[3].startswith("2026-06-10 13:18:37")      # ts = момент завершения
    assert '"provider_cost_micro_usd":170000' in e[9]


def test_running_job_is_skipped_until_finished():
    """Бегущий джоб не событие: его догонит люфт следующего прогона."""
    assert job_event({"id": "j2", "status": "running"}, "t") is None
    e = job_event({"id": "j3", "status": "failed",
                   "created_at": "2026-06-10T12:00:00+00:00"}, "t")
    assert e[2] == "generation_failed"


def test_credit_sign_splits_spend_and_grant():
    spend = credit_event({"id": "c1", "user_id": "u1", "amount": -4,
                          "reason": "generation", "balance_after": 96,
                          "created_at": "2026-06-10T12:32:20+00:00"}, "t")
    grant = credit_event({"id": "c2", "user_id": "u1", "amount": 100,
                          "reason": "purchase",
                          "created_at": "2026-06-11T00:00:00+00:00"}, "t")
    assert spend[2] == "credit_spend" and grant[2] == "credit_grant"
    assert credit_event({"id": "c3", "amount": 0}, "t") is None


def test_subscription_carries_the_missing_identity_link():
    """user_id ↔ stripe_customer_id: у части юзеров связка есть только тут."""
    e = subscription_event({"id": "s1", "user_id": "u1",
                            "stripe_customer_id": "cus_1", "plan": "creator",
                            "status": "active",
                            "created_at": "2026-08-01T04:19:14+00:00"}, "t")
    assert e[4] == "u1" and e[8] == "cus_1" and e[2] == "subscription_link"
    assert subscription_event({"id": "s2", "user_id": "u1"}, "t") is None


def test_plan_change_event():
    e = plan_change_event({"id": "p1", "user_id": "u1", "old_plan": "trial",
                           "new_plan": "creator",
                           "changed_at": "2026-07-31T11:29:36+00:00"}, "t")
    assert e[2] == "plan_change" and '"new_plan":"creator"' in e[9]


def test_measured_unit_cost_beats_owner_estimate():
    """§9: владелец ОЦЕНИВАЕТ, product_sync ИЗМЕРЯЕТ - измеренное главнее."""
    from economics import unit_cost
    cost, basis = unit_cost({"unit_cost_usd": "0.02",
                             "measured_unit_cost_usd": 0.0059}, 0.0066)
    assert (cost, basis) == (0.0059, "measured")


def test_measured_margin_beats_claimed():
    from economics import gross_margin
    assert gross_margin({"gross_margin_pct": 80,
                         "measured_margin_pct": 12.5}) == 0.125
    assert gross_margin({"gross_margin_pct": 80}) == 0.8


def test_measured_zero_margin_is_knowledge_not_absence():
    """Ноль по факту - «маржи нет», а не «не знаем»: оценка владельца молчит."""
    from economics import gross_margin
    assert gross_margin({"gross_margin_pct": 80,
                         "measured_margin_pct": 0.0}) == 0.0


def test_with_measured_merges_only_measured_keys():
    from economics import with_measured
    answers = {"gross_margin_pct": 80}
    measured = {"measured_margin_pct": 12.5, "measured_jobs": 4700,
                "measured_at": "2026-08-09 10:00:00"}
    merged = with_measured(answers, measured)
    assert merged["measured_margin_pct"] == 12.5
    assert merged["gross_margin_pct"] == 80           # ответы не потёрты
    assert "measured_at" in merged                     # служебное тоже measured_*
    assert with_measured(answers, {}) == answers       # нет замера - без изменений
