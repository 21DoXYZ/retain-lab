"""Регресс-тесты по адверсариальному аудиту 2026-08-26 (8 подтверждённых)."""


# ── 1 CRITICAL: measured zero margin -> cash gift ────────────────────────────
def test_zero_margin_stake_is_zero_not_none():
    """margin==0 -> ставка 0.0 (не None): экономические гарды НЕ отключаются."""
    from offer_value import gift_budget, margin_at_stake, rank
    stake = margin_at_stake(0.0, 12.0)      # монетарная маржа 0 x 12 мес
    assert stake == 0.0
    budget = gift_budget(stake, 0.0)
    assert budget == 0.0
    # cash-оффер (balance_credit $20) при нулевой ставке ДОЛЖЕН блокироваться
    cand = [{"offer_id": "c", "executor": "balance_credit", "params": {},
             "cash": 20.0, "revenue": 0.0, "uplift": 0.1}]
    ranked = rank(cand, stake, budget, set(), churn_risk=0.5, base_stay=0.5)
    assert ranked[0]["blocked"] is not None


# ── 2 HIGH: verdict at zero margin ───────────────────────────────────────────
def test_verdict_zero_margin_marks_cash_not_ok():
    from economics import verdict
    v = verdict(cost=17.70, plan_price=99, margin=0.0, cash=17.70)
    assert v["ok"] is False
    assert v["monthly_margin"] == 0        # не полная цена
    v_disc = verdict(cost=20.0, plan_price=99, margin=0.0, cash=0.0)
    assert v_disc["ok"] is False           # скидка при нулевой марже тоже не ок


def test_verdict_none_margin_still_price_basis():
    """None-маржа (не знаем) - по-прежнему считаем по цене, basis='price'."""
    from economics import verdict
    v = verdict(cost=10.0, plan_price=99, margin=None, cash=0.0)
    assert v["basis"] == "price" and v["monthly_margin"] == 99


# ── 3 HIGH: TCPA 10-digit US ─────────────────────────────────────────────────
def test_us_10digit_number_blocked():
    from saas_senders import is_us_number, normalize_phone
    assert is_us_number(normalize_phone("(202) 555-0143")) is True
    assert is_us_number("12025550143") is True         # 11-значный +1
    assert is_us_number("442079460958") is False       # UK - не трогаем
    assert is_us_number("380631112233") is False       # UA


# ── 5 HIGH: spaced/hyphenated placeholders ───────────────────────────────────
def test_spaced_placeholder_rendered_and_caught():
    from saas_senders import render, unresolved
    assert render("Go {{ app_url }}", {"app_url": "https://x"}) == "Go https://x"
    assert render("{{card-update-url}}", {"card_update_url": "https://b"}) == "https://b"
    # неизвестный - остаётся сырым И ловится (fail-closed)
    assert unresolved(render("Hi {{ first_name }}", {"app_url": "x"})) is True
    assert unresolved("clean text") is False


# ── 8 MEDIUM: trigger reentry uses max not min (SQL smoke) ───────────────────
def test_trigger_reentry_uses_max_enrolled_at():
    import inspect
    import trigger_tick
    src = inspect.getsource(trigger_tick.fire)
    assert "max(enrolled_at)" in src
    assert "HAVING max(enrolled_at)" in src        # кулдаун по последнему входу
    assert "FROM retention.campaign_enrollments\n" in src  # базовая, не _current


# ── 4 HIGH: shared cuid merges to one identity ───────────────────────────────
def test_shared_cuid_merges_into_one_identity():
    from stitch import Identity, _merge_shared_cuid
    # A: scus-identity без email, cuid U; B: email-identity с cuid U
    a = Identity("t", "A", stripe_customer_id="cus_1", client_user_ids=["U"],
                 sources=["stripe"])
    b = Identity("t", "B", email_hash="H", email_norm="u@x.co",
                 client_user_ids=["U"], sources=["snippet"])
    merged = _merge_shared_cuid([a, b])
    assert len(merged) == 1
    win = merged[0]
    assert win.email_norm == "u@x.co"          # победил email-identity
    assert win.stripe_customer_id == "cus_1"   # но stripe стянут из A
    assert "U" in win.client_user_ids


def test_distinct_cuids_not_merged():
    from stitch import Identity, _merge_shared_cuid
    a = Identity("t", "A", client_user_ids=["U1"])
    b = Identity("t", "B", client_user_ids=["U2"])
    assert len(_merge_shared_cuid([a, b])) == 2
