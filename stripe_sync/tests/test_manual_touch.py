"""Карточка юзера: политика ручных контактов и касаний.

Ручное касание - решение живого человека, но гарды общие с кампаниями:
согласие, супрессии и плейсхолдер-гард проверяет API, транспорт и валидация
адресов - здесь.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import manual_touch as mt  # noqa: E402
from saas_senders import EmailConfig, MessagingConfig  # noqa: E402


def test_contact_addresses_are_validated_per_channel():
    assert mt.validate_contact("sms", "+38 (063) 111-22-33") == ("380631112233", "")
    assert mt.validate_contact("whatsapp", "+971 50 111 2233") == ("971501112233", "")
    assert mt.validate_contact("viber", "hello") == ("", "invalid_phone")
    assert mt.validate_contact("sms", "") == ("", "empty_address")
    assert mt.validate_contact("email", "a@b.c") == ("", "unknown_channel")
    assert mt.validate_contact("push", "x") == ("", "unknown_channel")


def test_telegram_contact_is_a_chat_id_not_a_phone():
    """chat_id выдаёт бот после /start; телефон туда слать бессмысленно."""
    assert mt.validate_contact("telegram", "123456789") == ("123456789", "")
    assert mt.validate_contact("telegram", "-100123456789") == ("-100123456789", "")
    assert mt.validate_contact("telegram", "+971501112233") == \
        ("", "invalid_telegram_chat_id")
    assert mt.validate_contact("telegram", "@username") == \
        ("", "invalid_telegram_chat_id")


def test_manual_send_requires_body_and_email_subject():
    e, m = EmailConfig(dry_run=True), MessagingConfig(dry_run=True)
    assert mt.manual_send("email", "a@b.c", "Subj", "", e, m) == (False, "empty")
    assert mt.manual_send("email", "a@b.c", "", "text", e, m) == \
        (False, "subject_required")
    ok, detail = mt.manual_send("email", "a@b.c", "Subj", "Hello", e, m)
    assert ok and detail == "dry_run"
    ok, detail = mt.manual_send("sms", "+380631112233", "", "Hello", e, m)
    assert ok and detail == "dry_run"


def test_manual_send_keeps_the_campaign_placeholder_guard():
    """Сырой {{...}} человеку не уходит и из ручного пути тоже."""
    e, m = EmailConfig(dry_run=True), MessagingConfig(dry_run=True)
    ok, detail = mt.manual_send("email", "a@b.c", "Hi",
                                "Reply to {{telegram_connect_url}}", e, m)
    assert not ok and detail == "unresolved_placeholder"


def test_whatsapp_and_inapp_do_not_go_through_the_text_transport():
    """WhatsApp = инбокс (личный номер), inapp = очередь баннеров: у обоих
    свои пути в API. Транспорт свободного текста их не знает."""
    e, m = EmailConfig(dry_run=True), MessagingConfig(dry_run=True)
    assert mt.manual_send("whatsapp", "97150", "", "hi", e, m) == \
        (False, "unknown_channel")
    assert mt.manual_send("inapp", "", "", "hi", e, m) == \
        (False, "unknown_channel")
    assert "whatsapp" not in mt.SEND_CHANNELS
    # и wa_personal этот модуль не импортирует: единственный путь - инбокс
    import inspect
    assert "wa_personal" not in inspect.getsource(mt)


def test_send_log_row_matches_the_send_log_contract():
    row = mt.send_log_row("t", "id1", "email", "Subj", "body", "sent", "",
                          "2026-08-08 10:00:00.000", "msg_1")
    assert len(row) == len(mt.SEND_LOG_COLUMNS)
    assert row[1] == "manual" and row[3] == -1
    assert row[5] == "Subj" and row[8] == "msg_1"
    # без темы detail = начало текста (лог читают люди)
    row = mt.send_log_row("t", "id1", "sms", "", "  Hello   world  " + "x" * 200,
                          "sent", "", "2026-08-08 10:00:00.000")
    assert row[5].startswith("Hello world") and len(row[5]) <= 80


def test_manual_campaign_id_is_stable():
    """По этому id uplift-отчёт отделяет ручные касания от кампаний."""
    assert mt.MANUAL_CAMPAIGN == "manual"
