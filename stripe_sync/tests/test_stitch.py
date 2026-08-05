"""Правила склейки identity R1-R5 на фикстурах (без ClickHouse)."""

from stripe_sync.stitch import EventKey, build_identities

TENANT = "hubcontent"

CUS_ALICE = {"customer_id": "cus_a", "email_norm": "alice@mail.com",
             "email_hash": "hash_alice", "updated_at": "2026-08-01 00:00:00"}
CUS_NOMAIL = {"customer_id": "cus_x", "email_norm": "", "email_hash": "",
              "updated_at": "2026-08-01 00:00:00"}


def _by_hash(idents):
    return {i.email_hash: i for i in idents if i.email_hash}


def test_r1_r2_customer_and_snippet_merge_by_email_hash():
    idents, unmatched = build_identities(TENANT, [CUS_ALICE], [
        EventKey(client_user_id="u_1", email_hash="hash_alice", last_ts="2026-08-02"),
    ])
    a = _by_hash(idents)["hash_alice"]
    assert a.stripe_customer_id == "cus_a"
    assert a.client_user_id == "u_1"
    assert set(a.sources) == {"stripe", "snippet"}
    assert unmatched == []


def test_r3_direct_stripe_customer_id_in_event():
    idents, unmatched = build_identities(TENANT, [CUS_ALICE], [
        EventKey(client_user_id="u_1", stripe_customer_id="cus_a", last_ts="2026-08-02"),
    ])
    a = _by_hash(idents)["hash_alice"]
    assert a.client_user_id == "u_1"
    assert unmatched == []


def test_r4_no_keys_goes_to_unmatched():
    idents, unmatched = build_identities(TENANT, [], [
        EventKey(client_user_id="u_ghost", last_ts="2026-08-02"),
    ])
    assert idents == []
    assert unmatched[0]["reason"] == "no_email_hash"
    assert unmatched[0]["key_value"] == "u_ghost"


def test_r5_conflicting_email_latest_wins():
    idents, unmatched = build_identities(TENANT, [], [
        EventKey(client_user_id="u_1", email_hash="hash_old", last_ts="2026-08-01"),
        EventKey(client_user_id="u_1", email_hash="hash_new", last_ts="2026-08-03"),
    ])
    by_hash = _by_hash(idents)
    assert by_hash["hash_new"].client_user_id == "u_1"
    assert "hash_old" not in by_hash
    reasons = [u["reason"] for u in unmatched]
    assert reasons == ["conflicting_email"]


def test_customer_without_email_flagged_but_kept():
    idents, unmatched = build_identities(TENANT, [CUS_NOMAIL], [])
    assert len(idents) == 1 and idents[0].stripe_customer_id == "cus_x"
    assert unmatched[0]["reason"] == "customer_without_email"


def test_identity_id_stable_across_rebuilds():
    a1, _ = build_identities(TENANT, [CUS_ALICE], [])
    a2, _ = build_identities(TENANT, [CUS_ALICE], [
        EventKey(client_user_id="u_1", email_hash="hash_alice", last_ts="2026-08-02"),
    ])
    assert a1[0].identity_id == _by_hash(a2)["hash_alice"].identity_id
