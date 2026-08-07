"""Разовая загрузка базы юзеров клиента: разбор выгрузки без его кода."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from users_import import parse_rows, to_events  # noqa: E402


def test_csv_with_arbitrary_headers():
    """Колонки называют как угодно - распознаём сами, иначе клиенту пришлось бы
    переделывать выгрузку под нас."""
    csv_text = (
        "User ID;E-Mail;Registration Date;Stripe ID\n"
        "u_1;Ann@Example.COM;2026-01-15;cus_1\n"
        "u_2;bob@example.com;15.02.2026;\n"
    )
    rows = parse_rows(csv_text)
    events, report = to_events(rows, "t")
    assert report == {"parsed": 2, "imported": 2, "skipped": 0}
    assert events[0][4] == "u_1" and events[0][6] == "ann@example.com"
    assert events[0][3].startswith("2026-01-15")
    assert events[1][3].startswith("2026-02-15")
    assert events[0][8] == "cus_1"


def test_json_export_and_deduplication():
    rows = parse_rows('{"users": [{"id": "u_1", "email": "a@b.co"}, '
                      '{"id": "u_1", "email": "a@b.co"}, {"email": "c@d.co"}]}')
    events, report = to_events(rows, "t")
    assert report["imported"] == 2 and report["skipped"] == 1


def test_rows_without_id_and_email_are_skipped():
    rows = parse_rows("name,plan\nАнна,pro\n")
    events, report = to_events(rows, "t")
    assert events == [] and report["skipped"] == 1


def test_repeat_import_does_not_double_users():
    """Тот же файл дважды - те же event_id, конвейер схлопнет дубли."""
    rows = parse_rows("id,email\nu_1,a@b.co\n")
    first, _ = to_events(rows, "t")
    second, _ = to_events(rows, "t")
    assert first[0][1] == second[0][1]


def test_broken_email_does_not_break_the_row():
    rows = parse_rows("id,email\nu_1,не-почта\n")
    events, report = to_events(rows, "t")
    assert report["imported"] == 1 and events[0][6] == ""


def test_connector_output_feeds_the_same_pipeline():
    """Любой источник отдаёт один формат - дальше та же загрузка, без развилок."""
    from users_import import to_events
    from_supabase = [
        {"id": "abc-1", "email": "A@B.co", "created_at": "2026-03-01T10:00:00Z",
         "last_seen": "2026-08-01T10:00:00Z"},
        {"id": "abc-2", "email": "", "created_at": "2026-04-01T10:00:00Z", "last_seen": ""},
    ]
    rows, report = to_events(from_supabase, "t")
    assert report["imported"] == 2
    assert rows[0][3].startswith("2026-03-01")
    assert rows[0][6] == "a@b.co"


def test_unknown_source_is_rejected_loudly():
    import pytest
    from connectors import fetch_users
    with pytest.raises(ValueError):
        fetch_users({"kind": "телепатия"})
