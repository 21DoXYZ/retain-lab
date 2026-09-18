"""Авто-мозг: плейбук обязан быть валидным до всякого запуска."""

from auto_improve import FOLLOW_UP_DELAY_H, MIN_SEGMENT, PLAYBOOK, playbook_steps
from segment import build, validate_steps


def test_playbook_audiences_valid():
    keys = [p["key"] for p in PLAYBOOK]
    assert len(keys) == len(set(keys))
    for pb in PLAYBOOK:
        _c, _p, unknown = build(dict(pb["audience"]))
        assert not unknown, f"{pb['key']}: {unknown}"


def test_playbook_copy_passes_validator():
    for pb in PLAYBOOK:
        steps, reason = validate_steps(playbook_steps(pb))
        assert not reason, f"{pb['key']}: {reason}"
        assert steps and pb["goal_event"]


def test_min_segment_sane():
    assert 10 <= MIN_SEGMENT <= 100


def test_playbook_has_follow_up():
    """Дожим через 4 дня: одно касание - недожатая последовательность."""
    assert 48 <= FOLLOW_UP_DELAY_H <= 168
    for pb in PLAYBOOK:
        steps = playbook_steps(pb)
        assert 2 <= len(steps) <= 3, pb["key"]
        assert steps[-1]["delay_h"] == FOLLOW_UP_DELAY_H
        if pb.get("inapp"):
            assert steps[1]["action"] == "inapp" and steps[1]["delay_h"] == 0


def test_playbook_subject_ab_variants():
    """A/B темы: два варианта на первом шаге, оба проходят методологию."""
    from copy_review import review_step
    for pb in PLAYBOOK:
        steps = playbook_steps(pb)
        variants = steps[0].get("variants") or []
        assert len(variants) == 2, pb["key"]
        assert variants[0]["subject"] != variants[1]["subject"]
        for v in variants:
            flags = review_step(v["subject"], steps[0]["body"], pb["key"],
                                "email", {})
            fatals = [f for f in flags if f["level"] == "fatal"]
            assert not fatals, (pb["key"], v["subject"], fatals)


def test_playbook_copy_passes_methodology_v2():
    """Мозг не имеет права запускать текст, который завалил copy_review."""
    from copy_review import review_sequence, review_step
    for pb in PLAYBOOK:
        flags = []
        for st in playbook_steps(pb):
            flags += review_step(st["subject"], st["body"], pb["key"],
                                 st.get("action", "email"), {})
        flags += review_sequence(playbook_steps(pb))
        fatals = [f for f in flags if f["level"] == "fatal"]
        assert not fatals, (pb["key"], fatals)
