"""Чистые юнит-тесты компилятора сегментов (BEZ БД).

Проверяем, что JSON-дерево условий превращается в безопасный ClickHouse-WHERE:
  • значения уходят ТОЛЬКО параметрами {name:Type} (инъекция невозможна);
  • имена полей/операторов берутся только из реестра FIELDS;
  • группы И/ИЛИ, вложенность ≤2, not_segment, event-подзапрос;
  • отказ с человекочитаемой причиной на кривом вводе.

Соответствует Step 1 плана W4-T1 (кейсы а–е).
"""
from __future__ import annotations

import re

import pytest

from api.segment_compiler import compile_definition, base_query
from api import segment_fields as sf


# ── helpers ──────────────────────────────────────────────────────────────────
def _placeholder_names(where: str) -> set[str]:
    """Имена всех {name:Type}-плейсхолдеров в строке WHERE."""
    return set(re.findall(r"\{(\w+):", where))


def _no_raw_values(where: str) -> bool:
    """В WHERE не должно быть «голых» строковых литералов пользователя.

    Разрешены только имена колонок (f./u./ch. …), операторы, ключевые слова и
    плейсхолдеры. Грубая эвристика: одинарных кавычек с пользовательским текстом
    быть не должно, кроме фиксированных литералов реестра (account_type, TRUTHY).
    """
    return "'; DROP" not in where and "--" not in where


# ── (а) простое num/eq → WHERE с параметром ─────────────────────────────────
def test_simple_num_eq():
    where, params, joins = compile_definition(
        {"all": [{"field": "dep_count", "op": "eq", "value": 1}]})
    assert "f.dep_count" in where
    names = _placeholder_names(where)
    assert len(names) == 1
    (name,) = names
    assert params[name] == 1
    assert joins == set()          # dep_count — чистое поле player_features, джойнов нет
    assert "{" + name + ":Float64}" in where


def test_num_operators_gt_lt_ne():
    for op, sym in [("gt", ">"), ("lt", "<"), ("ne", "!=")]:
        where, params, _ = compile_definition(
            {"all": [{"field": "turnover", "op": op, "value": 100}]})
        assert f"f.turnover {sym}" in where
        assert list(params.values()) == [100]


# ── (б) all + any вложенность ────────────────────────────────────────────────
def test_all_any_nesting():
    where, params, joins = compile_definition({"all": [
        {"field": "dep_count", "op": "eq", "value": 1},
        {"any": [
            {"field": "lifecycle", "op": "in", "value": ["cooling", "at_risk"]},
            {"field": "recency_days", "op": "between", "value": [8, 30]},
        ]},
    ]})
    assert " AND " in where          # верхняя группа — И
    assert " OR " in where           # вложенная — ИЛИ
    assert "f.lifecycle" in where and "f.recency_days" in where
    # значения ушли параметрами
    assert 1 in params.values()
    assert ["cooling", "at_risk"] in params.values()
    assert 8 in params.values() and 30 in params.values()


def test_depth_two_ok_depth_three_rejected():
    # 2 уровня — ок
    compile_definition({"all": [{"any": [
        {"field": "dep_count", "op": "gt", "value": 0}]}]})
    # 3 уровня — отказ
    with pytest.raises(ValueError):
        compile_definition({"all": [{"any": [{"all": [
            {"field": "dep_count", "op": "gt", "value": 0}]}]}]})


# ── (в) between ──────────────────────────────────────────────────────────────
def test_between():
    where, params, _ = compile_definition(
        {"all": [{"field": "recency_days", "op": "between", "value": [8, 30]}]})
    assert "BETWEEN" in where.upper()
    assert sorted(params.values()) == [8, 30]
    assert len(_placeholder_names(where)) == 2


def test_between_bad_value_rejected():
    with pytest.raises(ValueError):
        compile_definition(
            {"all": [{"field": "recency_days", "op": "between", "value": [8]}]})


# ── (г) not_segment ──────────────────────────────────────────────────────────
def test_not_segment():
    where, params, _ = compile_definition(
        {"all": [{"not_segment": "safety_restricted"}]})
    assert "NOT IN" in where.upper()
    assert "segment_members" in where
    assert "safety_restricted" in params.values()


def test_not_segment_bad_sysname_rejected():
    with pytest.raises(ValueError):
        compile_definition({"all": [{"not_segment": "Bad Name!"}]})


