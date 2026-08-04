"""Юнит-тесты каталога полей сегментов (W4-T0): сверка с 158 фильтрами Василия.

Проверяем инварианты реестра после домержа `tools/filter_catalog_map.json`:
  (а) объединение всех catalog_n == {1..158} — без пропусков и дублей
      (один номер — ровно у одного поля);
  (б) каждое available=True поле имеет непустой sql (компилятор сможет его собрать);
  (в) каждое available=False поле имеет заполненный needs (UI покажет причину/бейдж).

БЕЗ БД — чистая проверка структуры реестра (реальный preview добавленных полей
прогоняется отдельно curl-ом, см. отчёт W4-T0).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api import segment_fields as sf


CATALOG_MAP = Path(__file__).resolve().parent.parent / 'tools' / 'filter_catalog_map.json'


def _nums(catalog_n) -> list[int]:
    """catalog_n (int | tuple | None) → плоский список номеров."""
    if catalog_n is None:
        return []
    if isinstance(catalog_n, (tuple, list)):
        return list(catalog_n)
    return [catalog_n]


# ── (а) полное покрытие 1..158 без пропусков и дублей ────────────────────────
def test_catalog_covers_1_to_158_no_gaps():
    seen: set[int] = set()
    for field in sf.FIELDS.values():
        for n in _nums(field.catalog_n):
            seen.add(n)
    assert seen == set(range(1, 159)), (
        f"пропуски: {sorted(set(range(1, 159)) - seen)}; "
        f"лишние: {sorted(seen - set(range(1, 159)))}"
    )


def test_no_catalog_number_owned_twice():
    owners: dict[int, list[str]] = {}
    for key, field in sf.FIELDS.items():
        for n in _nums(field.catalog_n):
            owners.setdefault(n, []).append(key)
    dupes = {n: ks for n, ks in owners.items() if len(ks) > 1}
    assert dupes == {}, f"номер закреплён за >1 полем: {dupes}"


def test_catalog_numbers_are_valid_range():
    for key, field in sf.FIELDS.items():
        for n in _nums(field.catalog_n):
            assert isinstance(n, int) and 1 <= n <= 158, f"{key}: некорректный № {n!r}"


# ── (б) available=True → есть sql ────────────────────────────────────────────
def test_available_fields_have_sql():
    missing = [k for k, f in sf.FIELDS.items() if f.available and not f.sql]
    assert missing == [], f"available без sql: {missing}"


# ── (в) available=False → заполнен needs ─────────────────────────────────────
def test_unavailable_fields_declare_needs():
    missing = [k for k, f in sf.FIELDS.items() if not f.available and not f.needs]
    assert missing == [], f"available=False без needs: {missing}"


def test_stub_fields_have_no_sql():
    # Все заглушки (available=False) держат sql=None — чистота реестра; компилятор
    # их и так отклоняет по флагу available, но sql-мусора быть не должно.
    dirty = [k for k, f in sf.FIELDS.items() if not f.available and f.sql]
    assert dirty == [], f"заглушки не должны нести sql: {dirty}"


# ── трассировка к номерам реального map-файла (смысловая сверка) ──────────────
def test_every_map_number_present_in_registry():
    catalog = json.loads(CATALOG_MAP.read_text(encoding='utf-8'))
    map_numbers = {row['n'] for row in catalog}
    registry_numbers: set[int] = set()
    for field in sf.FIELDS.values():
        registry_numbers.update(_nums(field.catalog_n))
    assert map_numbers == registry_numbers == set(range(1, 159))


def test_needs_values_have_ui_labels():
    # У каждого использованного needs есть человекочитаемый бейдж в NEEDS_LABELS.
    used = {f.needs for f in sf.FIELDS.values() if not f.available and f.needs}
    missing = sorted(used - set(sf.NEEDS_LABELS))
    assert missing == [], f"needs без подписи в NEEDS_LABELS: {missing}"


def test_sections_have_titles():
    used_sections = {f.section for f in sf.FIELDS.values()}
    missing = sorted(used_sections - set(sf.SECTIONS))
    assert missing == [], f"разделы без подписи в SECTIONS: {missing}"


# ── регрессия: v1-поля сохранили ключи/типы/sql (W4-T1 их протестировал) ──────
@pytest.mark.parametrize('key,expected_sql', [
    ('dep_count', 'f.dep_count'),
    ('p_churn', 'ch.p_churn'),
    ('lifecycle', 'f.lifecycle'),
    ('telegram_id_present', "(u.telegram_id != '' AND u.telegram_id != '0')"),
])
def test_v1_fields_sql_unchanged(key, expected_sql):
    assert sf.FIELDS[key].sql == expected_sql


def test_v1_fields_got_catalog_n():
    # Ключевые v1-поля получили трассировку к номеру Василия.
    assert sf.FIELDS['dep_count'].catalog_n == 36
    assert sf.FIELDS['vip_level'].catalog_n == (16, 115)
    assert sf.FIELDS['lifecycle'].catalog_n == (116, 117)
    assert sf.FIELDS['p_churn'].catalog_n == 126
