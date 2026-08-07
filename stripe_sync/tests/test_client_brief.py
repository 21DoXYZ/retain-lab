"""База знаний о клиенте: разбор, а не пересказ сайта."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from client_brief import answers_from_brief, diff_briefs, parse_brief  # noqa: E402


def test_parse_keeps_only_known_levers_and_marks_confidence():
    raw = json.dumps({
        "what_it_does": "Makes short videos from a text idea and exports them ready to post.",
        "who_for": "solo creators and small brand teams",
        "job_to_be_done": "publish consistently without a video editor",
        "value_unit": "Videos", "activation_moment": "first video exported",
        "value_event_hint": "Video Exported", "pricing_model": "usage",
        "churn_drivers": ["ran out of credits mid-month", "output quality below expectation"],
        "retention_levers": [{"lever": "bonus_units", "why": "credits run out", "fit": "high"},
                             {"lever": "телепатия", "why": "нет", "fit": "high"},
                             {"lever": "discount", "why": "last resort", "fit": "low"}],
        "never_offer": ["extra seats"], "confidence": "medium",
        "unknowns": ["does the plan reset monthly"],
    })
    b = parse_brief(raw)
    assert [x["lever"] for x in b["retention_levers"]] == ["bonus_units", "discount"]
    assert b["value_event_hint"] == "video_exported"
    assert b["value_unit"] == "videos"
    assert b["confidence"] == "medium"


def test_broken_answer_never_breaks_the_flow():
    assert parse_brief("модель ушла думать") == {}
    assert parse_brief('{"what_it_does": 5}')["what_it_does"] == "5"


def test_description_comes_from_analysis_not_from_the_landing():
    """В анкету должно попадать понятное описание, а не фраза с лендинга."""
    facts = {"product_name": "Hubcontent", "value_unit": "credits",
             "product_desc": "AI video production platform that turns ideas into content"}
    brief = {"what_it_does": "Makes short brand videos from a text idea.",
             "pricing_model": "usage"}
    out = answers_from_brief(brief, facts)
    assert out["product_desc"] == "Makes short brand videos from a text idea."
    assert out["value_unit"] == "credits"


def test_diff_shows_what_changed_on_re_analysis():
    """Клиент поменял тарифы - при повторном разборе это должно быть видно."""
    old = {"value_unit": "credits", "plans": [{"name": "Creator", "price_usd": 39},
                                              {"name": "Pro", "price_usd": 99}]}
    new = {"value_unit": "videos", "plans": [{"name": "Creator", "price_usd": 49},
                                             {"name": "Studio", "price_usd": 199}]}
    changes = {c["field"]: (c["was"], c["now"]) for c in diff_briefs(old, new)}
    assert changes["единица ценности"] == ("credits", "videos")
    assert changes["цена тарифа Creator"] == ("$39", "$49")
    assert changes["новый тариф"] == ("", "Studio: $199")
    assert changes["тариф убран"] == ("Pro", "")
    assert diff_briefs({}, new) == []
