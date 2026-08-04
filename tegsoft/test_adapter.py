"""Проверка звонилки на MockProvider — полный цикл без внешних сервисов.

Покрывает:
  1. MockProvider: originate → get_recordings → stream_recording;
  2. simulate_webhook: сборка payload как у боевого Tegsoft ECR;
  3. store.upsert_call: корректный INSERT в crm.calls (Postgres замокан fake-conn),
     + пропуск recording_ref когда колонки нет (совместимость с волной 1 / A1);
  4. lookup: телефон игрока (fake ClickHouse), do_not_contact, маска, маппинг ext↔operator,
     нормализация исхода;
  5. api/calls.py: webhook end-to-end (Flask test client) и originate.

Запуск:
    pytest tegsoft/test_adapter.py            # если установлен pytest
    python tegsoft/test_adapter.py            # standalone-режим (без pytest)

Реальные вызовы Tegsoft НЕ выполняются (доступов нет — только Mock работает вживую;
TegsoftProvider покрыт статически конструированием, боевой путь остаётся непроверенным).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# импорт пакета из корня репозитория (api/ — namespace-пакет, __init__ пишет A3)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tegsoft import MockProvider, get_provider, reset_provider  # noqa: E402
from tegsoft import lookup, store  # noqa: E402


# ── фейки внешних систем ─────────────────────────────────────────────────────────
class FakeCursor:
    """Минимальный psycopg-совместимый курсор: маршрутизирует ответы по тексту SQL."""

    def __init__(self, conn, rec_col: bool, existing_id):
        self._conn = conn
        self._rec_col = rec_col
        self._existing_id = existing_id
        self._last = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._conn.statements.append((sql, params))
        s = sql.lower()
        if "information_schema" in s:
            self._last = (1,) if self._rec_col else None
        elif "select id from crm.calls where provider_ref" in s:
            self._last = (self._existing_id,) if self._existing_id else None
        elif "returning id" in s:
            self._last = ("11111111-2222-3333-4444-555555555555",)
        else:
            self._last = None

    def fetchone(self):
        return self._last


class FakeConn:
    def __init__(self, rec_col=False, existing_id=None):
        self.statements: list = []
        self._rec_col = rec_col
        self._existing_id = existing_id

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self, self._rec_col, self._existing_id)


class FakeCHResult:
    def __init__(self, rows):
        self.result_rows = rows


class FakeCHClient:
    def __init__(self, rows):
        self._rows = rows

    def query(self, sql, parameters=None):
        return FakeCHResult(self._rows)


# ── 1. MockProvider полный цикл ──────────────────────────────────────────────────
def test_mock_originate_and_recordings():
    p = MockProvider()
    ref = p.originate("101", "+905551234567")
    assert ref.startswith("mock-")
    assert p.health() is True
    recs = p.get_recordings(ref)
    assert recs and recs[0].endswith(".mp3")
    chunks = b"".join(p.stream_recording(ref))
    assert chunks.startswith(b"ID3") and b"MOCK-AUDIO" in chunks


def test_mock_originate_requires_both_args():
    p = MockProvider()
    try:
        p.originate("101", "")
    except Exception as e:  # CallProviderError
        assert "player_phone" in str(e) or "operator_ext" in str(e)
    else:
        raise AssertionError("ожидалась ошибка на пустой phone")


def test_simulate_webhook_payload():
    p = MockProvider()
    ref = p.originate("101", "+905551234567")
    out = p.simulate_webhook(ref, "answered", 42, casino_player_id=808, operator_ext="101")
    assert out["posted"] is False
    pl = out["payload"]
    assert pl["provider_ref"] == ref
    assert pl["casino_player_id"] == 808
    assert pl["outcome"] == "answered"
    assert pl["duration_sec"] == 42
    assert pl["operator_ext"] == "101"


def test_factory_default_is_mock():
    reset_provider()
    os.environ.pop("CALL_PROVIDER", None)
    assert get_provider().name == "mock"


# ── 2. store.upsert_call (Postgres замокан) ──────────────────────────────────────
def test_upsert_insert_without_recording_col():
    store.reset_schema_cache()
    conn = FakeConn(rec_col=False)
    rec = {
        "casino_player_id": 808, "operator_id": "op-uuid", "outcome": "answered",
        "result": "interested", "provider_ref": "mock-1", "started_at": None,
        "duration_sec": 42, "recording_ref": "rec-mock-1.mp3",
    }
    call_id = store.upsert_call(rec, conn_factory=lambda: conn)
    assert call_id == "11111111-2222-3333-4444-555555555555"
    insert = [s for s, _ in conn.statements if "insert into crm.calls" in s.lower()]
    assert insert, "ожидался INSERT в crm.calls"
    # колонки recording_ref нет → поле НЕ должно попасть в INSERT
    assert "recording_ref" not in insert[0]


def test_upsert_includes_recording_col_when_present():
    store.reset_schema_cache()
    conn = FakeConn(rec_col=True)
    rec = {
        "casino_player_id": 808, "operator_id": "op-uuid", "outcome": "answered",
        "result": None, "provider_ref": "mock-2", "started_at": None,
        "duration_sec": 10, "recording_ref": "rec-mock-2.mp3",
    }
    store.upsert_call(rec, conn_factory=lambda: conn)
    insert = [s for s, _ in conn.statements if "insert into crm.calls" in s.lower()][0]
    assert "recording_ref" in insert
    store.reset_schema_cache()


def test_upsert_updates_existing_by_provider_ref():
    store.reset_schema_cache()
    conn = FakeConn(rec_col=False, existing_id="existing-uuid")
    rec = {
        "casino_player_id": 808, "operator_id": "op-uuid", "outcome": "answered",
        "result": None, "provider_ref": "mock-3", "started_at": None,
        "duration_sec": 99, "recording_ref": None,
    }
    store.upsert_call(rec, conn_factory=lambda: conn)
    updates = [s for s, _ in conn.statements if "update crm.calls" in s.lower()]
    assert updates, "существующий provider_ref → ожидался UPDATE, не INSERT"


# ── 3. lookup ────────────────────────────────────────────────────────────────────
def test_get_player_phone_composes_e164():
    client = FakeCHClient([("5551234567", "90", "0")])
    num = lookup.get_player_phone(808, client_factory=lambda: client)
    assert num == "+905551234567"


def test_get_player_phone_respects_do_not_contact():
    client = FakeCHClient([("5551234567", "90", "1")])
    try:
        lookup.get_player_phone(808, client_factory=lambda: client)
    except lookup.DoNotContactError:
        pass
    else:
        raise AssertionError("do_not_contact=1 должен блокировать звонок")


def test_mask_phone():
    assert lookup.mask_phone("+905551234567") == "+90•••••4567"
    assert lookup.mask_phone("") == ""


def test_operator_ext_mapping_roundtrip():
    os.environ["TEGSOFT_EXT_MAP"] = '{"op-uuid":"101"}'
    try:
        assert lookup.operator_ext("op-uuid") == "101"
        assert lookup.operator_id_for_ext("101") == "op-uuid"
    finally:
        os.environ.pop("TEGSOFT_EXT_MAP", None)


def test_normalize_outcome():
    assert lookup.normalize_outcome("CONNECTED") == "answered"
    assert lookup.normalize_outcome("RingNoAnswer") == "no_answer"
    assert lookup.normalize_outcome("busy") == "busy"
    assert lookup.normalize_outcome("weird-unknown") == "no_answer"
    assert lookup.normalize_outcome(None) == "no_answer"


# ── 4. api/calls.py через Flask test client ──────────────────────────────────────
def _make_app():
    from flask import Flask
    from api.calls import bp
    app = Flask(__name__)
    app.register_blueprint(bp)
    app.testing = True
    return app


def test_webhook_end_to_end(monkeypatch_env=None):
    os.environ["TEGSOFT_WEBHOOK_SECRET"] = "s3cr3t"
    os.environ["TEGSOFT_EXT_MAP"] = '{"op-uuid":"101"}'
    captured = {}

    def fake_upsert(record, **kw):
        captured["record"] = record
        return "call-uuid-1"

    store_upsert_orig = store.upsert_call
    store_audit_orig = store.write_audit
    store.upsert_call = fake_upsert
    store.write_audit = lambda *a, **k: None
    try:
        app = _make_app()
        c = app.test_client()
        # без секрета — 401
        r0 = c.post("/api/v1/webhooks/tegsoft", json={"casino_player_id": 808})
        assert r0.status_code == 401
        # с секретом и корректным payload — 200 + запись собрана
        payload = MockProvider().build_webhook_payload(
            "mock-x", "answered", 33, casino_player_id=808, operator_ext="101",
        )
        r = c.post("/api/v1/webhooks/tegsoft", json=payload, headers={"X-Tegsoft-Secret": "s3cr3t"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert captured["record"]["casino_player_id"] == 808
        assert captured["record"]["operator_id"] == "op-uuid"
        assert captured["record"]["outcome"] == "answered"
    finally:
        store.upsert_call = store_upsert_orig
        store.write_audit = store_audit_orig
        os.environ.pop("TEGSOFT_WEBHOOK_SECRET", None)
        os.environ.pop("TEGSOFT_EXT_MAP", None)


def test_webhook_recovers_ids_from_provider_ref():
    """Боевой сценарий Tegsoft-ECR: пришёл только CALLID (provider_ref) + исход +
    длительность, БЕЗ casino_player_id/operator. Игрок/оператор восстанавливаются
    из связки, записанной при originate (store.lookup_originate)."""
    os.environ["TEGSOFT_WEBHOOK_SECRET"] = "s3cr3t"
    captured = {}

    def fake_upsert(record, **kw):
        captured["record"] = record
        return "call-uuid-2"

    up_orig, au_orig, lo_orig = store.upsert_call, store.write_audit, store.lookup_originate
    store.upsert_call = fake_upsert
    store.write_audit = lambda *a, **k: None
    store.lookup_originate = lambda ref, **kw: {"casino_player_id": 808, "operator_id": "op-uuid"}
    try:
        app = _make_app()
        c = app.test_client()
        # payload как у боевого ECR: только id звонка провайдера + исход + длительность
        r = c.post(
            "/api/v1/webhooks/tegsoft",
            json={"provider_ref": "tg-CALLID-1", "outcome": "CONNECTED", "duration_sec": 51},
            headers={"X-Tegsoft-Secret": "s3cr3t"},
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        assert captured["record"]["casino_player_id"] == 808
        assert captured["record"]["operator_id"] == "op-uuid"
        assert captured["record"]["outcome"] == "answered"  # normalize_outcome('CONNECTED')
        # нет связки и нет id в payload → 422 (не пишем «висячий» звонок)
        store.lookup_originate = lambda ref, **kw: None
        r2 = c.post(
            "/api/v1/webhooks/tegsoft",
            json={"provider_ref": "unknown", "outcome": "busy"},
            headers={"X-Tegsoft-Secret": "s3cr3t"},
        )
        assert r2.status_code == 422
    finally:
        store.upsert_call, store.write_audit, store.lookup_originate = up_orig, au_orig, lo_orig
        os.environ.pop("TEGSOFT_WEBHOOK_SECRET", None)


def test_webhook_secret_in_url_path():
    """Форма Tegsoft «Управление веб-перехватчиком» не всегда шлёт кастомный
    заголовок → секрет можно передать сегментом URL-пути."""
    os.environ["TEGSOFT_WEBHOOK_SECRET"] = "urlsecret"
    up_orig, au_orig, lo_orig = store.upsert_call, store.write_audit, store.lookup_originate
    store.upsert_call = lambda rec, **kw: "call-uuid-url"
    store.write_audit = lambda *a, **k: None
    store.lookup_originate = lambda ref, **kw: {"casino_player_id": 808, "operator_id": "op-uuid"}
    try:
        c = _make_app().test_client()
        # верный секрет в пути → 200
        r = c.post("/api/v1/webhooks/tegsoft/urlsecret",
                   json={"provider_ref": "tg-1", "status": "ANSWERED"})
        assert r.status_code == 200, r.get_data(as_text=True)
        # неверный секрет в пути → 401
        r2 = c.post("/api/v1/webhooks/tegsoft/WRONG", json={"provider_ref": "tg-1"})
        assert r2.status_code == 401
    finally:
        store.upsert_call, store.write_audit, store.lookup_originate = up_orig, au_orig, lo_orig
        os.environ.pop("TEGSOFT_WEBHOOK_SECRET", None)


def test_webhook_parses_tegsoft_native_fields():
    """Всеядный разбор: Tegsoft-имена (UNIQUEID/status/BILLSEC/CALLDATE) + form-body
    (не JSON) корректно маппятся в наш record."""
    os.environ["TEGSOFT_WEBHOOK_SECRET"] = "s3cr3t"
    captured = {}
    up_orig, au_orig, lo_orig = store.upsert_call, store.write_audit, store.lookup_originate
    def _cap(rec, **kw):
        captured["record"] = rec           # перезаписываем на каждый вызов (не setdefault)
        return "id"
    store.upsert_call = _cap
    store.write_audit = lambda *a, **k: None
    store.lookup_originate = lambda ref, **kw: {"casino_player_id": 808, "operator_id": "op-uuid"}
    try:
        c = _make_app().test_client()
        # form-encoded (не JSON), родные имена Tegsoft
        r = c.post("/api/v1/webhooks/tegsoft",
                   data={"UNIQUEID": "1708543072.368", "status": "RINGNOANSWER", "BILLSEC": "0"},
                   headers={"X-Tegsoft-Secret": "s3cr3t"})
        assert r.status_code == 200, r.get_data(as_text=True)
        rec = captured["record"]
        assert rec["provider_ref"] == "1708543072.368"     # UNIQUEID → provider_ref
        assert rec["outcome"] == "no_answer"               # normalize_outcome('RINGNOANSWER')
        assert rec["duration_sec"] == 0                    # BILLSEC → duration_sec

        # состоявшийся звонок с длительностью в МИЛЛИСЕКУНДАХ (talkDurationMillis)
        r2 = c.post("/api/v1/webhooks/tegsoft",
                    json={"UNIQUEID": "x.1", "status": "COMPLETEAGENT", "talkDurationMillis": 483685},
                    headers={"X-Tegsoft-Secret": "s3cr3t"})
        assert r2.status_code == 200, r2.get_data(as_text=True)
        rec2 = captured["record"]
        assert rec2["outcome"] == "answered"               # COMPLETEAGENT → состоялся
        assert rec2["duration_sec"] == 483                 # 483685 мс → 483 сек (не 483685!)
    finally:
        store.upsert_call, store.write_audit, store.lookup_originate = up_orig, au_orig, lo_orig
        os.environ.pop("TEGSOFT_WEBHOOK_SECRET", None)


def _mint_jwt(role: str, secret: str = "test-secret-32-bytes-long-000000", sub: str = "op-uuid") -> str:
    """Собрать Supabase-подобный JWT с ролью приложения в app_metadata (как ждёт api.core)."""
    import jwt  # PyJWT (уже установлен — им пользуется api/core.py)
    return jwt.encode({"sub": sub, "app_metadata": {"role": role}}, secret, algorithm="HS256")


def test_originate_end_to_end():
    reset_provider()
    os.environ["CALL_PROVIDER"] = "mock"
    # dev-байпас авторизации теперь ЯВНЫЙ (фикс-волна): API_AUTH_OFF действует только
    # вместе с ALLOW_AUTH_OFF=1 (или FLASK_ENV=development). Роль под ним — super_admin
    # (в CALL_ROLES; can_access_player для reads_all-роли короткозамыкает в True).
    os.environ["API_AUTH_OFF"] = "1"
    os.environ["ALLOW_AUTH_OFF"] = "1"
    os.environ["TEGSOFT_DEFAULT_EXT"] = "101"  # ext оператора (маппинга нет → дефолт)
    lookup_orig = lookup.get_player_phone
    audit_orig = store.write_audit
    lookup.get_player_phone = lambda pid, **kw: "+905551234567"
    store.write_audit = lambda *a, **k: None
    try:
        app = _make_app()
        c = app.test_client()
        r = c.post("/api/v1/calls/originate", json={"casino_player_id": 808})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()["data"]
        assert data["call_ref"].startswith("mock-")
        # номер отдаётся ТОЛЬКО замаскированным
        assert data["player_phone_masked"] == "+90•••••4567"
        assert "5551234" not in data["player_phone_masked"]
        # плохой id → 422
        r2 = c.post("/api/v1/calls/originate", json={})
        assert r2.status_code == 422
    finally:
        lookup.get_player_phone = lookup_orig
        store.write_audit = audit_orig
        reset_provider()
        for k in ("CALL_PROVIDER", "API_AUTH_OFF", "ALLOW_AUTH_OFF", "TEGSOFT_DEFAULT_EXT"):
            os.environ.pop(k, None)


def test_originate_role_forbidden():
    # реальный JWT с ролью analyst (нет права звонка) → 403 через require_auth(CALL_ROLES) ядра A3
    os.environ.pop("API_AUTH_OFF", None)
    os.environ["SUPABASE_JWT_SECRET"] = "test-secret-32-bytes-long-000000"
    os.environ["SUPABASE_JWT_AUD"] = ""      # aud-проверку выключаем для теста
    try:
        app = _make_app()
        c = app.test_client()
        token = _mint_jwt("analyst")
        r = c.post("/api/v1/calls/originate", json={"casino_player_id": 808},
                   headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403, r.get_data(as_text=True)
        # без токена — 401
        r2 = c.post("/api/v1/calls/originate", json={"casino_player_id": 808})
        assert r2.status_code == 401
    finally:
        os.environ.pop("SUPABASE_JWT_SECRET", None)
        os.environ.pop("SUPABASE_JWT_AUD", None)


# ── TegsoftProvider: токен-режим (Bearer, ПОДТВЕРЖДЁН на боевом f81o27) ──────────
# HTTP замокан — сеть НЕ трогаем; проверяем контракт авторизации, а не инстанс.
class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload
        self.content = b"x"
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _token_provider(monkeypatch_request):
    from tegsoft.adapter import TegsoftProvider
    p = TegsoftProvider(base_url="https://f81o27.example", token="TESTTOKEN")
    # подменяем HTTP-слой: запоминаем, какие сервлеты дёргали
    calls = []

    def fake_request(servlet, params, *, stream=False):
        calls.append((servlet, params.get("service")))
        return monkeypatch_request(servlet, params)

    p._request = fake_request  # type: ignore[assignment]
    return p, calls


def test_token_mode_sets_bearer_header():
    """Токен уходит в заголовок Authorization: Bearer (боевая схема).
    requests в тестовом окружении нет — подсовываем фейковый модуль с Session."""
    from tegsoft.adapter import TegsoftProvider

    class _FakeSession:
        def __init__(self):
            self.headers: dict = {}

    class _FakeRequestsModule:
        Session = _FakeSession

    p = TegsoftProvider(base_url="https://f81o27.example", token="ABC123")
    p._requests = lambda: _FakeRequestsModule  # type: ignore[assignment]
    sess = p._get_session()
    assert sess.headers.get("Authorization") == "Bearer ABC123"


def test_token_mode_skips_performlogin():
    """В токен-режиме _ensure_session НЕ зовёт performLogin (он на инстансе даёт
    Code:898). Ни одного обращения к servlet Login с service=performLogin."""
    def resp(servlet, params):
        return _FakeResp({"success": True, "user": {"DISPLAYNAME": "entegreapi"}})

    p, calls = _token_provider(resp)
    p._ensure_session()
    assert p._logged_in is True
    assert all(svc != "performLogin" for _, svc in calls), calls


def test_token_health_parses_success_true():
    """health() читает боевой ответ checkLoginStatus: success=true → живой токен,
    success=false («No user login detected») → мёртвый."""
    ok_p, _ = _token_provider(lambda s, prm: _FakeResp({"success": True, "user": {}}))
    assert ok_p.health() is True

    bad_p, _ = _token_provider(lambda s, prm: _FakeResp(
        {"result": None, "success": False, "message": "No user login detected"}))
    assert bad_p.health() is False


# ── standalone-раннер (без pytest) ───────────────────────────────────────────────
def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
