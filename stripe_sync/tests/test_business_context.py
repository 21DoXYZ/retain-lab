"""Генерик-промпт запрещён: каждый генератор обязан нести бизнес-контекст.

Этот тест - страховка методологии §8 на уровне архитектуры: убрать контекст
из промпта можно только сломав сборку, а не молча.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import business_context as bc  # noqa: E402


def test_every_generator_carries_the_business_context():
    """Все модули с LLM-генерацией ссылаются на слой контекста."""
    import ai_analyst
    import ai_compose
    import cancel_reasons
    for mod in (ai_compose, ai_analyst, cancel_reasons):
        src = inspect.getsource(mod)
        assert "business_context" in src, f"{mod.__name__} потерял контекст"


def test_context_block_marks_claimed_vs_measured():
    """Модель обязана видеть разницу: самоописание бизнеса и его данные."""
    block = bc.context_block({"claimed": {"product_name": "acme"},
                              "measured": {"cancel_reasons": [
                                  {"reason": "price", "count": 7}]}})
    assert "CLAIMED" in block and "MEASURED" in block
    assert "acme" in block and "price" in block
    # без данных - честная пометка, а не молчаливая дыра
    empty = bc.context_block({"claimed": {"product_name": "acme"},
                              "measured": {}})
    assert "no measured data yet" in empty


class FakeCH:
    def __init__(self, rows_by_frag):
        self.rows = rows_by_frag

    def query(self, sql, parameters=None):
        class R:
            def __init__(self, rows):
                self.result_rows = rows
        for frag, rows in self.rows.items():
            if frag in sql:
                return R(rows)
        return R([])


def test_measured_layer_assembles_from_live_tables():
    ch = FakeCH({
        "tenant_plans_current": [["price_x", 39.0, 6000]],
        "cancel_reasons": [["price", 7], ["quality", 2]],
        "user_actions": [["MONITOR", 30], ["DUNNING", 2]],
        "uplift_reports": [["K3_payment_recovery", 0.4, 0.1, 60, 55]],
    })
    ctx = bc.business_context(ch, "t", answers={"product_name": "acme"})
    m = ctx["measured"]
    assert m["stripe_plans"][0]["usd_month"] == 39.0
    assert m["cancel_reasons"][0] == {"reason": "price", "count": 7}
    assert m["stage_counts"]["DUNNING"] == 2
    assert m["campaign_uplift"][0]["uplift_pp"] == 30.0


def test_no_db_falls_back_to_claimed_only():
    """Тесты и dry-run живут без базы: контекст остаётся claimed-слоем."""
    ctx = bc.business_context(None, "t", answers={"product_name": "acme"})
    assert ctx["claimed"]["product_name"] == "acme"
    assert ctx["measured"] == {}
