"""Предложения по офферам: каждое обязано опираться на факты из данных."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offer_suggest import suggest  # noqa: E402

COMPOSED = [
    {"offer_id": "A_pause_1m", "role": "save", "title": "Пауза на месяц",
     "monetary": False, "cost_estimate": 0},
    {"offer_id": "A_discount20", "role": "upgrade", "title": "Скидка 20%",
     "monetary": True, "cost_estimate": 9.8},
    {"offer_id": "A_trial_plus7", "role": "conversion", "title": "+7 дней триала",
     "monetary": False, "cost_estimate": 0},
]


def test_stage_with_people_but_no_offer_is_top_priority():
    """Люди на стадии есть, предложить нечего - это прямая потеря денег."""
    out = suggest(catalog=[{"offer_id": "A_x", "role": "activation"}],
                  stages={"SAVE": 12, "CONVERT": 3},
                  stage_value={"SAVE": 1188.0, "CONVERT": 297.0},
                  rejects={}, answers={}, avg_price=99.0, composed=COMPOSED)
    ids = [s["id"] for s in out]
    assert ids[0] == "role_gap:save"          # где денег больше - то и первым
    assert "role_gap:conversion" in ids
    assert "12 чел." in out[0]["why"] and "$1,188" in out[0]["why"]
    assert out[0]["offer"]["offer_id"] == "A_pause_1m"


def test_no_suggestion_without_people():
    """Пустая стадия - не повод что-то предлагать."""
    out = suggest(catalog=[{"offer_id": "A_x", "role": "activation"}],
                  stages={"SAVE": 0}, stage_value={}, rejects={},
                  answers={}, avg_price=99.0, composed=COMPOSED)
    assert [s for s in out if s["id"].startswith("role_gap")] == []


def test_cap_hits_become_a_concrete_raise():
    """Отказы по своему же лимиту - предлагаем поднять его на единицу."""
    catalog = [{"offer_id": "A_discount20", "role": "upgrade", "title": "Скидка 20%",
                "max_per_user_30d": 1, "cost_estimate": 9.8, "monetary": True}]
    out = suggest(catalog=catalog, stages={}, stage_value={},
                  rejects={("A_discount20", "offer_limit_30d"): 5},
                  answers={}, avg_price=99.0, composed=COMPOSED)
    cap = next(s for s in out if s["kind"] == "raise_cap")
    assert cap["offer"]["max_per_user_30d"] == 2
    assert "5 раз" in cap["why"]


def test_below_threshold_cap_hits_are_noise():
    out = suggest(catalog=[{"offer_id": "A_d", "role": "upgrade", "max_per_user_30d": 1}],
                  stages={}, stage_value={},
                  rejects={("A_d", "offer_limit_30d"): 1},
                  answers={}, avg_price=99.0, composed=COMPOSED)
    assert [s for s in out if s["kind"] == "raise_cap"] == []


def test_broken_executor_is_reported_as_fix_not_offer():
    """Нет адреса начисления - это не «добавь оффер», а «почини интеграцию»."""
    out = suggest(catalog=[{"offer_id": "A_bonus", "role": "activation"}],
                  stages={}, stage_value={},
                  rejects={("A_bonus", "callback_not_configured"): 7},
                  answers={}, avg_price=99.0, composed=COMPOSED)
    fix = next(s for s in out if s["kind"] == "fix")
    assert fix["offer"] is None and "адрес начисления" in fix["why"]


def test_free_lever_offered_when_only_money_levers_exist():
    """Если удерживаем только скидками - предлагаем сначала бесплатную паузу."""
    catalog = [{"offer_id": "A_discount20", "role": "upgrade", "monetary": True,
                "cost_estimate": 9.8}]
    out = suggest(catalog=catalog, stages={}, stage_value={}, rejects={},
                  answers={}, avg_price=99.0, composed=COMPOSED)
    cheap = next(s for s in out if s["id"] == "cheap_first:save")
    assert cheap["offer"]["offer_id"] == "A_pause_1m"


def test_empty_catalog_sends_to_the_questionnaire():
    out = suggest(catalog=[], stages={"MONITOR": 40}, stage_value={}, rejects={},
                  answers={}, avg_price=0.0, composed=COMPOSED)
    assert len(out) == 1 and out[0]["kind"] == "questionnaire"
    assert "40 чел." in out[0]["why"]
