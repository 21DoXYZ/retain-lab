"""Маппинг Stripe-событий в единую шину: контракт полей и краевые случаи."""

import json

from stripe_sync.mapper import email_hash, map_event, normalize_email, snapshot, ts_str

TENANT = "hubcontent"


def _evt(stripe_type, obj, evt_id="evt_1", created=1785830000):
    return {"id": evt_id, "type": stripe_type, "created": created,
            "data": {"object": obj}}


def test_normalize_and_hash():
    assert normalize_email("  User@Mail.COM ") == "user@mail.com"
    assert email_hash("User@Mail.COM") == email_hash("user@mail.com")
    assert email_hash("") == "" and email_hash(None) == ""


def test_ts_str_utc_ms():
    assert ts_str(1785830000) == "2026-08-04 07:53:20.000"
    assert ts_str(None) == ""


def test_payment_failed():
    row = map_event(_evt("invoice.payment_failed", {
        "id": "in_1", "customer": "cus_1", "subscription": "sub_1",
        "amount_due": 4900, "currency": "USD", "status": "open",
        "attempt_count": 2, "next_payment_attempt": 1785840000,
    }), TENANT)
    assert row["event_type"] == "billing.payment_failed"
    assert row["event_id"] == "stripe:evt_1"
    assert row["stripe_customer_id"] == "cus_1"
    assert row["invoice_id"] == "in_1" and row["subscription_id"] == "sub_1"
    assert row["amount"] == 49.0 and row["currency"] == "usd"
    assert json.loads(row["meta"])["attempt_count"] == 2


def test_subscription_created_plan_fields():
    sub = {"id": "sub_1", "customer": "cus_1", "status": "trialing",
           "items": {"data": [{"price": {
               "id": "price_1", "lookup_key": "pro_monthly",
               "unit_amount": 4900, "currency": "usd",
               "recurring": {"interval": "month"}}}]},
           "trial_end": 1786000000}
    row = map_event(_evt("customer.subscription.created", sub), TENANT)
    assert row["event_type"] == "billing.subscription_created"
    assert row["plan_id"] == "pro_monthly" and row["amount"] == 49.0
    assert json.loads(row["meta"])["interval"] == "month"


def test_subscription_cancel_scheduled_is_distinct():
    sub = {"id": "sub_1", "customer": "cus_1", "status": "active",
           "cancel_at_period_end": True, "items": {"data": []}}
    row = map_event(_evt("customer.subscription.updated", sub), TENANT)
    assert row["event_type"] == "billing.subscription_cancel_scheduled"


def test_checkout_completed_carries_identity_keys():
    row = map_event(_evt("checkout.session.completed", {
        "id": "cs_1", "customer": "cus_1", "subscription": "sub_1",
        "amount_total": 4900, "currency": "usd", "status": "complete",
        "customer_details": {"email": " Buyer@Mail.com "},
        "client_reference_id": "u_42",
    }), TENANT)
    assert row["email_hash"] == email_hash("buyer@mail.com")
    assert row["client_user_id"] == "u_42"
    assert row["session_id"] == "cs_1"


def test_unknown_type_returns_none():
    assert map_event(_evt("customer.created", {"id": "cus_1"}), TENANT) is None


def test_expanded_customer_object():
    row = map_event(_evt("charge.refunded", {
        "id": "ch_1", "customer": {"id": "cus_9"}, "invoice": "in_9",
        "amount": 4900, "amount_refunded": 4900, "currency": "usd",
        "status": "succeeded", "refunded": True,
    }), TENANT)
    assert row["stripe_customer_id"] == "cus_9"
    assert row["amount"] == 49.0 and row["status"] == "refunded"


def test_snapshot_subscription_and_invoice():
    sub = {"id": "sub_1", "customer": "cus_1", "status": "active",
           "items": {"data": [{"price": {"id": "price_1", "unit_amount": 9900,
                                          "currency": "usd",
                                          "recurring": {"interval": "year"}}}]},
           "current_period_start": 1785830000, "current_period_end": 1788508400,
           "created": 1785830000}
    table, row = snapshot(_evt("customer.subscription.updated", sub), TENANT)
    assert table == "stripe_subscriptions"
    assert row["bill_interval"] == "year" and row["amount"] == 99.0
    assert row["trial_start"] is None  # пустой ts → NULL, не ''

    table, row = snapshot(_evt("invoice.paid", {
        "id": "in_1", "customer": "cus_1", "subscription": "sub_1",
        "status": "paid", "amount_due": 4900, "amount_paid": 4900,
        "currency": "usd", "attempt_count": 1, "created": 1785830000,
    }), TENANT)
    assert table == "stripe_invoices" and row["amount_paid"] == 49.0

    # checkout без email/customer - снапшота нет
    assert snapshot(_evt("checkout.session.completed", {"id": "cs_1"}), TENANT) is None


def test_snapshot_checkout_bridges_open_email():
    table, row = snapshot(_evt("checkout.session.completed", {
        "id": "cs_1", "customer": "cus_demo_1",
        "customer_details": {"email": " DoDemo@Example.test ", "name": "Demo"},
    }), TENANT)
    assert table == "stripe_customers"
    assert row["customer_id"] == "cus_demo_1"
    assert row["email_norm"] == "dodemo@example.test"
    assert row["email_hash"] == email_hash("dodemo@example.test")
