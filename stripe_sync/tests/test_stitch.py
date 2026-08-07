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


def test_r4_cuid_only_is_visible_not_discarded():
    """ПРАВИЛО ИЗМЕНЕНО: юзер без email/биллинга больше не выбрасывается в
    unmatched - он получает identity по client_user_id, иначе для него не
    работают ни стадии, ни ACTIVATE-кампания, ни in-app баннер."""
    idents, unmatched = build_identities(TENANT, [], [
        EventKey(client_user_id="u_ghost", last_ts="2026-08-02"),
    ])
    assert len(idents) == 1 and idents[0].client_user_id == "u_ghost"
    assert unmatched == []


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


def test_bridge_event_binds_customer_without_backfill():
    """checkout.completed (client+hash+customer) до бэкфила кастомеров:
    identity получает stripe_customer_id, billing-события резолвятся."""
    idents, unmatched = build_identities(TENANT, [], [
        EventKey(client_user_id="u_demo_1", email_hash="hash_demo",
                 stripe_customer_id="cus_demo_1", last_ts="2026-08-05"),
        EventKey(stripe_customer_id="cus_demo_1", last_ts="2026-08-05"),
    ])
    assert len(idents) == 1
    ident = idents[0]
    assert ident.client_user_id == "u_demo_1"
    assert ident.stripe_customer_id == "cus_demo_1"
    assert set(ident.sources) == {"stripe", "snippet"}
    assert unmatched == []


def test_r4_cuid_only_user_gets_identity():
    """Юзер без email и биллинга должен быть виден: своя identity по cuid."""
    ids, unm = build_identities("hub", [], [
        EventKey(client_user_id="u_no_email", last_ts="2026-08-05 10:00:00"),
    ])
    assert len(ids) == 1
    assert ids[0].client_user_id == "u_no_email"
    assert ids[0].email_hash == ""
    assert "snippet" in ids[0].sources


def test_r4_yields_to_email_identity_when_hash_appears():
    """Как только у cuid появился email - живём по email-identity, без дубля."""
    ids, _ = build_identities("hub", [], [
        EventKey(client_user_id="u1", last_ts="2026-08-05 10:00:00"),
        EventKey(client_user_id="u1", email_hash="h1", last_ts="2026-08-05 11:00:00"),
    ])
    assert len(ids) == 1 and ids[0].email_hash == "h1"


def test_every_job_entrypoint_is_runnable():
    """Джобы запускаются подпроцессом из планировщика: опечатка в main() не
    видна ни импортом, ни линтером - падает только в проде. Здесь проверяем,
    что каждый вход компилируется и не ссылается на несуществующие имена."""
    import pathlib
    import py_compile
    import symtable

    jobs = ["stitch", "scoring", "contacts_sync", "plans_sync", "campaign_tick",
            "uplift_report", "ai_analyst", "cancel_reasons", "issue", "backfill"]
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in jobs:
        path = root / f"{name}.py"
        py_compile.compile(str(path), doraise=True)
        src = path.read_text()
        table = symtable.symtable(src, str(path), "exec")
        main = next((c for c in table.get_children() if c.get_name() == "main"), None)
        if main is None:
            continue
        local = {sym.get_name() for sym in main.get_symbols() if sym.is_assigned()}
        module = {sym.get_name() for sym in table.get_symbols()}
        import builtins
        for sym in main.get_symbols():
            if not sym.is_referenced() or sym.is_assigned() or sym.is_imported():
                continue
            n = sym.get_name()
            if n.startswith("__") and n.endswith("__"):
                continue          # __file__ и прочая магия модуля
            assert n in local or n in module or hasattr(builtins, n), \
                f"{name}.main(): имя {n!r} нигде не определено"
