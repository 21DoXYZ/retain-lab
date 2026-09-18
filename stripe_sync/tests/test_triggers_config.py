"""Каждый триггер обязан иметь кампанию: TRIGGERS без кампании - мёртвый
код, кампания TRIGGER без триггера - мёртвый конфиг (fire() их сшивает)."""

import json
from pathlib import Path

from trigger_tick import TRIGGERS

_CONF = json.loads((Path(__file__).resolve().parents[1]
                    / "saas_campaigns.json").read_text())


def _trigger_campaigns() -> dict:
    return {c["campaign_id"]: c
            for c in _CONF["_default"]["campaigns"]
            if c.get("entry_stage") == "TRIGGER"}


def test_every_trigger_has_campaign():
    camps = _trigger_campaigns()
    missing = [cid for cid in TRIGGERS if cid not in camps]
    assert not missing, missing


def test_trigger_campaigns_are_manual_audience():
    """Стадии у TRIGGER-зачисленных нет - без manual_audience тик выкинет
    их exited на первом же проходе."""
    for cid, camp in _trigger_campaigns().items():
        assert camp.get("manual_audience"), cid


def test_trigger_steps_have_action_path():
    """Каждый email-шаг ведёт к действию: ссылка или просьба ответить."""
    for cid, camp in _trigger_campaigns().items():
        for i, st in enumerate(camp.get("steps", [])):
            if st.get("action") != "email":
                continue
            body = str(st.get("body") or "")
            ok = ("http" in body or "{{" in body
                  or "reply" in body.lower())
            assert ok, (cid, i)
