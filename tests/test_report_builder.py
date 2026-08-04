"""Юнит-тесты компилятора отчётов (api/report_builder.py).

ЧИСТЫЕ ЮНИТ-ТЕСТЫ: билдер собирает (sql, params) БЕЗ обращения к ClickHouse —
проверяем структуру SQL и валидацию spec, не данные. Кейсы соответствуют
плану W5-T2 Step 1 (а–д) + инварианты исторической корректности.

Запуск:  .venv/bin/python -m pytest tests/test_report_builder.py -q
"""
from __future__ import annotations

import pytest

from api.report_builder import MAX_METRICS, build_report_query, report_uses_state_at
from api import report_fields as rf


PERIOD = {'from': '2026-06-01', 'to': '2026-06-30'}


def _norm(sql: str) -> str:
    """SQL в одну строку со схлопнутыми пробелами — устойчивое сравнение подстрок."""
    return ' '.join(sql.split())


# ── (а) 1 метрика × 1 time-разрез ────────────────────────────────────────────
def test_single_metric_single_time_dim():
    sql, params = build_report_query({
        'metrics': ['deposits_sum'],
        'dims': ['day'],
        'period': PERIOD,
    })
    s = _norm(sql)
    assert 'sumIf(f.amount' in s                       # депозит-агрегат
    assert "toDate(toTimezone(f.created_at,'Europe/Istanbul'))" in s
    assert 'FROM money_transactions' in s
    assert 'GROUP BY' in s
    assert 'ORDER BY' in s
    assert 'LIMIT 10000' in s
    assert 'max_execution_time' in s
    # период — параметрами, не литералами
    assert params['d_from'] == '2026-06-01'
    assert params['d_to'] == '2026-06-30'
    assert '2026-06-01' not in s


# ── (б) порядок разрезов меняет GROUP BY / ORDER BY ──────────────────────────
def test_dim_order_changes_grouping():
    sql1, _ = build_report_query({
        'metrics': ['deposits_sum'], 'dims': ['month', 'vip_level_at'], 'period': PERIOD})
    sql2, _ = build_report_query({
        'metrics': ['deposits_sum'], 'dims': ['vip_level_at', 'month'], 'period': PERIOD})
    o1 = _norm(sql1).split('ORDER BY', 1)[1]
    o2 = _norm(sql2).split('ORDER BY', 1)[1]
    assert o1.index('month') < o1.index('vip_level_at')
    assert o2.index('vip_level_at') < o2.index('month')
    assert _norm(sql1) != _norm(sql2)


# ── (в) state_at-разрез джойнит psd по ДАТЕ СОБЫТИЯ (историческая корректность) ─
def test_state_at_joins_psd_on_event_date():
    sql, _ = build_report_query({
        'metrics': ['deposits_sum'], 'dims': ['vip_level_at'], 'period': PERIOD})
    s = _norm(sql)
    assert 'player_state_daily' in s
    assert 'FINAL' in s
    # join именно по дате события (created_at факта), НЕ по текущей дате
    assert "psd.snap_date = toDate(toTimezone(f.created_at,'Europe/Istanbul'))" in s
    assert 'psd.casino_player_id = f.casino_player_id' in s
    assert 'psd.vip_level' in s
    assert report_uses_state_at(
        {'metrics': ['deposits_sum'], 'dims': ['vip_level_at'], 'period': PERIOD}) is True


# ── (г) фильтр по enum — значения параметрами ────────────────────────────────
def test_filter_enum_is_parameterized():
    sql, params = build_report_query({
        'metrics': ['deposits_sum'], 'dims': ['country'], 'period': PERIOD,
        'filters': [{'dim': 'country', 'op': 'in', 'value': ['TR', 'AZ']}],
    })
    s = _norm(sql)
    assert 'Array(String)' in s
    assert ' IN {' in s
    assert ['TR', 'AZ'] in list(params.values())
    # значения фильтра не должны попадать в текст SQL
    assert "'TR'" not in s and "'AZ'" not in s


def test_filter_not_in_and_numeric_dim_typed():
    sql, params = build_report_query({
        'metrics': ['deposits_sum'], 'dims': ['vip_level_at'], 'period': PERIOD,
        'filters': [{'dim': 'vip_level_at', 'op': 'in', 'value': [3, 4, 5]}],
    })
    s = _norm(sql)
    assert 'Array(Int64)' in s
    assert [3, 4, 5] in list(params.values())

    sql2, _ = build_report_query({
        'metrics': ['deposits_sum'], 'dims': ['country'], 'period': PERIOD,
        'filters': [{'dim': 'country', 'op': 'not_in', 'value': ['XX']}],
    })
    assert 'NOT IN {' in _norm(sql2)


