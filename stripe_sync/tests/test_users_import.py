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
    assert report["parsed"] == 2 and report["imported"] == 2 and report["skipped"] == 0
    assert report["with_email"] == 2
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


def test_preview_shows_what_we_understood_before_loading():
    """Клиент не обязан верить на слово: до загрузки показываем разбор файла."""
    from users_import import preview
    rows = parse_rows("User ID;E-Mail;Registration Date\n"
                      "u_1;a@b.co;2026-01-15\n"
                      ";;\n"
                      "u_2;bad-email;2026-02-15\n")
    p = preview(rows)
    assert p["mapping"]["id"] == "User ID" and p["mapping"]["email"] == "E-Mail"
    assert p["rows"] == 3 and p["usable"] == 2 and p["unusable"] == 1
    assert p["sample"][0]["created_at"].startswith("2026-01-15")


def test_import_reports_how_many_people_are_reachable():
    """Загрузили 200 человек без почты - база наполнится, а письма не уйдут
    никому. Отчёт обязан сказать это прямо, а не радовать числом строк."""
    rows = parse_rows("id,email\nu_1,a@b.co\nu_2,\nu_3,\n")
    _events, report = to_events(rows, "t")
    assert report["imported"] == 3
    assert report["with_email"] == 1 and report["without_email"] == 2


def test_email_column_aliases_are_wide():
    from users_import import preview
    for header in ("User Email", "e_mail", "primary_email", "contact_email", "Адрес"):
        rows = parse_rows(f"id,{header}\nu_1,a@b.co\n")
        assert preview(rows)["with_email"] == 1, header


def test_export_connector_maps_rows_and_drops_internal(monkeypatch):
    """Экспорт продукта: is_internal - вон, stripe_customer_id и план - с собой."""
    import connectors

    page = {"data": {"rows": [
        {"id": "u1", "email": "A@B.co", "stripe_customer_id": "cus_1",
         "created_at": "2026-06-01T10:00:00Z", "plan": "pro", "status": "active",
         "credits_balance": 500, "is_internal": False},
        {"id": "svc", "email": "ops@team.co", "is_internal": True},
    ], "cursor": ""}}
    monkeypatch.setattr(connectors, "_get", lambda url, headers: page)

    users = connectors.fetch_users({"kind": "export", "url": "https://x/api", "key": "k"})
    assert len(users) == 1
    assert users[0]["id"] == "u1" and users[0]["email"] == "a@b.co"
    assert users[0]["stripe_customer_id"] == "cus_1"
    assert users[0]["_meta"]["plan"] == "pro"
    assert users[0]["_meta"]["credits_balance"] == 500


def test_export_connector_stops_on_repeated_cursor(monkeypatch):
    """Кривой курсор, который не двигается, не должен зациклить прогон."""
    import connectors

    calls = []
    def fake_get(url, headers):
        calls.append(url)
        return {"data": {"rows": [{"id": f"u{len(calls)}", "email": "a@b.co"}] * 1000,
                         "cursor": "same"}}
    monkeypatch.setattr(connectors, "_get", fake_get)
    connectors.export_users("https://x/api", "k")
    assert len(calls) == 2          # первая страница + одна по курсору, дальше стоп


def test_to_events_carries_connector_meta():
    """План/статус/кредиты из экспорта доезжают до события - их ждёт скоринг."""
    rows = [{"id": "u1", "email": "a@b.co", "created_at": "2026-06-01",
             "stripe_customer_id": "cus_1", "_meta": {"plan": "pro"}}]
    events, _report = to_events(rows, "t")
    assert events[0][8] == "cus_1"
    assert '"plan":"pro"' in events[0][9]


def test_to_events_meta_empty_for_csv_rows():
    rows = parse_rows("id,email\nu_1,a@b.co\n")
    events, _ = to_events(rows, "t")
    assert events[0][9] == ""
