"""ИИ-слой 2: аналитик результатов, разбор причин отмены, churn-гейт."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_analyst import parse_insights                    # noqa: E402
from cancel_reasons import extract_text, parse_classification  # noqa: E402
from hygiene import check_churn_floor                    # noqa: E402

CAMPS = {"K3_payment_recovery": 4, "K5_upgrade": 3}


# ── Аналитик: валидация рекомендаций ────────────────────────────────────────

def test_insights_accept_valid_and_reject_garbage():
    text = json.dumps({"insights": [
        {"campaign_id": "K3_payment_recovery", "step_idx": 2, "kind": "drop_step",
         "title": "Второе письмо не даёт прироста",
         "rationale": "target 42.9% против holdout 40.1% при n=120 - разница в пределах шума",
         "suggestion": {}},
        {"campaign_id": "K9_ghost", "step_idx": 0, "kind": "drop_step",
         "title": "x", "rationale": "y", "suggestion": {}},          # нет кампании
        {"campaign_id": "K5_upgrade", "step_idx": 9, "kind": "drop_step",
         "title": "x", "rationale": "y", "suggestion": {}},          # шага нет
        {"campaign_id": "K5_upgrade", "step_idx": 0, "kind": "delete_everything",
         "title": "x", "rationale": "y", "suggestion": {}},          # вид не из списка
    ]})
    out, rejected = parse_insights(text, CAMPS)
    assert len(out) == 1 and out[0]["campaign_id"] == "K3_payment_recovery"
    assert any("unknown_campaign" in r for r in rejected)
    assert any("step_out_of_range" in r for r in rejected)
    assert any("unknown_kind" in r for r in rejected)


def test_insights_validate_suggestion_bounds():
    def one(kind, sug):
        return json.dumps({"insights": [{"campaign_id": "K5_upgrade", "step_idx": 0,
                                         "kind": kind, "title": "t",
                                         "rationale": "r", "suggestion": sug}]})
    ok, _ = parse_insights(one("change_delay", {"delay_h": 48}), CAMPS)
    assert ok[0]["suggestion"]["delay_h"] == 48.0
    bad, rej = parse_insights(one("change_delay", {"delay_h": 5000}), CAMPS)
    assert not bad and any("delay_out_of_range" in r for r in rej)
    bad2, rej2 = parse_insights(one("raise_cap", {"max_per_user_30d": 999}), CAMPS)
    assert not bad2 and any("cap_out_of_range" in r for r in rej2)


def test_insights_strip_em_dash():
    text = json.dumps({"insights": [{"campaign_id": "K5_upgrade", "step_idx": -1,
                                     "kind": "no_action", "title": "Мало данных—ждём",
                                     "rationale": "n=4—недостаточно", "suggestion": {}}]})
    out, _ = parse_insights(text, CAMPS)
    assert "—" not in out[0]["title"] and "—" not in out[0]["rationale"]


# ── Причины отмены ──────────────────────────────────────────────────────────

def test_extract_text_picks_first_nonempty_field():
    assert extract_text('{"text":"слишком дорого"}') == "слишком дорого"
    assert extract_text('{"reason":"нашёл дешевле"}') == "нашёл дешевле"
    assert extract_text('{"other":"x"}') == ""
    assert extract_text("не json") == ""


def test_classification_rejects_foreign_ids_and_categories():
    text = json.dumps({"items": [
        {"id": "e1", "category": "price", "summary": "дорого для текущего бюджета"},
        {"id": "e2", "category": "magic", "summary": "x"},
        {"id": "e9", "category": "price", "summary": "чужой id"},
    ]})
    out, rejected = parse_classification(text, {"e1", "e2"})
    assert set(out) == {"e1"} and out["e1"][0] == "price"
    assert any("unknown_category" in r for r in rejected)
    assert any("unknown_id" in r for r in rejected)


# ── Churn-гейт: скор наконец влияет на решение ──────────────────────────────

def test_churn_floor_blocks_money_for_calm_payers():
    money = {"monetary": True}
    free = {"monetary": False}
    calm = {"sub_status": "active", "p_churn": 0.1}
    risky = {"sub_status": "active", "p_churn": 0.6}

    assert check_churn_floor(money, calm, 0.25) == (False, "low_churn_risk")
    assert check_churn_floor(money, risky, 0.25)[0] is True
    assert check_churn_floor(free, calm, 0.25)[0] is True          # немонетарный можно
    assert check_churn_floor(money, calm, 0.0)[0] is True          # гейт выключен
    assert check_churn_floor(money, {"sub_status": "trialing", "p_churn": 0.0}, 0.25)[0] is True
    assert check_churn_floor(money, {"sub_status": "active"}, 0.25)[0] is True  # скора нет


def test_leaver_voice_dropped_outside_winback():
    """«Since you left» в SAVE - фактическая ошибка: юзер ещё платит. Такой шаг
    выбрасывается, остаётся детерминированный шаблон. В K6 та же фраза легальна."""
    from stripe_sync.ai_compose import parse_ai_copy
    doc = {
        "K4_save": {
            "1": {"subject": "Pause instead", "body": "You can pause for a month."},
            "2": {"subject": "Your work", "body": "Since you left we added new charts."},
        },
        "K6_winback": {
            "0": {"subject": "What is new", "body": "Since you left we added new charts."},
        },
    }
    out = parse_ai_copy(json.dumps(doc))
    assert set(out["K4_save"]) == {1}
    assert set(out["K6_winback"]) == {0}


def test_leaver_detector_ignores_case_and_spacing():
    from stripe_sync.ai_compose import _talks_to_leaver
    assert _talks_to_leaver("Welcome   BACK to the product")
    assert not _talks_to_leaver("Come back to the dashboard when ready")
