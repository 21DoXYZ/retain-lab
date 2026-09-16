"""Разбор писем из IMAP: адрес, тема, тело без цитат, свои адреса."""

from mail_poll import is_own, parse_message


def _mime(from_h: str, subject: str, body: str, mid: str = "<m1@x>") -> bytes:
    return (f"From: {from_h}\r\nTo: care@hubcontent.ai\r\n"
            f"Subject: {subject}\r\nMessage-ID: {mid}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}"
            ).encode()


def test_parse_plain_reply():
    inb = parse_message(_mime("Vasya <vasya@mail.ru>",
                              "Re: one thing about pricing",
                              "too expensive for me\n\nOn Tue, Michael wrote:\n> hey"))
    assert inb["from_email"] == "vasya@mail.ru"
    assert inb["subject"] == "Re: one thing about pricing"
    assert inb["text"] == "too expensive for me"
    assert inb["message_id"] == "<m1@x>"


def test_quoted_lines_stripped():
    inb = parse_message(_mime("a@b.com", "Re: x",
                              "ok\n> quoted line\n> more quoted"))
    assert inb["text"] == "ok"


def test_encoded_subject_and_utf8_body():
    raw = ("From: u@mail.ru\r\nSubject: =?utf-8?B?0L/RgNC40LLQtdGC?=\r\n"
           "Message-ID: <m2@x>\r\n"
           "Content-Type: text/plain; charset=utf-8\r\n\r\n"
           "дорого для меня").encode()
    inb = parse_message(raw)
    assert inb["subject"] == "привет"
    assert "дорого" in inb["text"]


def test_html_fallback():
    raw = ("From: u@gmail.com\r\nSubject: Re: y\r\nMessage-ID: <m3@x>\r\n"
           "Content-Type: text/html; charset=utf-8\r\n\r\n"
           "<div>hello <b>there</b></div>").encode()
    inb = parse_message(raw)
    assert "hello" in inb["text"] and "<" not in inb["text"]


def test_own_addresses_ignored():
    assert is_own("care@hubcontent.ai")
    assert is_own("michael@reply.hubcontent.ai")
    assert is_own("alerts@retivo.digital")
    assert not is_own("vasya@mail.ru")
