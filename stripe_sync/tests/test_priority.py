"""Очередь на дневной бюджет писем: горячие по скору уходят первыми."""

from campaign_tick import by_priority, priority_score


def test_score_monotonic():
    assert priority_score(3, 0.5, 100) > priority_score(1, 0.5, 100)
    assert priority_score(1, 0.9, 0) > priority_score(1, 0.1, 0)
    assert priority_score(0, 0, 0) == 0.0


def test_score_ltv_capped():
    """Гигантский LTV-выброс не должен перебивать сигналы намерения."""
    assert priority_score(0, 0, 10_000_000) <= priority_score(2, 0, 0)


def test_by_priority_orders_hot_first():
    enrolled = {"cold": {"status": "active"}, "hot": {"status": "active"},
                "warm": {"status": "active"}}
    prio = {"hot": 25.0, "warm": 5.0}
    order = [i for i, _r in by_priority(enrolled, prio)]
    assert order == ["hot", "warm", "cold"]


def test_by_priority_without_scores_keeps_everyone():
    enrolled = {"a": {}, "b": {}}
    assert {i for i, _r in by_priority(enrolled, {})} == {"a", "b"}
