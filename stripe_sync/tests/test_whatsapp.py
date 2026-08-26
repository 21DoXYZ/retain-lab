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


def test_webhook_surfaces_button_and_interactive_replies_as_text():
    """Ответ кнопкой шаблона (payload с RB_-кодом) и интерактивной кнопкой
    попадает в inbound.text - дальше его разбирает parse_reply_intent."""
    doc = {"entry": [{"changes": [{"field": "messages", "value": {
        "messages": [
            {"id": "wamid.b", "from": "97150", "type": "button",
             "button": {"payload": "RB_cGxhbjE_0123456789", "text": "Order again"}},
            {"id": "wamid.i", "from": "97150", "type": "interactive",
             "interactive": {"type": "button_reply",
                             "button_reply": {"id": "still_have",
                                              "title": "Still have"}}},
        ]}}]}]}
    out = wac.parse_webhook(doc)
    assert out["inbound"][0]["text"] == "RB_cGxhbjE_0123456789"
    assert out["inbound"][1]["text"] == "still_have"


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


# ── Личный номер (WAHA, трек C): только приём ────────────────────────────────

def test_personal_webhook_hmac_is_sha512_of_the_raw_body():
    import hashlib
    import hmac as hm

    import wa_personal as wap
    body = b'{"event": "message.any"}'
    key = wap.webhook_hmac_key("hub", secret="k")
    good = hm.new(key.encode(), body, hashlib.sha512).hexdigest()
    assert wap.verify_webhook("hub", body, good, secret="k")
    # подмена символа обязана МЕНЯТЬ строку: «заменить на 0», когда там уже 0,
    # однажды сделал этот тест бессмысленным
    bad = good[:-1] + ("0" if good[-1] != "0" else "1")
    assert not wap.verify_webhook("hub", body, bad, secret="k")
    assert not wap.verify_webhook("other", body, good, secret="k")
    assert not wap.verify_webhook("hub", body, "", secret="k")


def test_personal_events_parse_and_outgoing_is_ignored():
    import wa_personal as wap
    st = wap.parse_event({"event": "session.status", "payload": {
        "status": "WORKING", "me": {"id": "971501112233@c.us"}}})
    assert st == {"kind": "status", "status": "WORKING",
                  "number": "971501112233"}
    msg = wap.parse_event({"event": "message.any", "payload": {
        "id": "m1", "from": "97150@c.us", "fromMe": False, "body": "hello"}})
    assert msg["kind"] == "inbound" and msg["from"] == "97150"
    # свои ответы (с телефона или из инбокса) - в тред, а не в игнор
    assert wap.parse_event({"event": "message.any", "payload": {
        "fromMe": True, "to": "x@lid"}})["kind"] == "outbound"
    assert wap.parse_event({})["kind"] == "ignore"


def test_personal_transport_has_no_scheduled_send_path():
    """Гарантия методологии: автокасания на личный номер не ходят ТЕХНИЧЕСКИ.

    Отправка в личный канал существует ровно одна - reply_as_human из
    инбокса, за ней всегда живой человек. Конвейер кампаний до неё не
    дотягивается: ни campaign_tick, ни saas_senders этот модуль не знают.
    """
    import inspect

    import campaign_tick
    import saas_senders
    import wa_personal as wap
    senders = [n for n in dir(wap) if "send" in n.lower()]
    assert senders == [], senders          # send_* не появилось
    assert hasattr(wap, "reply_as_human")  # ручной путь есть и один
    # ГРАНИЦА ПЕРЕДВИНУТА ОСОЗНАННО (2026-08-13, решение владельца):
    # автокасания разрешены, но только через ЯВНЫЙ тумблер
    # (wa_personal_automation) и дневной бюджет номера. Дефолт - выключено:
    # без тумблера wa_personal_tenant пуст и конвейер канал не видит.
    assert saas_senders.MessagingConfig().wa_personal_tenant == ""
    assert "wa_personal_daily_cap" in inspect.getsource(campaign_tick)


def test_personal_outbound_echo_lands_in_the_thread():
    """Свои ответы (в т.ч. с телефона) - в тред: иначе половина разговора."""
    import wa_personal as wap
    out = wap.parse_event({"event": "message.any", "payload": {
        "id": "m9", "from": "971@c.us", "to": "258948@lid", "fromMe": True,
        "body": "reply from phone"}})
    assert out["kind"] == "outbound"
    assert out["chat_id"] == "258948@lid"      # тред собеседника, не свой
    assert out["text"] == "reply from phone"
    inb = wap.parse_event({"event": "message.any", "payload": {
        "id": "m10", "from": "258948@lid", "fromMe": False,
        "body": "hi", "pushName": "Ivan"}})
    assert inb["chat_id"] == "258948@lid" and inb["name"] == "Ivan"


def test_human_reply_is_the_only_send_and_needs_text():
    """Единственный путь отправки в личный канал - живой человек с текстом."""
    import wa_personal as wap
    ok, why = wap.reply_as_human("t", "", "hello")
    assert not ok and why == "empty"
    ok, why = wap.reply_as_human("t", "258948@lid", "   ")
    assert not ok and why == "empty"
    # автокампании ходят ТОЛЬКО через бюджетную ветку send_whatsapp
    # (тумблер + дневной лимит); reply_as_human остаётся ручным путём инбокса


def test_whatsapp_statuses_are_not_conversations():
    """status@broadcast - сторис контактов: в инбоксе им не место."""
    import wa_personal as wap
    assert wap.parse_event({"event": "message.any", "payload": {
        "id": "s1", "from": "status@broadcast", "fromMe": False,
        "body": "somebody's story"}})["kind"] == "ignore"


