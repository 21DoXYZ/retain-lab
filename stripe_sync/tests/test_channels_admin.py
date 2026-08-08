"""Клиентский флоу каналов: стор tenants.json, машины состояний, парсеры."""

import json
import os
import sys

import pytest

from stripe_sync import channels_admin as ca

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ingest"))
from tg_events import update_to_event  # noqa: E402


# ── tenants.json: merge + атомарная запись ───────────────────────────────────

def test_merged_tenant_none_deletes_key():
    out = ca.merged_tenant({"a": 1, "b": 2}, {"b": None, "c": 3})
    assert out == {"a": 1, "c": 3}


def test_update_tenant_roundtrip_and_preserves_others(tmp_path):
    p = str(tmp_path / "tenants.json")
    p_written = ca.update_tenant("t1", {"email_domain": "mail.x.com"}, path=p)
    assert p_written == {"email_domain": "mail.x.com"}
    ca.update_tenant("t2", {"sms_sender": "Brand"}, path=p)
    ca.update_tenant("t1", {"email_from": "X <a@mail.x.com>"}, path=p)
    data = json.loads(open(p).read())
    assert data["t1"] == {"email_domain": "mail.x.com", "email_from": "X <a@mail.x.com>"}
    assert data["t2"] == {"sms_sender": "Brand"}
    assert not [f for f in os.listdir(tmp_path) if f.startswith(".tenants-")]


# ── Машины состояний ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("conf,key,exp", [
    ({}, True, "not_connected"),
    ({"email_domain": "m.x", "email_domain_status": "awaiting_provider"}, False, "awaiting_provider"),
    ({"email_domain": "m.x", "email_domain_status": "awaiting_provider"}, True, "pending_dns"),
    ({"email_domain_status": "pending_dns"}, True, "pending_dns"),
    ({"email_domain_status": "verified"}, True, "sender_needed"),
    ({"email_domain_status": "verified", "email_from": "A <a@m.x>"}, True, "active"),
])
def test_email_state(conf, key, exp):
    assert ca.email_state(conf, key) == exp


def test_messaging_state():
    assert ca.messaging_state({}, "sms", True) == "not_connected"
    assert ca.messaging_state({"requested_sms_sender": "Brand"}, "sms", True) == "pending_approval"
    assert ca.messaging_state({"sms_sender": "Brand"}, "sms", True) == "active"
    # имя подтверждено, но платформенный ключ DT ещё не введён
    assert ca.messaging_state({"sms_sender": "Brand"}, "sms", False) == "awaiting_provider"


def test_telegram_state():
    assert ca.telegram_state({}) == "not_connected"
    assert ca.telegram_state({"telegram_bot_token": "1:x"}) == "active"


# ── Валидаторы и парсер DNS-записей ──────────────────────────────────────────

def test_validators():
    assert ca.DOMAIN_RE.match("mail.hubcontent.com")
    assert not ca.DOMAIN_RE.match("нет.домен")
    assert not ca.DOMAIN_RE.match("nodots")
    assert ca.ALPHA_RE.match("HubContent")
    assert not ca.ALPHA_RE.match("СлишкомДлинноеИмя12345")
    assert ca.BOT_TOKEN_RE.match("123456789:AAF0lqzu8GkiRnqHbDLM1a2b3c4d5e6f7g8")
    assert not ca.BOT_TOKEN_RE.match("hello")


def test_dns_rows_parse():
    dom = {"records": [
        {"record": "SPF", "name": "send.m.x", "type": "MX", "ttl": "Auto",
         "status": "not_started", "value": "feedback-smtp.eu.amazonses.com", "priority": 10},
        {"record": "DKIM", "name": "resend._domainkey.m.x", "type": "TXT",
         "status": "not_started", "value": "p=MIGf..."},
    ]}
    rows = ca.dns_rows(dom)
    assert rows[0]["priority"] == 10 and rows[0]["type"] == "MX"
    assert "priority" not in rows[1] and rows[1]["record"] == "DKIM"
    assert ca.dns_rows({}) == []


# ── Telegram-вебхук -> contact_update ────────────────────────────────────────

