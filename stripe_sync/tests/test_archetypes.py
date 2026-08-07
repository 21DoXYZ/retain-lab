"""Тип экономики по сайту: разбор уровня «видел таблицу себестоимости» для
бизнеса, про который известен только лендинг.

Сайт не назовёт себестоимость никогда. Но он выдаёт ТИП экономики, а тип
говорит, где лежит маржа, какой рычаг дешёвый и какие числа надо спросить.
Тексты ниже - сокращённые лендинги реальных категорий.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archetypes import (ARCHETYPES, assumed_margin, classify, lever_fit,  # noqa: E402
                        profile, questions_for, read)
from economics import build, unit_cost  # noqa: E402

VIDEO_AI = """Turn any idea into a ready-to-publish video. Every generation
costs credits. Creator gets 6000 credits per month, Pro 15000. Run out? Top up
with a credit pack anytime. Rendering happens on our GPU cluster."""

CLASSIC_SAAS = """The project tracker teams actually use. Unlimited projects,
all features included, 120+ integrations, automation and dashboards.
14-day free trial, no credit card required, cancel anytime."""

SEAT_B2B = """Design collaboration for product teams. $12 per editor / month.
Invite your team, manage workspace members with admin roles. SSO and SCIM on
the Enterprise plan."""

MARKETPLACE = """Hire vetted freelancers. We take a 12% commission on every
transaction. Become a seller and list your services to thousands of buyers."""

SHOP = """Free shipping on orders over $60. Add to cart, in stock, ships in 24
hours. Check the size guide. Free returns within 30 days."""

AGENCY = """We build brands that scale. Book a call and our team will map your
funnel. Monthly retainer, dedicated manager, onboarding call in week one.
See our case studies."""

INFRA = """Managed Postgres in 30 regions. $0.09 per GB of egress, billed per
request. Compute hours scale to zero. 99.99% uptime SLA."""


def test_every_category_is_recognised_from_its_landing_page():
    assert classify(VIDEO_AI)[0] == "ai_usage"
    assert classify(CLASSIC_SAAS)[0] == "software_saas"
    assert classify(SEAT_B2B)[0] == "per_seat_b2b"
    assert classify(MARKETPLACE)[0] == "marketplace"
    assert classify(SHOP)[0] == "ecommerce_physical"
    assert classify(AGENCY)[0] == "services"
    assert classify(INFRA)[0] == "infrastructure"


def test_classifier_shows_what_it_saw():
    kind, conf, hits = classify(VIDEO_AI)
    assert kind == "ai_usage" and conf > 0.5
    assert any("credit" in h or "gpu" in h for h in hits)


def test_big_included_limits_betray_usage_pricing():
    """«6000 кредитов» - это не «5 проектов»: крупный лимит выдаёт потребление."""
    plans = [{"name": "Pro", "price_usd": 99, "units_included": 15000}]
    plain = "A tool for teams. Simple monthly pricing."
    assert classify(plain)[0] != "ai_usage"
    assert classify(plain, {"plans": plans})[0] == "ai_usage"


def test_empty_site_falls_back_to_the_safest_type():
    kind, conf, hits = classify("")
    assert kind == "software_saas" and conf == 0.0 and hits == []


def test_each_type_knows_which_lever_is_cheap():
    """Один и тот же подарок в разных моделях стоит по-разному - это и есть суть."""
    assert lever_fit("ai_usage", "bonus_units") == "costly"
    assert lever_fit("software_saas", "bonus_units") == "cheap"
    assert lever_fit("software_saas", "discount") == "costly"
    assert lever_fit("ai_usage", "topup_discount") == "cheap"
    assert lever_fit("per_seat_b2b", "discount") == "costly"


def test_each_type_asks_only_the_numbers_that_change_its_maths():
    assert "unit_cost_usd" in questions_for("ai_usage")
    assert "topup_price" in questions_for("ai_usage")
    # у классического софта себестоимость юнита не нужна - хватает маржи
    assert questions_for("software_saas") == ["gross_margin_pct"]
    # уже отвеченное второй раз не спрашиваем
    assert questions_for("software_saas", {"gross_margin_pct": 85}) == []


def test_assumed_margin_beats_assuming_zero():
    """Подставить цену вместо себестоимости - это тихо допустить «маржа ноль».

    Для обычного софта это завышает стоимость подарка в разы и заставляет
    систему отказываться от нормальных офферов.
    """
    price_per_unit = 0.05
    blind, basis_blind = unit_cost({}, price_per_unit)
    smart, basis_smart = unit_cost({"cost_archetype": "software_saas"}, price_per_unit)
    assert (blind, basis_blind) == (0.05, "price")
    assert basis_smart == "assumed" and smart == 0.00875
    assert blind / smart > 5


def test_assumption_is_labelled_in_every_verdict_not_just_the_summary():
    econ = build([{"name": "Pro", "price_usd": 99, "units_included": 15000}],
                 {"cost_archetype": "ai_usage", "max_discount_pct": 20,
                  "monthly_units": 15000})
    assert econ["cost_basis"] == "assumed"
    assert econ["cost_archetype"] == "ai_usage"
    assert all(l["basis"] == "assumed" for l in econ["levers"].values())
    # предположение не выдаётся за факт: число всё ещё числится недостающим
    assert "валовая маржа или себестоимость юнита" in econ["missing"]


def test_owner_answer_overrides_the_assumption():
    econ = build([{"name": "Pro", "price_usd": 99, "units_included": 15000}],
                 {"cost_archetype": "ai_usage", "gross_margin_pct": 10,
                  "max_discount_pct": 20, "monthly_units": 15000})
    assert econ["cost_basis"] == "margin" and econ["gross_margin"] == 0.1
    assert "валовая маржа или себестоимость юнита" not in econ["missing"]


def test_read_merges_the_model_answer_with_the_site_signals():
    both = read(VIDEO_AI, None, {"cost_archetype": "ai_usage"})
    assert both["archetype"] == "ai_usage" and "сошлись" in both["agreement"]

    # признаков мало - доверяем модели
    thin = read("Welcome to our platform.", None, {"cost_archetype": "marketplace"})
    assert thin["archetype"] == "marketplace" and "мало" in thin["agreement"]

    # признаки весомые и противоречат модели - берём признаки, но говорим об этом
    argued = read(SHOP, None, {"cost_archetype": "software_saas"})
    assert argued["archetype"] == "ecommerce_physical"
    assert "весомее" in argued["agreement"]


def test_read_returns_a_usable_card_for_the_screen():
    card = read(VIDEO_AI)
    assert card["label"] == "оплата за генерацию"
    assert card["margin_band_pct"] == [10, 40]
    assert card["margin_in"] == "overage"
    assert "bonus_units" in card["costly_levers"]
    assert card["never"] and card["why"]


def test_no_archetype_promises_a_margin_it_cannot_hold():
    for kind, card in ARCHETYPES.items():
        low, high = card["margin_band"]
        assert 0 < low < high < 1, kind
        assert card["ask"] and card["why"], kind
        assert set(card["cheap"]).isdisjoint(card["costly"]), kind
        assert 0 < assumed_margin(kind) < 1, kind
        assert profile(kind)["label"], kind
