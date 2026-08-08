"""WhatsApp Cloud API: шаблоны из кампаний, подпись вебхука, connect-флоу.

Живого токена в тестах нет и не должно быть: сеть мокается на границе HTTP,
проверяется ФОРМА запросов к Meta и разбор её ответов - то, что ломается
молча и дорого.
"""

import json
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import whatsapp_cloud as wac  # noqa: E402
from saas_senders import MessagingConfig, send_whatsapp  # noqa: E402
from wa_templates import (build_from_step, connect_url, parse_connect_text,  # noqa: E402
                          pick_template, template_name, to_meta_body)


# ── Шаблоны из шагов кампаний ────────────────────────────────────────────────

def test_named_placeholders_become_positional_and_order_survives():
    """Meta принимает только {{1}}, {{2}} - имена возвращаются для подстановки."""
    body, names = to_meta_body(
        "Update your card: {{card_update_url}} or open {{app_url}}")
    assert body == "Update your card: {{1}} or open {{2}}"
    assert names == ["card_update_url", "app_url"]


def test_dunning_step_builds_a_utility_template():
    step = {"body": "Your payment did not go through. Update your card in "
                    "30 seconds: {{card_update_url}}. Your account is safe."}
    payload, reason = build_from_step("hubcontent", "K3_payment_recovery", 2, step)
    assert reason == "" and payload["category"] == "UTILITY"
    assert payload["name"] == "retivo_hubcontent_k3_payment_recovery_s2_v1"
    assert payload["param_names"] == ["card_update_url"]
    assert "{{1}}" in payload["body"]


def test_promo_words_are_refused_in_utility_before_meta_sees_them():
    """Промо-слово в utility: Meta переклассифицирует (цена x3) или отклонит
    (минус к качеству WABA). Ловим у себя - до подачи."""
    step = {"body": "Your trial ends soon. Upgrade now and get 20% off!"}
    payload, reason = build_from_step("t", "K2_trial_conversion", 1, step)
    assert payload is None and reason == "promo_words_in_utility"
    # для MARKETING-кампании то же слово допустимо
    payload, reason = build_from_step("t", "K6_winback", 0, step)
    assert reason == "" and payload["category"] == "MARKETING"


def test_template_name_is_meta_safe_and_versioned():
    name = template_name("Hub-Content", "K3_payment_recovery", 2, 3)
    assert name == "retivo_hub_content_k3_payment_recovery_s2_v3"
    assert all(c.islower() or c.isdigit() or c == "_" for c in name)


def test_registry_picks_the_newest_approved_version():
    reg = (
        ("tpl_v1", "APPROVED", "K3_payment_recovery", 2, 1, ("card_update_url",)),
        ("tpl_v2", "PENDING", "K3_payment_recovery", 2, 2, ("card_update_url",)),
        ("other", "APPROVED", "K6_winback", 0, 1, ()),
    )
    name, params = pick_template(reg, "K3_payment_recovery", 2)
    assert name == "tpl_v1"                    # v2 ещё не одобрен
    assert params == ("card_update_url",)
    assert pick_template(reg, "K1_activation", 0) == ("", ())


# ── Отправка ─────────────────────────────────────────────────────────────────

def _cfg(**kw):
    base = dict(dry_run=True, wa_token="tok", wa_phone_number_id="123",
                wa_templates=(("tpl", "APPROVED", "K3_payment_recovery", 2, 1,
                               ("card_update_url",)),))
    base.update(kw)
    return MessagingConfig(**base)


def test_send_requires_an_approved_template_for_the_step():
    ok, detail = send_whatsapp("+971501112233", "text", _cfg(),
                               {"campaign_id": "K1_activation", "step_idx": 0})
    assert not ok and detail == "wa_template_not_approved"


def test_send_refuses_empty_parameter_values():
    """Пустая подстановка = битая ссылка в мессенджере человека."""
    ok, detail = send_whatsapp("+971501112233", "text", _cfg(),
                               {"campaign_id": "K3_payment_recovery",
                                "step_idx": 2, "card_update_url": ""})
    assert not ok and detail == "unresolved_placeholder"


