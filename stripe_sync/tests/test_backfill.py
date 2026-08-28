"""Backfill: ширина строк обязана совпадать с COLUMNS (иначе вставка кривая).

Регресс на баг 2026-08-28: колонку phone добавили в COLUMNS и в схему, но
забыли в строку клиента fetch_stripe/mock_world - вставка бы падала или
сдвигала поля."""

import os

os.environ.setdefault("TENANT_ID", "t")

from backfill import COLUMNS, mock_world


def test_mock_rows_match_column_widths():
    world = mock_world("t", 3, seed=1)
    for table, rows in world.items():
        for r in rows:
            assert len(r) == len(COLUMNS[table]), (
                f"{table}: строка {len(r)} != COLUMNS {len(COLUMNS[table])}")


def test_customers_carry_phone_slot():
    # phone на своём месте (между name и created_ts): 7-й столбец, индекс 6
    assert COLUMNS["stripe_customers"][6] == "phone"
    row = mock_world("t", 1, seed=1)["stripe_customers"][0]
    assert row[6] == ""   # мок без телефона - пустая строка, не сдвиг
