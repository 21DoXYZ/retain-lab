"""Язык письма = язык юзера: выбор локали и подмена текста шага."""

from campaign_tick import apply_locale, locale_for


def test_locale_by_email_domain():
    assert locale_for("vasya@mail.ru", "") == "ru"
    assert locale_for("v@yandex.ru", "US") == "ru"   # домен сильнее гео
    assert locale_for("john@gmail.com", "") == "en"


def test_locale_by_geo():
    assert locale_for("john@gmail.com", "RU") == "ru"
    assert locale_for("john@gmail.com", "KZ") == "ru"
    assert locale_for("john@gmail.com", "DE") == "en"
    # Украина намеренно НЕ получает русский дефолт
    assert locale_for("john@gmail.com", "UA") == "en"


def test_locale_empty_inputs():
    assert locale_for("", "") == "en"
    assert locale_for("broken-address", "") == "en"


def test_apply_locale_swaps_text():
    step = {"subject": "hello", "body": "english body",
            "subject_ru": "привет", "body_ru": "русское тело",
            "cta_label": "Open"}
    ru = apply_locale(step, "ru")
    assert ru["subject"] == "привет" and ru["body"] == "русское тело"
    # исходный шаг не мутирует - другие юзеры того же тика видят оригинал
    assert step["subject"] == "hello"
    assert apply_locale(step, "en") is step


def test_apply_locale_without_translation_keeps_original():
    step = {"subject": "hello", "body": "english body"}
    assert apply_locale(step, "ru")["subject"] == "hello"


def test_playbook_ru_versions_pass_review():
    """Русские тексты плейбука проходят фильтр: тире, крик, ссылка, повтор."""
    from auto_improve import PLAYBOOK, playbook_steps
    from copy_review import review_sequence, review_step
    for pb in PLAYBOOK:
        steps = playbook_steps(pb)
        assert all(st.get("body_ru") for st in steps), pb["key"]
        flags = []
        for st in steps:
            flags += review_step(st["subject_ru"], st["body_ru"], pb["key"],
                                 st.get("action", "email"), {})
        flags += review_sequence([{"body": st["body_ru"]} for st in steps])
        fatals = [f for f in flags if f["level"] == "fatal"]
        assert not fatals, (pb["key"], fatals)


def test_validate_steps_keeps_ru_fields():
    from segment import validate_steps
    steps, reason = validate_steps([
        {"action": "email", "subject": "s", "body": "b http://x",
         "subject_ru": "тема — с тире", "body_ru": "тело", "delay_h": 0}])
    assert not reason
    assert steps[0]["subject_ru"] == "тема - с тире"   # em-dash вычищен
    assert steps[0]["body_ru"] == "тело"


def test_validate_steps_keeps_variants():
    from segment import validate_steps
    steps, reason = validate_steps([
        {"action": "email", "subject": "a", "body": "b http://x", "delay_h": 0,
         "variants": [{"subject": "a"}, {"subject": "b — dash"}]}])
    assert not reason
    vs = steps[0]["variants"]
    assert len(vs) == 2 and vs[1]["subject"] == "b - dash"
    # битые варианты молча отбрасываются целиком, шаг живёт
    steps2, reason2 = validate_steps([
        {"action": "email", "subject": "a", "body": "b http://x", "delay_h": 0,
         "variants": ["not-a-dict", {"subject": "x"}]}])
    assert not reason2 and "variants" not in steps2[0]
