"""Подписка на Telegram-бота тенанта: подпись ссылок и паритет зеркала.

Подпись существует по одной причине: голый client_user_id в ссылке позволяет
любому, кто узнал чужой id, увести чужие уведомления в свой чат.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ingest"))

from telegram_connect import (PAYLOAD_RE, connect_url, parse_start,  # noqa: E402
                              sign_payload)


def test_signed_payload_roundtrip():
    payload = sign_payload("hub", "u_18342", secret="k")
    assert PAYLOAD_RE.match(payload) and len(payload) <= 64
    uid, kind = parse_start("hub", payload, secret="k")
    assert (uid, kind) == ("u_18342", "signed")


def test_uuid_uid_fits_signed_format():
    """Идентификаторы из импорта часто UUID - они обязаны влезать в 64."""
    uuid = "243fbfe0-b03b-5f11-9d00-6661d7d2a014"
    payload = sign_payload("hubcontent", uuid, secret="k")
    assert payload and len(payload) <= 64
    assert parse_start("hubcontent", payload, secret="k")[0] == uuid


def test_tampered_signature_is_rejected():
    payload = sign_payload("hub", "u_1", secret="k")
    bad = payload[:-1] + ("0" if payload[-1] != "0" else "1")
    uid, reason = parse_start("hub", bad, secret="k")
    assert uid == "" and reason == "bad_signature"
    # подпись чужого тенанта не подходит: ссылка не переносится между базами
    assert parse_start("other", payload, secret="k")[0] == ""


def test_legacy_bare_uid_is_flagged_for_verification():
    uid, kind = parse_start("hub", "u_18342", secret="k")
    assert (uid, kind) == ("u_18342", "legacy")
    assert parse_start("hub", "не то", secret="k")[0] == ""


def test_connect_url_prefers_signed_and_survives_long_uids():
    url = connect_url("HubBot", "hub", "u_1", secret="k")
    assert url.startswith("https://t.me/HubBot?start=s")
    # длинный uid не влезает в подписанный формат - легаси, если алфавит чист
    long_uid = "u" * 60
    url = connect_url("@HubBot", "hub", long_uid, secret="k")
    assert url == f"https://t.me/HubBot?start={long_uid}"
    # длинный И грязный - ссылки нет вовсе, а не битая
    assert connect_url("HubBot", "hub", "x" * 60 + "!", secret="k") == ""
    assert connect_url("", "hub", "u_1") == ""


def test_ingest_mirror_stays_in_sync():
    """Разбор payload живёт в двух образах (stripe_sync и ingest).

    Расхождение означает: ссылка, подписанная бордом, не пройдёт проверку на
    шлюзе - подписки молча умрут. Тест прогоняет одни и те же данные через
    обе реализации.
    """
    import telegram_connect as tc
    import tg_events

    old = tg_events.UNSUB_SECRET
    tg_events.UNSUB_SECRET = "shared-secret"
    try:
        for uid in ("u_1", "243fbfe0-b03b-5f11-9d00-6661d7d2a014", "abc-def_9"):
            payload = tc.sign_payload("hubcontent", uid, secret="shared-secret")
            assert tg_events.parse_start("hubcontent", payload) == (uid, "signed"), uid
        # и отказ по подделке зеркален
        forged = tc.sign_payload("hubcontent", "u_1", secret="wrong")
        assert tg_events.parse_start("hubcontent", forged)[0] == ""
        assert tg_events.PAYLOAD_RE.pattern == tc.PAYLOAD_RE.pattern
        assert tg_events.SIGNED_RE.pattern == tc.SIGNED_RE.pattern
    finally:
        tg_events.UNSUB_SECRET = old


def test_unverified_contact_binds_only_to_an_existing_user():
    """contacts_sync: неподписанный uid должен существовать в базе тенанта."""
    from contacts_sync import sync_contacts

    class CH:
        def __init__(self):
            self.inserts = []

        def query(self, sql, parameters=None):
            class R:
                result_rows = []
            r = R()
            if "saas_events" in sql and "client_user_id != ''" in sql:
                r.result_rows = [
                    ["known_u", '{"channel":"telegram","address":"111",'
                                '"consent":true,"verified":false}', "2026-08-07"],
                    ["ghost_u", '{"channel":"telegram","address":"222",'
                                '"consent":true,"verified":false}', "2026-08-07"],
                    ["client_u", '{"channel":"viber","address":"333",'
                                 '"consent":true}', "2026-08-07"],
                ]
            elif "identities_current" in sql:
                r.result_rows = [["known_u"]]
            return r

        def insert(self, table, rows, column_names=None):
            self.inserts.extend(rows)

    ch = CH()
    n = sync_contacts(ch, "hub")
    uids = {r[1] for r in ch.inserts}
    # известный - записан; призрачный - отклонён; событие клиента без
    # verified - доверенное по умолчанию
    assert "known_u" in uids and "client_u" in uids
    assert "ghost_u" not in uids
    assert n == 2
