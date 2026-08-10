"""Экзекьюторы: чистые билдеры payload + интеграционный тест callback (stdlib)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from stripe_sync.executors import (
    ExecConfig,
    build_balance_credit,
    build_callback_body,
    build_coupon,
    build_pause,
    build_trial_end,
    execute,
)

USER = {"identity_id": "id-1", "client_user_id": "u_5",
        "stripe_customer_id": "cus_5", "subscription_id": "sub_5"}


def test_coupon_builder_repeating_and_once():
    c = build_coupon({"params": {"percent_off": 20, "duration": "repeating",
                                 "duration_in_months": 2}})
    assert c == {"percent_off": 20, "duration": "repeating", "duration_in_months": 2}
    c = build_coupon({"params": {"percent_off": 25, "duration": "once"}})
    assert "duration_in_months" not in c


def test_trial_pause_credit_builders():
    assert build_trial_end({"params": {"days": 7}}, 1_000_000) == 1_000_000 + 7 * 86400
    p = build_pause({"params": {"months": 1}}, 1_000_000)
    assert p["behavior"] == "mark_uncollectible"
    assert p["resumes_at"] == 1_000_000 + 30 * 86400
    assert build_balance_credit({"params": {"amount_usd": 10}}) == {"amount": -1000, "currency": "usd"}


def test_callback_body_carries_identity_and_params():
    body = build_callback_body(
        {"offer_id": "O1_tokens_100",
         "params": {"command": "token_credit", "tokens": 100, "expires_days": 14}},
        USER, "hubcontent")
    assert body["command"] == "token_credit" and body["tokens"] == 100
    assert body["client_user_id"] == "u_5" and body["tenant_id"] == "hubcontent"


def test_dry_run_never_touches_network():
    cfg = ExecConfig(dry_run=True)
    for offer in (
        {"offer_id": "O2", "executor": "stripe_coupon",
         "params": {"percent_off": 20, "duration": "once"}},
        {"offer_id": "O1", "executor": "client_callback",
         "params": {"command": "token_credit", "tokens": 50}},
        {"offer_id": "O8", "executor": "pause_collection", "params": {"months": 1}},
    ):
        assert execute(offer, USER, "hubcontent", cfg) == (True, "dry_run")


def test_unknown_executor_and_unconfigured():
    cfg = ExecConfig(dry_run=False)
    ok, detail = execute({"offer_id": "x", "executor": "nope", "params": {}}, USER, "t", cfg)
    assert not ok and detail.startswith("unknown_executor")
    ok, detail = execute({"offer_id": "O1", "executor": "client_callback",
                          "params": {"command": "token_credit"}}, USER, "t", cfg)
    assert (ok, detail) == (False, "callback_not_configured")


class _Sink(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Sink.received.append(
            {"auth": self.headers.get("Authorization"), "body": json.loads(body)})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):
        pass


def test_callback_integration_real_http_roundtrip():
    """Acceptance Phase 3: client_callback реально стреляет в mock-приёмник."""
    server = HTTPServer(("127.0.0.1", 0), _Sink)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cfg = ExecConfig(dry_run=False,
                         callback_url=f"http://127.0.0.1:{port}/grant",
                         callback_token="cb-secret")
        offer = {"offer_id": "O1_tokens_100", "executor": "client_callback",
                 "params": {"command": "token_credit", "tokens": 100, "expires_days": 14}}
        ok, detail = execute(offer, USER, "hubcontent", cfg)
        assert (ok, detail) == (True, "http_200")
        assert len(_Sink.received) == 1
        got = _Sink.received[0]
        assert got["auth"] == "Bearer cb-secret"
        assert got["body"]["tokens"] == 100 and got["body"]["identity_id"] == "id-1"
    finally:
        server.shutdown()


def test_downgrade_executor_dry_run_and_validation():
    """Даунгрейд вместо отмены: dry-run уважается, без price_id - отказ."""
    from executors import ExecConfig, execute

    cfg = ExecConfig(dry_run=True, stripe_api_key="sk_test_x")
    offer = {"offer_id": "O_down", "executor": "stripe_downgrade",
             "params": {"price_id": "price_lower"}}
    ok, detail = execute(offer, {"subscription_id": "sub_1"}, "t", cfg)
    assert (ok, detail) == (True, "dry_run")

    bad = {"offer_id": "O_down", "executor": "stripe_downgrade", "params": {}}
    ok2, detail2 = execute(bad, {"subscription_id": "sub_1"}, "t", cfg)
    assert (ok2, detail2) == (False, "no_price_id")


def test_downgrade_offer_passes_schema():
    from compose import validate_offer
    offer, reason = validate_offer({
        "offer_id": "C_downgrade", "title": "Move to Starter instead",
        "executor": "stripe_downgrade", "params": {"price_id": "price_123"}})
    assert reason == "" and offer["params"]["price_id"] == "price_123"
    _o, r2 = validate_offer({"offer_id": "C_x", "title": "No price",
                             "executor": "stripe_downgrade", "params": {}})
    assert r2 != ""
