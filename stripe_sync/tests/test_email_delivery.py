"""Доставляемость email: отписка, HTML, подпись вебхука, классификация."""

import base64
import hashlib
import hmac
import json
import time

from stripe_sync.email_delivery import (build_email_payload, parse_webhook,
                                        text_to_html, unsub_token,
                                        unsub_token_valid, unsub_url,
                                        verify_svix)

SECRET = "test-secret"


# ── Отписка ─────────────────────────────────────────────────────────────────

def test_unsub_token_binds_tenant_and_address():
    t = unsub_token("hub", "a@x.com", SECRET)
    assert unsub_token_valid("hub", "a@x.com", t, SECRET)
    assert unsub_token_valid("hub", "A@X.com", t, SECRET)      # регистр не важен
    assert not unsub_token_valid("other", "a@x.com", t, SECRET)  # чужой тенант
    assert not unsub_token_valid("hub", "b@x.com", t, SECRET)    # чужой адрес
    assert not unsub_token_valid("hub", "a@x.com", "подделка", SECRET)


def test_unsub_url_is_absolute_and_signed():
    u = unsub_url("retivo.digital", "hub", "a@x.com", SECRET)
    assert u.startswith("https://retivo.digital/public/unsubscribe?")
    assert "t=hub" in u and "a=a%40x.com" in u and "s=" in u


# ── Письмо ──────────────────────────────────────────────────────────────────

def test_html_has_unsubscribe_and_clickable_links():
    html = text_to_html("Update your card: https://b.example/p\nThanks",
                        "https://retivo.digital/public/unsubscribe?x=1", "Hub Content")
    assert 'href="https://b.example/p"' in html
    assert "unsubscribe" in html.lower()
    assert "Hub Content" in html
    assert "<script" not in html.lower()


def test_html_escapes_injection():
    html = text_to_html("<script>alert(1)</script>", "https://u", "")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_payload_carries_list_unsubscribe_headers():
    p = build_email_payload("a@x.com", "Subj", "Body", "Brand <care@mail.x.com>",
                            "https://retivo.digital/u?s=1", "Brand")
    assert p["to"] == ["a@x.com"] and p["from"] == "Brand <care@mail.x.com>"
    assert p["html"] and p["text"]
    assert p["headers"]["List-Unsubscribe"] == "<https://retivo.digital/u?s=1>"
    assert p["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "Unsubscribe: https://retivo.digital/u?s=1" in p["text"]


# ── Подпись вебхука (Svix) ──────────────────────────────────────────────────

def _sign(secret_b64: str, msg_id: str, ts: str, body: bytes) -> str:
    key = base64.b64decode(secret_b64)
    signed = b"%s.%s.%s" % (msg_id.encode(), ts.encode(), body)
    return "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


def test_verify_svix_accepts_valid_and_rejects_tampered():
    raw_secret = base64.b64encode(b"super-secret-key").decode()
    secret = "whsec_" + raw_secret
    body = b'{"type":"email.delivered"}'
    ts = str(int(time.time()))
    sig = _sign(raw_secret, "msg_1", ts, body)

    assert verify_svix(secret, "msg_1", ts, body, sig) is True
    assert verify_svix(secret, "msg_1", ts, b'{"type":"email.bounced"}', sig) is False
    assert verify_svix(secret, "msg_OTHER", ts, body, sig) is False
    assert verify_svix("", "msg_1", ts, body, sig) is False          # нет секрета
    old = str(int(time.time()) - 4000)
    assert verify_svix(secret, "msg_1", old, body,
                       _sign(raw_secret, "msg_1", old, body)) is False   # старое


# ── Классификация событий ───────────────────────────────────────────────────

def test_parse_webhook_extracts_and_flags_suppression():
    ev = parse_webhook(json.loads(json.dumps({
        "type": "email.bounced",
        "data": {"email_id": "re_123", "to": ["User@X.com"], "subject": "Hi",
                 "bounce": {"message": "mailbox does not exist"}}})))
    assert ev["provider_id"] == "re_123"
    assert ev["address"] == "user@x.com"
    assert ev["suppress_reason"] == "bounced"
    assert "mailbox" in ev["detail"]

    delivered = parse_webhook({"type": "email.delivered",
                               "data": {"email_id": "re_9", "to": ["a@x.com"]}})
    assert delivered["suppress_reason"] == ""
    assert parse_webhook({"type": "contact.created", "data": {}}) == {}