def test_personal_first_with_budget(monkeypatch):
    """Личный канал: явный тумблер + бюджет; исчерпан и без Cloud - честный
    отказ, а не тихая массовая рассылка с личного номера."""
    import saas_senders as ss

    sent = []
    monkeypatch.setattr("wa_personal.reply_as_human",
                        lambda t, chat, text: (sent.append((t, chat, text)) or (True, "sent")),
                        raising=False)
    import wa_personal
    monkeypatch.setattr(wa_personal, "reply_as_human",
                        lambda t, chat, text: (sent.append((t, chat, text)) or (True, "sent")))

    budget = {"left": 2}
    cfg = ss.MessagingConfig(dry_run=False, wa_personal_tenant="t1",
                             wa_personal_budget=budget)
    ok, reason = ss.send_whatsapp("+62 812-345-678", "hello", cfg, {})
    assert ok and reason == "sent"
    assert sent[0][1].endswith("@c.us") and budget["left"] == 1

    budget["left"] = 0
    ok2, reason2 = ss.send_whatsapp("+62812345678", "hello", cfg, {})
    assert not ok2 and reason2 == "wa_personal_budget_exhausted"


def test_personal_dry_run_spends_budget_but_sends_nothing():
    import saas_senders as ss
    budget = {"left": 1}
    cfg = ss.MessagingConfig(dry_run=True, wa_personal_tenant="t1",
                             wa_personal_budget=budget)
    ok, reason = ss.send_whatsapp("+62812345678", "hello", cfg, {})
    assert ok and reason == "dry_run" and budget["left"] == 0


def test_personal_requires_explicit_automation_flag():
    """WORKING-сессии мало: без тумблера wa_personal_automation канал в
    цепочки не попадает."""
    import saas_senders as ss
    e, m = ss.EmailConfig.from_env(), ss.MessagingConfig.from_env()

    def fake_channels(tc):
        import saas_senders
        return lambda t: tc
    import saas_senders
    orig = saas_senders.load_tenant_channels
    try:
        saas_senders.load_tenant_channels = lambda t: {
            "wa_personal_status": "WORKING"}
        _e, m1 = ss.tenant_configs("t1", e, m)
        assert m1.wa_personal_tenant == ""
        saas_senders.load_tenant_channels = lambda t: {
            "wa_personal_status": "WORKING", "wa_personal_automation": True}
        _e, m2 = ss.tenant_configs("t1", e, m)
        assert m2.wa_personal_tenant == "t1"
    finally:
        saas_senders.load_tenant_channels = orig


def test_waha_target_resolves_per_tenant(monkeypatch, tmp_path):
    """WAHA free = одна сессия на инстанс: тенант с waha_url/waha_api_key в
    tenants.json ходит в СВОЙ контейнер, остальные - в платформенный из env."""
    import channels_admin as ca
    import wa_personal as wap

    f = tmp_path / "tenants.json"
    f.write_text(json.dumps({"simbago": {
        "waha_url": "http://waha-simbago:3000/",     # хвостовой / срезается
        "waha_api_key": " sk-simba "}}))             # пробелы срезаются
    monkeypatch.setattr(ca, "TENANTS_FILE", str(f))
    monkeypatch.setattr(wap, "WAHA_URL", "http://waha:3000")
    monkeypatch.setattr(wap, "WAHA_API_KEY", "platform-key")

    assert wap.waha_target("simbago") == ("http://waha-simbago:3000", "sk-simba")
    # hubcontent без waha_* в конфиге - прежнее поведение (env)
    assert wap.waha_target("hubcontent") == ("http://waha:3000", "platform-key")
    # tenants.json недоступен - тоже env-фолбэк, а не падение
    monkeypatch.setattr(ca, "TENANTS_FILE", str(tmp_path / "nope.json"))
    assert wap.waha_target("simbago") == ("http://waha:3000", "platform-key")


def test_waha_calls_hit_the_tenant_instance(monkeypatch):
    """HTTP-вызовы реально уходят на инстанс тенанта и с его ключом."""
    import wa_personal as wap

    seen = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"status": "WORKING", "me": {"id": "62812@c.us"}}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["key"] = req.get_header("X-api-key")
        return _Resp()

    monkeypatch.setattr(
        wap, "waha_target",
        lambda t: ("http://waha-simbago:3000", "sk-simba")
        if t == "simbago" else ("http://waha:3000", "env-key"))
    monkeypatch.setattr(wap.urllib.request, "urlopen", fake_urlopen)

    ok, status, number = wap.get_status("simbago")
    assert ok and status == "WORKING" and number == "62812"
    assert seen["url"].startswith(
        "http://waha-simbago:3000/api/sessions/tenant_simbago")
    assert seen["key"] == "sk-simba"

    wap.get_status("hubcontent")
    assert seen["url"].startswith("http://waha:3000/api/sessions/")
    assert seen["key"] == "env-key"


def test_dunning_and_triggers_have_wa_ladder():
    import json
    from pathlib import Path
    conf = json.loads((Path(__file__).parent.parent / "saas_campaigns.json")
                      .read_text())["_default"]
    for c in conf["campaigns"]:
        if c["campaign_id"].startswith(("K3", "T1", "T2", "T3")):
            email_steps = [s for s in c["steps"] if s.get("action") == "email"]
            assert email_steps and all(
                (s.get("channels") or [""])[0] == "whatsapp"
                and "email" in (s.get("channels") or []) for s in email_steps), \
                c["campaign_id"]