# ── (д) отказы валидации ─────────────────────────────────────────────────────
def test_reject_unknown_metric():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['nonsense'], 'dims': [], 'period': PERIOD})


def test_reject_unknown_dim():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum'], 'dims': ['nope'], 'period': PERIOD})


def test_reject_four_dims():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum'],
                            'dims': ['day', 'country', 'currency', 'account_type'],
                            'period': PERIOD})


def test_reject_period_over_366_days():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum'], 'dims': [],
                            'period': {'from': '2025-01-01', 'to': '2026-06-30'}})


def test_reject_missing_period():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum'], 'dims': []})


def test_reject_no_metrics():
    with pytest.raises(ValueError):
        build_report_query({'metrics': [], 'dims': ['day'], 'period': PERIOD})


def test_reject_too_many_metrics():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum'] * (MAX_METRICS + 1),
                            'dims': [], 'period': PERIOD})


def test_reject_empty_filter_value():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum'], 'dims': ['country'], 'period': PERIOD,
                            'filters': [{'dim': 'country', 'op': 'in', 'value': []}]})


def test_reject_bad_filter_op():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum'], 'dims': ['country'], 'period': PERIOD,
                            'filters': [{'dim': 'country', 'op': 'like', 'value': ['TR']}]})


def test_reject_bad_date_format():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum'], 'dims': [],
                            'period': {'from': '01-06-2026', 'to': '2026-06-30'}})


# ── ИНВАРИАНТ: state_at к users-метрике неприменим ───────────────────────────
def test_state_at_dim_with_users_metric_raises():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['registrations'], 'dims': ['vip_level_at'],
                            'period': PERIOD})


def test_state_at_dim_with_mixed_users_metric_raises():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['deposits_sum', 'registrations'],
                            'dims': ['vip_level_at'], 'period': PERIOD})


def test_state_at_filter_with_users_metric_raises():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['ftd_count'], 'dims': ['country'], 'period': PERIOD,
                            'filters': [{'dim': 'lifecycle_at', 'op': 'in', 'value': ['active']}]})


# ── применимость разрезов к источникам ───────────────────────────────────────
def test_payment_method_with_game_metric_raises():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['ggr'], 'dims': ['payment_method'], 'period': PERIOD})


def test_hour_with_users_metric_raises():
    with pytest.raises(ValueError):
        build_report_query({'metrics': ['registrations'], 'dims': ['hour'], 'period': PERIOD})


# ── N-source: 3 источника (money+game+users) собираются в цепочку FULL JOIN ──
def test_three_sources_compile():
    sql, _ = build_report_query({'metrics': ['deposits_sum', 'ggr', 'registrations'],
                                 'dims': ['month'], 'period': PERIOD})
    s = _norm(sql)
    assert s.count('FULL OUTER JOIN') == 2
    assert 'coalesce(' in s


# ── multi-source FULL OUTER JOIN ─────────────────────────────────────────────
def test_two_sources_full_join():
    sql, _ = build_report_query({'metrics': ['deposits_sum', 'ggr'],
                                'dims': ['month'], 'period': PERIOD})
    s = _norm(sql)
    assert 'FULL OUTER JOIN' in s
    assert 'coalesce(' in s
    assert 'money_transactions' in s
    assert 'game_transactions' in s


def test_ftd_and_registrations_two_users_partitions_full_join():
    # разные якорные даты (reg_date / ftd_date) → два подзапроса, FULL JOIN
    sql, _ = build_report_query({'metrics': ['registrations', 'ftd_count'],
                                'dims': ['month'], 'period': PERIOD})
    s = _norm(sql)
    assert 'FULL OUTER JOIN' in s
    assert 'f.reg_date' in s
    assert 'f.ftd_date' in s


# ── net_cash — производная одним SQL-выражением ──────────────────────────────
def test_net_cash_is_single_sql_expression():
    sql, _ = build_report_query({'metrics': ['net_cash'], 'dims': [], 'period': PERIOD})
    s = _norm(sql)
    assert 'sumIf(f.amount' in s and 'sumIf(abs(f.amount)' in s
    # без dims — totals-режим (нет GROUP BY)
    assert 'GROUP BY' not in s


# ── реестры непусты и согласованы ────────────────────────────────────────────
def test_registries_shape():
    assert len(rf.METRICS) == 25
    assert len(rf.DIMENSIONS) == 15
    fields = rf.describe_fields()
    assert set(fields.keys()) == {'metrics', 'dimensions'}
    assert all('label' in m for m in fields['metrics'].values())
    assert all('applicable_sources' in d for d in fields['dimensions'].values())
