"""Продуктовые гипотезы: валидатор отбрасывает выдумки, опросы - в конфиге."""

from product_insights import validate_hypotheses


FACTS = {"friction_pages": [{"page": "/projects/x/studio", "rage_clicks": 14}],
         "voice": [{"text": "Механика дрифта сломана в студии"}],
         "funnel": {"signed_up": 500, "got_value": 196}}


def test_grounded_hypothesis_passes():
    kept, rejected = validate_hypotheses([{
        "theme": "Студия фрустрирует",
        "hypothesis": "Юзеры застревают на /projects/x/studio",
        "suggested_change": "Починить механику дрифта в студии",
        "evidence": ["/projects/x/studio", "Механика дрифта сломана"]}], FACTS)
    assert len(kept) == 1 and rejected == 0


def test_invented_evidence_is_rejected():
    kept, rejected = validate_hypotheses([{
        "theme": "Цены пугают",
        "hypothesis": "Слишком дорого",
        "suggested_change": "Скидка всем",
        "evidence": ["юзеры массово жалуются на цену", "отток из-за тарифов"]}],
        FACTS)
    assert kept == [] and rejected == 1


def test_incomplete_hypothesis_is_rejected():
    kept, rejected = validate_hypotheses(
        [{"theme": "x", "hypothesis": "", "suggested_change": "y",
          "evidence": ["z"]}], FACTS)
    assert kept == [] and rejected == 1


def test_nps_survey_campaign_config():
    import json
    from pathlib import Path
    conf = json.loads((Path(__file__).parent.parent / "saas_campaigns.json")
                      .read_text())["_default"]
    t4 = next(c for c in conf["campaigns"] if c["campaign_id"] == "T4_nps")
    assert t4["entry_stage"] == "TRIGGER" and t4["reentry_days"] == 90
    step = t4["steps"][0]
    assert step["action"] == "inapp" and step["survey"] == "nps"
    from trigger_tick import TRIGGERS
    assert "T4_nps" in TRIGGERS and "%(t)s" in TRIGGERS["T4_nps"]


def test_inapp_row_carries_kind():
    from datetime import datetime
    from campaign_tick import INAPP_COLUMNS, inapp_row
    camp = {"campaign_id": "T4_nps", "entry_stage": "TRIGGER"}
    step = {"action": "inapp", "survey": "nps", "subject": "Q", "body": "B"}
    row = inapp_row("t", camp, step, 0, "id1", "u1", datetime(2026, 1, 1), {})
    assert len(row) == len(INAPP_COLUMNS)
    assert row[INAPP_COLUMNS.index("kind")] == "nps"
    row2 = inapp_row("t", camp, {"action": "inapp", "subject": "Q", "body": "B"},
                     0, "id1", "u1", datetime(2026, 1, 1), {})
    assert row2[INAPP_COLUMNS.index("kind")] == "banner"
