"""Входящие ответы: parse_inbound терпит все формы поля from."""

from email_delivery import parse_inbound


def test_ignores_other_events():
    assert parse_inbound({"type": "email.delivered", "data": {}}) == {}
    assert parse_inbound({}) == {}


def test_from_as_display_string():
    inb = parse_inbound({"type": "email.received", "data": {
        "from": "Vasya Pupkin <vasya@mail.ru>",
        "subject": "Re: one thing about pricing",
        "text": "too expensive for me", "email_id": "em_1"}})
    assert inb["from_email"] == "vasya@mail.ru"
    assert inb["text"] == "too expensive for me"
    assert inb["provider_id"] == "em_1"


def test_from_as_dict():
    inb = parse_inbound({"type": "email.received", "data": {
        "from": {"email": "A@B.com", "name": "A"}, "text": "hi"}})
    assert inb["from_email"] == "a@b.com"


def test_html_fallback_when_no_text():
    inb = parse_inbound({"type": "email.received", "data": {
        "from": "x@y.com", "html": "<div>hello <b>there</b>&nbsp;</div>"}})
    assert "hello" in inb["text"] and "<" not in inb["text"]


def test_garbage_from_gives_empty_email():
    inb = parse_inbound({"type": "email.received", "data": {
        "from": "not-an-address", "text": "hi"}})
    assert inb["from_email"] == ""
