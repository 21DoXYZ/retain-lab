"""Методология текстов как код: каждый тест - одно правило §8."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copy_review import fatal, review_step  # noqa: E402

PROFILE = {"product_name": "hubcontent", "value_unit": "credits",
           "aha_moment": "Upload existing brief to generate concepts automatically.",
           "can_pause": False, "executors": ("stripe_coupon",),
    # факты планов - источник для check_numbers (v2)
    "plan_facts": "Pro gives 2.5x credits",
}


def codes(flags):
    return {f["code"] for f in flags}


def test_good_email_passes():
    f = review_step(
        "That brief on your desk is already a video",
        "Upload any client brief and hubcontent turns it into ready concepts "
        "in minutes - the work that normally eats an afternoon. Your trial "
        "credits are waiting: {{app_url}}\n\nStuck? Reply - a person reads this.",
        "K1_activation", "email", PROFILE)
    assert not fatal(f), f


def test_pause_promise_without_capability_is_fatal():
    """can_pause=false, а письмо обещает паузу - ложь на автопилоте."""
    f = review_step("Need a break?",
                    "Pause your plan and keep everything: {{app_url}}",
                    "K4_save", "email", PROFILE)
    assert "promises_pause_without_capability" in codes(f) and fatal(f)
    ok = review_step("Need a break?",
                     "Pause your plan and keep your credits: {{app_url}}",
                     "K4_save", "email", {**PROFILE, "can_pause": True})
    assert "promises_pause_without_capability" not in codes(ok)


def test_trial_extension_promise_is_fatal_without_executor():
    f = review_step("Good news", "We extended your trial: {{app_url}}",
                    "K2_trial_conversion", "email", PROFILE)
    assert "promises_trial_extension_without_capability" in codes(f)
    ok = review_step("Good news", "We extended your trial: {{app_url}}",
                     "K2_trial_conversion", "email",
                     {**PROFILE, "executors": ("trial_extend",)})
    assert "promises_trial_extension_without_capability" not in codes(ok)


def test_shouting_and_hype_are_fatal():
    f = review_step("Don't miss this!", "Act now: {{app_url}}",
                    "K2_trial_conversion", "email", PROFILE)
    assert {"shouting_exclamation", "hype_words"} <= codes(f)


def test_email_needs_exactly_one_action():
    f = review_step("Hi", "Just checking in about your credits.",
                    "K1_activation", "email", PROFILE)
    assert "no_action_link" in codes(f)
    f = review_step("Hi", "Open {{app_url}} or billing {{card_update_url}}.",
                    "K1_activation", "email", PROFILE)
    assert "many_actions" in codes(f)


def test_generic_filler_is_flagged():
    """Ни одного факта продукта - генерик, который не конвертит."""
    f = review_step("A quick note",
                    "We noticed you have not been around. Here is a link "
                    "to get back in and continue your journey: {{app_url}}",
                    "K1_activation", "email", PROFILE)
    assert "no_product_specificity" in codes(f)


def test_leaver_talk_outside_winback_is_fatal():
    f = review_step("Since you left",
                    "Since you left, your credits are waiting: {{app_url}}",
                    "K4_save", "email", PROFILE)
    assert "talks_to_leaver" in codes(f)


def test_installed_hubcontent_copy_passes_its_own_methodology():
    """Рукописный эталон обязан проходить собственный валидатор."""
    import json
    import urllib.request  # noqa: F401 - структурный импорт не нужен
    # локальная копия того, что установлено в overrides прода
    sample = {
        "K5_upgrade": ("You are close to your credit limit this month",
                       "You have burned through most of your monthly credits - "
                       "which means hubcontent is carrying real production for "
                       "you. Good problem.\n\nOn Pro you get 2.5x the credits, "
                       "so a heavy month never stalls mid-brief: {{app_url}}\n\n"
                       "Reply - a person will look at your numbers."),
        "K3_payment_recovery": ("Your payment did not go through - production is safe",
                                "Your last hubcontent payment did not go through - "
                                "usually an expired card or a limit. Every concept "
                                "and scenario is safe.\n\nUpdating your card takes "
                                "about 30 seconds: {{card_update_url}}"),
    }
    for cid, (subj, body) in sample.items():
        flags = review_step(subj, body, cid, "email", PROFILE)
        assert not fatal(flags), (cid, flags)


# ── v2: голос из contract-hunter + вечные правила retivo ─────────────────────

def _f(codes, flags):
    return [f for f in flags if f["code"] in codes]


def test_v2_ai_cliches_and_marketing_words_fatal():
    flags = review_step("hi", "I hope this finds you well. Try it: {{app_url}}",
                        "K1", "email", PROFILE)
    assert _f({"ai_cliche"}, flags) and fatal(flags)
    flags = review_step("hi", "We help you streamline production: {{app_url}}",
                        "K1", "email", PROFILE)
    assert _f({"marketing_word"}, flags) and fatal(flags)


def test_v2_unsourced_numbers_fatal_but_profile_and_placeholders_allowed():
    bad = review_step("hi", "Teams save 37% with us: {{app_url}}",
                      "K1", "email", PROFILE)
    assert _f({"unsourced_numbers"}, bad) and fatal(bad)
    ok = review_step("hi", "Pro gives 2.5x credits, takes 1 minute: {{app_url}}",
                     "K1", "email", PROFILE)
    assert not _f({"unsourced_numbers"}, ok)
    # цифры внутри URL/плейсхолдера не считаются
    ok2 = review_step("hi", "See https://x.co/2026/plan50 here: {{app_url}}",
                      "K1", "email", PROFILE)
    assert not _f({"unsourced_numbers"}, ok2)


def test_v2_rhythm_warns_do_not_block():
    body = ("This is a sentence that goes on and on and keeps adding words "
            "until it clearly crosses the twenty eight word ceiling that the "
            "naturalness rule from contract hunter enforces every time. "
            "Try it now: {{app_url}}")
    flags = review_step("hi", body, "K1", "email", PROFILE)
    assert _f({"sentence_over_28_words"}, flags)
    assert not fatal([f for f in flags if f["code"] == "sentence_over_28_words"])


def test_v2_caught_mistakes_forever():
    flags = review_step("hi", "You can unsubscribe below - {{app_url}}",
                        "K1", "email", PROFILE)
    codes = {f["code"] for f in flags}
    assert "unsubscribe_in_body" in codes
    flags = review_step("hi", "Great news — try it: {{app_url}}",
                        "K1", "email", PROFILE)
    assert "em_dash" in {f["code"] for f in flags}


def test_v2_sequence_repeat_fatal():
    from copy_review import review_sequence
    a = {"body": "Your project is one click from done and it takes a minute"}
    b = {"body": "Remember your project is one click from done and it takes"}
    flags = review_sequence([a, b])
    assert flags and flags[0]["code"] == "repeats_previous_step" and fatal(flags)
    assert review_sequence([a, {"body": "Totally different follow up text here"}]) == []
