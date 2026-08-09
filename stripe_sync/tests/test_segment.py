"""Ручные кампании: сегмент по фильтрам, мерж в конфиг, поведение тика."""

from overrides import merge_campaign_conf
from segment import audience_sql, build, describe


def test_segment_stages_and_status():
    conds, params, unknown = build({"stages": ["DUNNING", "SAVE"],
                                    "status": "paying"})
    assert unknown == []
    assert "ua.stage IN ('DUNNING', 'SAVE')" in conds
    assert "ua.sub_status IN ('active', 'past_due')" in conds


def test_segment_dormant_includes_never_seen():
    """«Молчат 30 дней» обязан ловить и тех, кого не видели НИКОГДА."""
    conds, _p, _u = build({"not_seen_days": 30})
    assert any("toUnixTimestamp(ua.last_seen) = 0" in c for c in conds)


def test_segment_numbers_are_validated_not_injected():
    conds, _p, unknown = build({"mrr_min": "50", "churn_min": "боль",
                                "gens_max": 0})
    assert any("toFloat64(ua.mrr) >= 50.0" in c for c in conds)
    assert any("coalesce(f.generations_total, 0) <= 0.0" in c for c in conds)
    assert "churn_min" in unknown                  # мусор не молчит и не летит


def test_segment_country_whitelist():
    conds, _p, unknown = build({"country": "id"})
    assert any("f.geo_country = 'ID'" in c for c in conds)
    _c, _p2, unknown2 = build({"country": "1; DROP"})
    assert "country" in unknown2


def test_segment_unknown_stage_is_reported():
    _c, _p, unknown = build({"stages": ["КИТЫ"]})
    assert "stages" in unknown


def test_audience_sql_shape():
    conds, _p, _u = build({"status": "free"})
    sql = audience_sql(conds, limit=5)
    assert sql.startswith("SELECT ua.identity_id")
    assert "ua.tenant_id = {t:String}" in sql and sql.endswith("LIMIT 5")


def test_describe_is_human():
    d = describe({"stages": ["MONITOR"], "not_seen_days": 14, "status": "paying"})
    assert "MONITOR" in d and "quiet 14d+" in d and "paying" in d
    assert describe({}) == "all users"


def test_merge_adds_custom_campaign_with_manual_flags():
    conf = {"campaigns": [{"campaign_id": "K1", "entry_stage": "ACTIVATE",
                           "steps": []}]}
    ov = {"custom_campaigns": [
        {"campaign_id": "M_promo_1", "title": "Promo", "status": "active",
         "steps": [{"action": "email", "subject": "s", "body": "b", "delay_h": 0}]},
        {"campaign_id": "M_old", "status": "archived", "steps": []},
    ]}
    out = merge_campaign_conf(conf, ov)
    ids = [c["campaign_id"] for c in out["campaigns"]]
    assert "M_promo_1" in ids and "M_old" not in ids     # архив движку не виден
    custom = next(c for c in out["campaigns"] if c["campaign_id"] == "M_promo_1")
    assert custom["manual_audience"] and custom["_custom"]
    assert custom["entry_stage"] == "MANUAL"             # автозачисление молчит


def test_manual_campaign_never_autoenrolls():
    """Ни одна живая стадия не равна MANUAL - тик не дозачислит никого."""
    from campaign_tick import enroll_entry
    camp = {"campaign_id": "M_promo", "entry_stage": "MANUAL"}
    for stage in ("ACTIVATE", "CONVERT", "UPGRADE", "SAVE",
                  "DUNNING", "WINBACK", "MONITOR"):
        assert enroll_entry(camp, stage, 1.0, 1.0) == ""


def test_custom_steps_validation():
    from segment import validate_steps

    steps, reason = validate_steps([
        {"action": "email", "subject": "Hey — there", "body": "Text – here",
         "delay_h": 2, "cta_url": "https://x.co", "cta_label": "Open"}])
    assert reason == ""
    assert steps[0]["subject"] == "Hey - there"          # тире-правило в коде
    assert steps[0]["body"] == "Text - here"

    _s, r1 = validate_steps([])
    assert r1 == "steps_count"
    _s, r2 = validate_steps([{"action": "sms", "subject": "x", "body": "y"}])
    assert r2 == "step_0_channel"
    _s, r3 = validate_steps([{"action": "email", "subject": "", "body": "y"}])
    assert r3 == "step_0_empty"
    _s, r4 = validate_steps([{"action": "email", "subject": "s",
                              "body": "b", "cta_url": "javascript:x"}])
    assert r4 == "step_0_cta_url"


def test_segment_support_filters():
    """Сапорт-сигналы в фильтрах: жаловались/репортили баги за 30 дней."""
    conds, _p, unknown = build({"tickets_min": 2, "bugs_min": 1})
    assert unknown == []
    assert any("support_tickets_30d, 0) >= 2" in c for c in conds)
    assert any("bug_reports_30d, 0) >= 1" in c for c in conds)