def test_send_dry_run_passes_with_approved_template():
    ok, detail = send_whatsapp("+971501112233", "text", _cfg(),
                               {"campaign_id": "K3_payment_recovery",
                                "step_idx": 2,
                                "card_update_url": "https://pay.x/y"})
    assert ok and detail == "dry_run"


def test_send_builds_the_exact_meta_payload(monkeypatch):
    """Форма запроса к Meta - контракт: ломается молча и дорого."""
    captured = {}

    def fake_post(url, token, payload):
        captured.update({"url": url, "token": token, "payload": payload})
        return 200, {"messages": [{"id": "wamid.ABC"}]}

    monkeypatch.setattr(wac, "_post", fake_post)
    ok, detail = wac.send_template("tok", "123", "+971 50 111-22-33",
                                   "tpl", "en", ["https://pay.x/y"])
    assert ok and detail == "wamid.ABC"
    assert captured["url"].endswith("/123/messages")
    p = captured["payload"]
    assert p["to"] == "971501112233"           # без + и мусора
    assert p["template"]["name"] == "tpl"
    assert p["template"]["components"][0]["parameters"][0]["text"] == "https://pay.x/y"


def test_meta_error_codes_route_to_retry_or_suppression():
    assert wac.is_transient("wa_130429:rate limit hit")
    assert not wac.is_transient("wa_131026:not on whatsapp")
    assert wac.should_suppress("wa_131050:user stopped marketing")
    assert not wac.should_suppress("wa_130429:rate limit hit")


# ── Вебхук ───────────────────────────────────────────────────────────────────

def test_webhook_signature_is_hmac_of_the_raw_body():
    body = b'{"entry": []}'
    import hashlib
    import hmac as hm
    good = "sha256=" + hm.new(b"secret", body, hashlib.sha256).hexdigest()
    assert wac.verify_signature("secret", body, good)
    assert not wac.verify_signature("secret", body, good[:-1] + "0")
    assert not wac.verify_signature("", body, good)
    assert not wac.verify_signature("secret", body, "sha1=abc")


def test_webhook_parses_statuses_inbound_and_template_updates():
    doc = {"entry": [{"changes": [
        {"field": "messages", "value": {
            "statuses": [{"id": "wamid.1", "status": "failed",
                          "timestamp": "1786000000", "recipient_id": "97150",
                          "errors": [{"code": 131050}]}],
            "messages": [{"id": "wamid.2", "from": "97150",
                          "timestamp": "1786000001", "type": "text",
                          "text": {"body": "hello"}}]}},
        {"field": "message_template_status_update", "value": {
            "message_template_name": "retivo_x_k3_s2_v1", "event": "approved",
            "reason": "none"}},
    ]}]}
    out = wac.parse_webhook(doc)
    assert out["statuses"][0]["error_code"] == 131050
    assert out["inbound"][0]["text"] == "hello"
    assert out["templates"][0] == {"name": "retivo_x_k3_s2_v1",
                                   "event": "APPROVED", "reason": "none"}
    assert wac.parse_webhook({}) == {"statuses": [], "inbound": [],
                                     "templates": []}


# ── Connect-флоу: человек пишет первым ───────────────────────────────────────

def test_connect_url_roundtrip_binds_the_account():
    url = connect_url("+971 4 123 4567", "hubcontent", "st_user_1", secret="k")
    assert url.startswith("https://wa.me/97141234567?text=")
    text = unquote(url.split("text=")[1])
    assert parse_connect_text("hubcontent", text, secret="k") == "st_user_1"
    # подпись чужого тенанта не подходит
    assert parse_connect_text("other", text, secret="k") == ""
    # подделка кода - никого не привязали
    forged = text[:-2] + ("00" if not text.endswith("00") else "11")
    assert parse_connect_text("hubcontent", forged, secret="k") == ""


def test_plain_inbound_text_binds_nobody():
    assert parse_connect_text("t", "hi, i need help", secret="k") == ""
    assert connect_url("", "t", "u") == ""
    assert connect_url("+9714", "t", "") == ""
