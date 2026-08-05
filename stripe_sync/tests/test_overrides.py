"""Правки кампаний/офферов из CRM: мерж поверх базы + атомарный стор."""

import json

from stripe_sync import overrides as ovr


BASE_CONF = {"campaigns": [{
    "campaign_id": "K3", "entry_stage": "DUNNING",
    "steps": [{"delay_h": 0, "action": "email", "subject": "base subj",
               "body": "base body"},
              {"delay_h": 24, "action": "email", "subject": "s2", "body": "b2"}],
}]}

CATALOG = {"control_pct": 10, "offers": [{
    "offer_id": "O1", "title": "+100 tokens", "executor": "client_callback",
    "monetary": True, "cost_estimate": 0.5, "max_per_user_30d": 2,
    "params": {"tokens": 100, "expires_days": 14, "command": "token_credit"},
}]}


def test_merge_campaign_text_and_delay():
    ov = {"campaigns": {"K3": {"steps": {"0": {"body": "новый текст", "delay_h": 2}}}}}
    out = ovr.merge_campaign_conf(BASE_CONF, ov)
    s0 = out["campaigns"][0]["steps"][0]
    assert s0["body"] == "новый текст" and s0["delay_h"] == 2.0 and s0["_edited"]
    # соседний шаг и база не тронуты
    assert out["campaigns"][0]["steps"][1]["body"] == "b2"
    assert BASE_CONF["campaigns"][0]["steps"][0]["body"] == "base body"


def test_merge_campaign_ignores_bad_index():
    out = ovr.merge_campaign_conf(BASE_CONF, {"campaigns": {"K3": {"steps": {"9": {"body": "x"}}}}})
    assert all("_edited" not in s for s in out["campaigns"][0]["steps"])


def test_merge_catalog_params_whitelist():
    ov = {"offers": {"O1": {"max_per_user_30d": 1,
                            "params": {"tokens": 150, "hacked": 1}}}}
    out = ovr.merge_catalog(CATALOG, ov)
    o = out["offers"][0]
    assert o["max_per_user_30d"] == 1 and o["params"]["tokens"] == 150
    assert "hacked" not in o["params"] and o["_edited"]
    assert CATALOG["offers"][0]["params"]["tokens"] == 100


def test_store_roundtrip_and_reset(tmp_path):
    p = str(tmp_path / "overrides.json")
    ovr.set_campaign_step("hub", "K3", 0, {"body": "v1"}, path=p)
    ovr.set_offer("hub", "O1", {"params": {"tokens": 200}}, path=p)
    data = json.loads(open(p).read())
    assert data["hub"]["campaigns"]["K3"]["steps"]["0"]["body"] == "v1"
    assert data["hub"]["offers"]["O1"]["params"]["tokens"] == 200
    ovr.set_campaign_step("hub", "K3", 0, None, path=p)
    data = json.loads(open(p).read())
    assert data["hub"]["campaigns"] == {}
    assert ovr.load_tenant("hub", path=p)["offers"]["O1"]["params"]["tokens"] == 200
