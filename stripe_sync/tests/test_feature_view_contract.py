"""Контракт витрины фич: колонки, которые читают scoring/карточка/user_actions,
обязаны присутствовать. Статическая проверка saas_schema.sql - чтобы правка
большой вьюхи не уронила фичу молча (без CH)."""

from pathlib import Path

SCHEMA = (Path(__file__).resolve().parent.parent.parent / "saas_schema.sql").read_text()


def _view(name: str) -> str:
    marker = f"CREATE OR REPLACE VIEW retention.{name} AS"
    i = SCHEMA.index(marker)
    j = SCHEMA.index(";", i)
    return SCHEMA[i:j]


# Колонки по concern'ам - тот же список, что потребляют scoring.FEATURE_QUERY
# и api/saas.py. Пропажа любой = тихо сломанный скоринг/карточка.
EXPECTED = {
    "usage": ["generations_total", "generations_7d", "generations_prev_7d",
              "gen_days_this_month", "paywall_views", "checkout_starts",
              "cancel_flow_14d", "tokens_spent_month", "first_seen", "last_seen"],
    "billing": ["last_payment_failed", "last_invoice_paid", "last_cancel_scheduled"],
    "behavior": ["rage_clicks_7d", "js_errors_7d", "active_sec_7d",
                 "active_sec_prev_7d"],
    "intent": ["pricing_visits", "visit_count", "downloads_14d"],
    "performance": ["inp_ms", "lcp_ms"],
    "context": ["geo_country", "os_family", "device_type", "gpu",
                "device_model", "apple_pay", "datacenter"],
}


def test_feature_view_exposes_all_concerns():
    view = _view("user_event_features")
    missing = [(concern, col) for concern, cols in EXPECTED.items()
               for col in cols if f"AS {col}" not in view]
    assert not missing, f"витрина потеряла фичи: {missing}"


def test_feature_view_reads_deduped_single_pass():
    """Один проход по дедуп-вьюхе, не инлайн-подзапрос и не N джойнов."""
    view = _view("user_event_features")
    assert "FROM retention.saas_events_deduped" in view
    assert view.count("GROUP BY") == 1        # единственная агрегация


def test_dedup_view_exists_and_collapses_by_event_id():
    view = _view("saas_events_deduped")
    assert "GROUP BY tenant_id, identity_id, event_id" in view
    assert "FROM retention.saas_events_resolved" in view
