"""Авто-мозг: плейбук обязан быть валидным до всякого запуска."""

from auto_improve import MIN_SEGMENT, PLAYBOOK
from segment import build, validate_steps


def test_playbook_audiences_valid():
    keys = [p["key"] for p in PLAYBOOK]
    assert len(keys) == len(set(keys))
    for pb in PLAYBOOK:
        _c, _p, unknown = build(dict(pb["audience"]))
        assert not unknown, f"{pb['key']}: {unknown}"


def test_playbook_copy_passes_validator():
    for pb in PLAYBOOK:
        steps, reason = validate_steps([
            {"action": "email", "subject": pb["subject"], "body": pb["body"],
             "cta_label": "Open the app", "delay_h": 0}])
        assert not reason, f"{pb['key']}: {reason}"
        assert steps and pb["goal_event"]


def test_min_segment_sane():
    assert 10 <= MIN_SEGMENT <= 100
