"""Предполётный чеклист: проверки человечности и целостности перед запуском."""

from launch_check import (check_copy, check_offers_bound, check_sender,
                          manual_items, verdict)


def test_sender_human_vs_noreply():
    assert check_sender("Michael from Hubcontent <care@h.ai>")["status"] == "pass"
    assert check_sender("Hubcontent <care@h.ai>")["status"] == "warn"   # бренд ок, личное лучше
    assert check_sender("noreply@h.ai")["status"] == "fail"
    assert check_sender("Support <no-reply@h.ai>")["status"] == "fail"
    assert check_sender("")["status"] == "fail"


def test_copy_catches_bad_placeholder_and_dash():
    conf = {"campaigns": [{"campaign_id": "K1", "steps": [
        {"action": "email", "subject": "Hi {{first_name}}", "body": "x"},
        {"action": "email", "subject": "ok", "body": "text — with dash",
         "cta_url": "https://x", "cta_label": ""},
        {"action": "email", "subject": "ok", "body": "fine {{app_url}}"},
    ]}]}
    by_key = {c["key"]: c for c in check_copy(conf)}
    assert by_key["placeholders"]["status"] == "fail"
    assert "K1#0" in by_key["placeholders"]["detail"]
    assert by_key["dashes"]["status"] == "warn"
    assert by_key["cta"]["status"] == "warn"


def test_copy_checks_variants_too():
    conf = {"campaigns": [{"campaign_id": "K1", "steps": [
        {"action": "email", "subject": "ok", "body": "ok",
         "variants": [{"subject": "b {{broken}}", "body": "x"}]}]}]}
    by_key = {c["key"]: c for c in check_copy(conf)}
    assert by_key["placeholders"]["status"] == "fail"


def test_offer_binding_check():
    conf = {"campaigns": [{"campaign_id": "K6", "steps": [
        {"action": "offer", "offer_id": ""}]}]}
    assert check_offers_bound(conf)["status"] == "warn"
    conf["campaigns"][0]["steps"][0]["offer_id"] = "O1"
    assert check_offers_bound(conf)["status"] == "pass"


def test_verdict_ladder():
    assert verdict([{"status": "pass"}]) == "ready"
    assert verdict([{"status": "pass"}, {"status": "manual"}]) == "almost"
    assert verdict([{"status": "warn"}]) == "almost"
    assert verdict([{"status": "manual"}, {"status": "fail"}]) == "not_ready"
    ms = manual_items({"dmarc": True})
    assert {m["key"]: m["status"] for m in ms}["dmarc"] == "pass"
    assert {m["key"]: m["status"] for m in ms}["reply_mailbox"] == "manual"


def test_signature_derived_from_sender():
    from email_delivery import signature_block, with_signature
    assert signature_block("Michael from Hubcontent <c@h.ai>") == "Michael\nHubcontent"
    assert signature_block("Hubcontent <c@h.ai>") == "The Hubcontent team"
    assert signature_block("") == ""
    body = with_signature("Hi! Try this.", "Michael from Hubcontent <c@h.ai>")
    assert body.endswith("Michael\nHubcontent")
    # автор подписался сам - не дублируем
    signed = "Hi!\n\nMichael\nHubcontent"
    assert with_signature(signed, "Michael from Hubcontent <c@h.ai>") == signed
