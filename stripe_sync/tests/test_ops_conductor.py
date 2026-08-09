"""Дирижёр: граф зависимостей и guard свежести входа."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ops_loop as ops  # noqa: E402


def test_dep_graph_edges_are_declared():
    """Ключевые рёбра: скоринг ждёт личности+тарифы, кампании - личности,
    аналитик - свежий uplift."""
    assert set(ops.STAGES["scoring"]["deps"]) == {"stitch", "plans"}
    assert ops.STAGES["campaign_tick"]["deps"] == ["stitch"]
    assert ops.STAGES["uplift_report"]["deps"] == ["campaign_tick"]
    assert ops.STAGES["ai_analyst"]["deps"] == ["uplift_report"]
    # источники данных ни от кого не зависят
    assert ops.STAGES["stitch"]["deps"] == []


def test_order_is_topological():
    """Зависимость исполняется РАНЬШЕ зависящей в одном тике."""
    order = ops._ORDER
    for stage, spec in ops.STAGES.items():
        for dep in spec["deps"]:
            assert order.index(dep) < order.index(stage), (dep, stage)


def test_stale_dep_blocks_when_dependency_missing():
    """Скоринг не бежит, если stitch ни разу успешно не отработал."""
    ages = {"plans": 1.0}                       # stitch отсутствует
    assert ops.stale_dep("scoring", ages) == "stitch"


def test_stale_dep_blocks_when_dependency_expired():
    """Выход зависимости протух (stitch свеж 2ч, а ему 5ч) - тормозим."""
    ages = {"stitch": 5.0, "plans": 1.0}
    assert ops.stale_dep("scoring", ages) == "stitch"


def test_fresh_deps_pass():
    ages = {"stitch": 0.5, "plans": 3.0}
    assert ops.stale_dep("scoring", ages) == ""
    assert ops.stale_dep("campaign_tick", {"stitch": 1.0}) == ""


def test_no_journal_is_fail_open():
    """Журнала нет (первый запуск/нет БД) - свежесть не проверяем, не
    замыкаемся насмерть."""
    assert ops.stale_dep("scoring", {}) == ""


def test_source_stages_never_blocked():
    assert ops.stale_dep("stitch", {}) == ""
    assert ops.stale_dep("plans", {"whatever": 99.0}) == ""


def test_rows_parsed_from_tail():
    assert ops._rows_from_tail("[scoring] tenant=x version=heur-v3 scored=232") == 232
    assert ops._rows_from_tail("[stitch] tenant=x identities=48 unmatched=0") == 48
    assert ops._rows_from_tail("nothing here") == 0
