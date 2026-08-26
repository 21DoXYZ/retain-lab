"""Серверный токен ingest (§3/§4a): открытый email только с секретом бэкенда.

Контракт: публичный сниппет-токен - email вырезается, source=snippet;
серверный токен - email нормализуется и проходит, source принудительно api;
чужой тенант - 403; неизвестный токен - 401.
"""
import importlib
import json
import sys
import types

import pytest


class _FakeProducer:
    def __init__(self, *a, **k):
        self.messages = []

    def produce(self, topic, key=None, value=None, on_delivery=None):
        self.messages.append((topic, key, json.loads(value)))
        if on_delivery:
            on_delivery(None, None)

    def flush(self, timeout=None):
        return 0


@pytest.fixture()
def ingest_app(tmp_path, monkeypatch):
    tokens = tmp_path / "tokens.json"
    server_tokens = tmp_path / "server_tokens.json"
    tokens.write_text(json.dumps({"acme": "pub-token-acme"}))
    server_tokens.write_text(json.dumps({"acme": "srv-token-acme"}))
    monkeypatch.setenv("TOKENS_FILE", str(tokens))
    monkeypatch.setenv("SERVER_TOKENS_FILE", str(server_tokens))
    monkeypatch.setenv("INGEST_REQUIRE_AUTH", "1")

    fake_kafka = types.ModuleType("confluent_kafka")
    fake_kafka.Producer = _FakeProducer
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake_kafka)

    # ingest - не пакет (контейнер живёт с WORKDIR ingest и плоскими импортами
    # event_time/geo/ua), поэтому добавляем каталог в путь и грузим как "app".
    import os
    ingest_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ingest")
    monkeypatch.syspath_prepend(ingest_dir)
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    app_mod.producer = _FakeProducer()
    app_mod.app.config["TESTING"] = True
    return app_mod


def _event(**over):
    e = {
        "event_id": "ev-1",
        "tenant_id": "acme",
        "event_type": "signup",
        "ts": "2026-08-27 10:00:00.000",
        "client_user_id": "u1",
        "email": "User@Example.COM ",
        "email_hash": "abc",
        "source": "spoofed",
    }
    e.update(over)
    return e


def _post(app_mod, token, payload):
    client = app_mod.app.test_client()
    return client.post(
        "/ingest/saas/events",
        data=json.dumps(payload),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )


def test_snippet_token_strips_email(ingest_app):
    resp = _post(ingest_app, "pub-token-acme", _event())
    assert resp.status_code == 200
    (_, _, ev), = ingest_app.producer.messages
    assert "email" not in ev
    assert ev["source"] == "snippet"


def test_server_token_keeps_normalized_email_and_forces_api(ingest_app):
    resp = _post(ingest_app, "srv-token-acme", _event())
    assert resp.status_code == 200
    (_, _, ev), = ingest_app.producer.messages
    assert ev["email"] == "user@example.com"
    assert ev["source"] == "api"


def test_server_token_drops_garbage_email(ingest_app):
    resp = _post(ingest_app, "srv-token-acme", _event(email="not-an-address"))
    assert resp.status_code == 200
    (_, _, ev), = ingest_app.producer.messages
    assert "email" not in ev


def test_server_token_foreign_tenant_403(ingest_app):
    resp = _post(ingest_app, "srv-token-acme", _event(tenant_id="other"))
    assert resp.status_code == 403
    assert not ingest_app.producer.messages


def test_unknown_token_401(ingest_app):
    resp = _post(ingest_app, "no-such-token", _event())
    assert resp.status_code == 401


def test_server_token_billing_still_banned(ingest_app):
    resp = _post(ingest_app, "srv-token-acme",
                 _event(event_type="billing.invoice_paid"))
    assert resp.status_code == 403


def test_dict_meta_normalized_to_json_string(ingest_app):
    resp = _post(ingest_app, "srv-token-acme",
                 _event(meta={"order_id": "SG-1", "items": [{"sku": "A", "qty": 1}]}))
    assert resp.status_code == 200
    (_, _, ev), = ingest_app.producer.messages
    assert isinstance(ev["meta"], str)
    assert json.loads(ev["meta"])["order_id"] == "SG-1"