def test_tg_start_with_legacy_payload_binds_user_unverified():
    """Голый uid от старого сниппета: принимаем, но помечаем verified=false -
    contacts_sync привяжет его только к существующему юзеру."""
    ev, reply = update_to_event("hub", {"update_id": 7, "message": {
        "chat": {"id": 555}, "date": 1754400000, "text": "/start u_18342"}})
    assert ev["event_type"] == "contact_update"
    assert ev["client_user_id"] == "u_18342"
    assert ev["event_id"] == "tg-hub-7"
    meta = json.loads(ev["meta"])
    assert meta == {"channel": "telegram", "address": "555",
                    "consent": True, "verified": False}
    assert ev["ts"] == "2025-08-05 13:20:00"
    assert reply and "Connected" in reply["text"]


def test_tg_start_with_signed_payload_is_verified():
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    import tg_events
    from telegram_connect import sign_payload
    payload = sign_payload("hub", "u_18342", secret="k")
    old = tg_events.UNSUB_SECRET
    tg_events.UNSUB_SECRET = "k"
    try:
        ev, reply = update_to_event("hub", {"update_id": 12, "message": {
            "chat": {"id": 555}, "date": 1754400000,
            "text": f"/start {payload}"}})
        assert ev["client_user_id"] == "u_18342"
        assert json.loads(ev["meta"])["verified"] is True
        # подделанная подпись не проходит и не привязывает никого
        bad = payload[:-1] + ("0" if payload[-1] != "0" else "1")
        ev2, reply2 = update_to_event("hub", {"update_id": 13, "message": {
            "chat": {"id": 555}, "date": 1754400000, "text": f"/start {bad}"}})
        assert ev2 is None and reply2 and "connect" in reply2["text"].lower()
    finally:
        tg_events.UNSUB_SECRET = old


def test_tg_start_without_payload_gets_guidance_not_a_contact():
    """Человек нашёл бота сам: связать не с кем, но молчать нельзя."""
    ev, reply = update_to_event("hub", {"update_id": 8, "message": {
        "chat": {"id": 555}, "date": 1754400000, "text": "/start"}})
    assert ev is None
    assert reply and reply["chat_id"] == 555


def test_tg_stop_and_block_revoke_consent():
    ev, reply = update_to_event("hub", {"update_id": 9, "message": {
        "chat": {"id": 555}, "date": 1754400000, "text": "/stop"}})
    assert json.loads(ev["meta"])["consent"] is False
    assert reply and "/start" in reply["text"]
    ev2, reply2 = update_to_event("hub", {"update_id": 10, "my_chat_member": {
        "chat": {"id": 555}, "date": 1754400000,
        "new_chat_member": {"status": "kicked"}}})
    assert json.loads(ev2["meta"])["consent"] is False
    assert ev2["client_user_id"] == "" and reply2 is None


def test_tg_chatter_ignored():
    assert update_to_event("hub", {"update_id": 11, "message": {
        "chat": {"id": 555}, "text": "когда видео будет готово?"}}) == (None, None)
    assert update_to_event("hub", {}) == (None, None)


# ── contacts_sync: восстановление юзера по адресу для отписок ────────────────

class _FakeCH:
    def __init__(self, with_cuid, orphans, known):
        self._with = with_cuid
        self._orphans = orphans
        self._known = known
        self.inserted = []

    def query(self, sql, parameters=None):
        class R:
            def __init__(self, rows):
                self.result_rows = rows
        if "client_user_id != ''" in sql:
            return R(self._with)
        if "client_user_id = ''" in sql:
            return R(self._orphans)
        return R(self._known)

    def insert(self, table, rows, column_names=None):
        self.inserted.extend(rows)


def test_sync_contacts_resolves_orphan_unsubscribe():
    from stripe_sync.contacts_sync import sync_contacts

    meta_sub = json.dumps({"channel": "telegram", "address": "555", "consent": True})
    meta_unsub = json.dumps({"channel": "telegram", "address": "555", "consent": False})
    fake = _FakeCH(
        with_cuid=[["u_1", meta_sub, "2026-08-05 10:00:00"]],
        orphans=[[meta_unsub, "2026-08-05 11:00:00"],
                 [json.dumps({"channel": "telegram", "address": "999",
                              "consent": False}), "2026-08-05 11:00:00"]],
        known=[["telegram", "555", "u_1"]])
    n = sync_contacts(fake, "hub")
    assert n == 2   # подписка + разрешённая отписка; адрес 999 никому не известен
    revoked = [r for r in fake.inserted if r[4] == 0]
    assert revoked == [["hub", "u_1", "telegram", "555", 0,
                        "2026-08-05 11:00:00", "2026-08-05 11:00:00"]]
