"""Методологический гейт живой выдачи: правила, которые раньше жили только
в превью, теперь останавливают реальные деньги. Каждый тест - одно правило."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import offer_gate as og  # noqa: E402


class FakeCH:
    """Отвечает по фрагменту SQL; по умолчанию - пустая история."""

    def __init__(self, issued=None, reasons=None, uplift=None):
        self.issued = issued or []
        self.reasons = reasons or []
        self.uplift = uplift or []

    def query(self, sql, parameters=None):
        class R:
            def __init__(self, rows):
                self.result_rows = rows
        if "offers_issued" in sql:
            return R(self.issued)
        if "cancel_reasons" in sql:
            return R(self.reasons)
        if "uplift_reports" in sql:
            return R(self.uplift)
        raise AssertionError("неожиданный запрос: " + sql[:80])


def _user(**kw):
    base = {"identity_id": "id1", "client_user_id": "u1",
            "stripe_customer_id": "cus_1", "sub_status": "active",
            "stage": "SAVE", "mrr": 99.0, "p_convert": 1.0, "p_churn": 0.6}
    base.update(kw)
    return base


def _offer(**kw):
    base = {"offer_id": "O_credit", "executor": "balance_credit",
            "monetary": True, "cost_estimate": 15.0, "params": {},
            "role": "save"}
    base.update(kw)
    return base


def _answers(monkeypatch, margin_pct=70):
    monkeypatch.setattr(og, "load_tenant_channels", lambda t: {
        "onboarding_answers": {"gross_margin_pct": margin_pct}})


# ── candidate_of: живые деньги отдельно от недополученной выручки ────────────

def test_candidate_cash_split():
    c = og.candidate_of({"offer_id": "a", "executor": "balance_credit",
                         "cost_estimate": 10.0, "params": {}}, 0.1)
    assert c["cash"] == 10.0 and c["revenue"] == 0.0
    c = og.candidate_of({"offer_id": "b", "executor": "stripe_coupon",
                         "cost_estimate": 20.0, "params": {}}, 0.1)
    assert c["cash"] == 0.0 and c["revenue"] == 20.0
    # скидка на докупку через вебхук клиента - тоже не живые деньги
    c = og.candidate_of({"offer_id": "c", "executor": "client_callback",
                         "cost_estimate": 12.0,
                         "params": {"command": "topup_discount"}}, 0.1)
    assert c["cash"] == 0.0


# ── measured_uplift: замер заменяет прайор только когда достоверен ───────────

def test_measured_uplift_confidence_gate():
    ch = FakeCH(uplift=[[0.30, 0.10, 50, 40]])
    m = og.measured_uplift(ch, "t", "K4_save")
    assert m["confident"] and abs(m["uplift"] - 0.2) < 1e-9
    ch = FakeCH(uplift=[[0.30, 0.10, 12, 8]])       # групп мало
    assert og.measured_uplift(ch, "t", "K4_save")["confident"] is False
    assert og.measured_uplift(FakeCH(), "t", "K4_save") is None


def test_measured_uplift_feeds_the_decision(monkeypatch):
    """Петля замкнута: достоверный замер входит в EV вместо прайора."""
    _answers(monkeypatch)
    ctx_no = og.build_context(FakeCH(), "t", _user(), "K4_save")
    assert ctx_no["measured"] is None
    ctx_yes = og.build_context(FakeCH(uplift=[[0.5, 0.1, 60, 55]]),
                               "t", _user(), "K4_save")
    assert ctx_yes["measured"]["confident"] and ctx_yes["measured"]["uplift"] == 0.4


# ── спящие собаки: низкий риск + деньги = молчим ─────────────────────────────

def test_sleeping_dog_blocks_monetary_gift(monkeypatch):
    _answers(monkeypatch)
    ok, reason = og.gate(FakeCH(), "t", _offer(), _user(p_churn=0.05), "K4_save")
    assert not ok and "would_stay_anyway" in reason


def test_high_risk_user_passes_with_cheap_lever(monkeypatch):
    """Пауза (время, не деньги) у рискового юзера проходит; а вот кэш-подарок
    с прайор-аплифтом 3% гейт честно отбивает - он в минусе (см. тест EV)."""
    _answers(monkeypatch)
    ok, reason = og.gate(FakeCH(), "t",
                         _offer(offer_id="O_pause", executor="pause_collection",
                                monetary=False, cost_estimate=0.0),
                         _user(p_churn=0.7), "K4_save")
    assert ok, reason


# ── EV: подарок дороже спасаемого - отказ ────────────────────────────────────

def test_negative_ev_is_refused(monkeypatch):
    _answers(monkeypatch, margin_pct=70)
    # маржа $9 * 70% на дешёвом тарифе, а подарок - $200 живых денег
    ok, reason = og.gate(FakeCH(), "t", _offer(cost_estimate=200.0),
                         _user(mrr=9.0, p_churn=0.7), "K4_save")
    assert not ok
    assert "negative_value" in reason or "stake_too_small" in reason


# ── кэп попыток: пожизненный счётчик, не 14 дней ─────────────────────────────

def test_lifetime_attempts_cap(monkeypatch):
    _answers(monkeypatch)
    issued = [[f"O{i}", "balance_credit", "{}", 1, 10.0] for i in range(4)]
    ok, reason = og.gate(FakeCH(issued=issued), "t", _offer(),
                         _user(p_churn=0.7), "K4_save")
    assert not ok and "enough_attempts" in reason


# ── лестница: дешёвая неиспробованная ступень в каталоге блокирует дорогую ───

def test_ladder_prefers_cheaper_untried_peer(monkeypatch):
    _answers(monkeypatch)
    cheap_peer = _offer(offer_id="O_pause", executor="pause_collection",
                        monetary=False, cost_estimate=0.0)
    ok, reason = og.gate(FakeCH(), "t", _offer(), _user(p_churn=0.7),
                         "K4_save", catalog_offers=[cheap_peer, _offer()])
    assert not ok and "cheaper_rung_first" in reason
    # ступень испробована И у кампании есть ДОСТОВЕРНЫЙ замер эффекта -
    # дорогая ступень открывается: измеренный аплифт делает её плюсовой
    issued = [["O_pause", "pause_collection", "{}", 0, 0.0]]
    ch = FakeCH(issued=issued, uplift=[[0.5, 0.1, 60, 55]])
    ok, reason = og.gate(ch, "t", _offer(cost_estimate=5.0),
                         _user(p_churn=0.7), "K4_save",
                         catalog_offers=[cheap_peer, _offer()])
    assert ok, reason


# ── причина ухода: качество/саппорт не лечатся деньгами ──────────────────────

def test_reason_quality_refuses_money(monkeypatch):
    _answers(monkeypatch)
    ch = FakeCH(reasons=[["quality"]])
    ok, reason = og.gate(ch, "t", _offer(cost_estimate=5.0),
                         _user(p_churn=0.7), "K4_save")
    assert not ok and "reason" in reason


def test_missing_context_does_not_block(monkeypatch):
    """Нет ответов онбординга, нет скора - гейт не имеет права молча душить
    выдачу: неизвестный контекст = правило не применяется."""
    monkeypatch.setattr(og, "load_tenant_channels", lambda t: {})
    ok, reason = og.gate(FakeCH(), "t", _offer(cost_estimate=5.0),
                         _user(p_churn=None, stage="ACTIVATE"), "K1_activation")
    assert ok, reason


def test_trial_user_zero_churn_is_not_a_sleeping_dog(monkeypatch):
    """У триала p_churn = 0 по определению («нечего отменять») - это не
    спящая собака, иначе глушились бы все активационные подарки."""
    _answers(monkeypatch)
    ok, reason = og.gate(
        FakeCH(uplift=[[0.5, 0.1, 60, 55]]), "t",
        _offer(offer_id="O_credits", role="activation", cost_estimate=3.0),
        _user(sub_status="trialing", stage="ACTIVATE", p_churn=0.0,
              p_convert=0.4),
        "K1_activation")
    assert ok, reason