# ── (д) event-подзапрос ──────────────────────────────────────────────────────
def test_event_subquery():
    where, params, _ = compile_definition({"all": [
        {"event": {"type": "deposit", "status": "completed",
                   "within_days": 30, "op": "gte", "count": 1}}]})
    assert "money_transactions" in where
    assert "GROUP BY casino_player_id" in where
    assert "HAVING" in where.upper()
    assert 30 in params.values()      # окно
    assert 1 in params.values()       # порог count
    assert "completed" in params.values()


def test_event_unknown_type_rejected():
    with pytest.raises(ValueError):
        compile_definition({"all": [{"event": {"type": "login", "within_days": 7}}]})


def test_event_bet_uses_game_transactions():
    where, _, _ = compile_definition({"all": [
        {"event": {"type": "bet", "within_days": 7}}]})
    assert "game_transactions" in where


# ── (е) отказы: неизвестное поле / оператор не для типа ──────────────────────
def test_unknown_field_rejected():
    with pytest.raises(ValueError):
        compile_definition({"all": [{"field": "nope_field", "op": "eq", "value": 1}]})


def test_bad_operator_for_type_rejected():
    # для num нет оператора 'in'
    with pytest.raises(ValueError):
        compile_definition({"all": [{"field": "dep_count", "op": "in", "value": [1, 2]}]})
    # для enum нет 'gt'
    with pytest.raises(ValueError):
        compile_definition({"all": [{"field": "lifecycle", "op": "gt", "value": "x"}]})


def test_unavailable_field_rejected():
    # найдём любое available=False поле в реестре и убедимся, что оно отклоняется
    unavail = [k for k, v in sf.FIELDS.items() if not v.available]
    if unavail:
        with pytest.raises(ValueError):
            compile_definition({"all": [{"field": unavail[0], "op": "eq", "value": 1}]})


# ── enum / flag / top_pct / ML-джойны ────────────────────────────────────────
def test_enum_in():
    where, params, _ = compile_definition(
        {"all": [{"field": "lifecycle", "op": "in", "value": ["active", "cooling"]}]})
    assert "f.lifecycle IN" in where
    assert ["active", "cooling"] in params.values()
    assert "Array(String)" in where


def test_flag_is():
    where, params, _ = compile_definition(
        {"all": [{"field": "phone_verified", "op": "is", "value": True}]})
    # флаг компилируется литералом (без параметра) — значение не пользовательское
    assert "phone_verified" in where
    assert params == {}


def test_top_pct():
    where, params, _ = compile_definition(
        {"all": [{"field": "turnover", "op": "top_pct", "value": 10}]})
    assert "quantile" in where
    assert "player_features" in where
    # 10% сверху → quantile(0.9)
    assert any(abs(float(v) - 0.9) < 1e-9 for v in params.values())


def test_ml_field_adds_join_and_guard():
    where, params, joins = compile_definition(
        {"all": [{"field": "p_churn", "op": "gt", "value": 0.5}]})
    assert "ch" in joins                       # джойн player_churn_ml добавлен
    assert "ch.casino_player_id != 0" in where  # NULL-семантика: нет строки → не матч
    assert "ch.p_churn >" in where


def test_base_query_assembles_joins():
    where, params, joins = compile_definition(
        {"all": [{"field": "p_churn", "op": "gt", "value": 0.5},
                 {"field": "pred_ltv_d90", "op": "gt", "value": 1000}]})
    sql = base_query(where, joins)
    assert sql.startswith("SELECT f.casino_player_id FROM player_features")
    assert "account_type = 'normal'" in sql
    assert "player_churn_ml" in sql and "player_ltv" in sql


# ── общая безопасность ───────────────────────────────────────────────────────
def test_injection_attempt_goes_to_param():
    evil = "1); DROP TABLE users;--"
    where, params, _ = compile_definition(
        {"all": [{"field": "affiliate_code", "op": "eq", "value": evil}]})
    assert evil in params.values()             # ушло параметром
    assert "DROP TABLE" not in where            # не в теле запроса
    assert _no_raw_values(where)


def test_empty_or_bad_top_level_rejected():
    with pytest.raises(ValueError):
        compile_definition({"field": "dep_count", "op": "eq", "value": 1})  # не группа
    with pytest.raises(ValueError):
        compile_definition("not a dict")
