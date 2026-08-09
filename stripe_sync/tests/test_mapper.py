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


def test_upgrade_is_not_any_subscription_change():
    """Успех кампании апгрейда - переход на тариф ДОРОЖЕ. Раньше засчитывалось
    любое изменение подписки, включая понижение: эффект выглядел бы дутым."""
    def evt(prev_cents, new_cents):
        return {"id": "evt_1", "type": "customer.subscription.updated", "created": 1,
                "data": {"object": {"id": "sub_1", "customer": "cus_1", "status": "active",
                                    "items": {"data": [{"price": {
                                        "id": "p2", "unit_amount": new_cents, "currency": "usd",
                                        "recurring": {"interval": "month"}, "product": "prod_1"}}]}},
                         "previous_attributes": {"items": {"data": [
                             {"price": {"unit_amount": prev_cents}}]}}}}

    assert map_event(evt(2900, 9900), "t")["event_type"] == "billing.subscription_upgraded"
    assert map_event(evt(9900, 2900), "t")["event_type"] == "billing.subscription_downgraded"
    # изменение, не касающееся цены, остаётся обычным обновлением
    other = {"id": "e", "type": "customer.subscription.updated", "created": 1,
             "data": {"object": {"id": "s", "customer": "c", "status": "active"},
                      "previous_attributes": {"metadata": {"x": "y"}}}}
    assert map_event(other, "t")["event_type"] == "billing.subscription_updated"


def test_client_clock_cannot_poison_the_windows():
    """Время события задаёт клиент: у браузера часы врут, сервер клиента может
    прислать что угодно. Событие «из будущего» иначе считалось бы свежим
    месяцами и держало человека в активных."""
    import pathlib
    import sys
    from datetime import datetime, timezone

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "ingest"))
    from event_time import sane_ts

    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    now_s = "2026-08-06 12:00:00.000"
    assert sane_ts("2026-08-06 11:59:00.000", now) == "2026-08-06 11:59:00.000"
    assert sane_ts("2027-01-01 00:00:00.000", now) == now_s      # будущее
    assert sane_ts("1999-01-01 00:00:00.000", now) == now_s      # древность
    assert sane_ts("не время", now) == now_s                     # мусор
    assert sane_ts(None, now) == now_s
    assert sane_ts("2026-08-06T11:00:00Z", now) == "2026-08-06 11:00:00.000"


def test_subscription_period_is_read_from_items():
    """Stripe перенёс период внутрь позиций подписки. Пока читали только
    верхний уровень, снапшот подписки падал при вставке - и КАЖДАЯ подписка
    клиента терялась: ни стадий, ни MRR, ни аудита утечек."""
    from stripe_sync.mapper import snapshot

    def evt(top_level: bool):
        item = {"price": {"id": "price_1", "unit_amount": 9900, "currency": "usd",
                          "recurring": {"interval": "month"}, "product": "prod_1"}}
        if not top_level:
            item["current_period_start"] = 1786000000
            item["current_period_end"] = 1788592000
        obj = {"id": "sub_1", "customer": "cus_1", "status": "active",
               "created": 1785000000, "items": {"data": [item]}}
        if top_level:
            obj["current_period_start"] = 1786000000
            obj["current_period_end"] = 1788592000
        return {"id": "e", "type": "customer.subscription.created",
                "created": 1786000000, "data": {"object": obj}}

    for top in (True, False):
        table, row = snapshot(evt(top), "t")
        assert table == "stripe_subscriptions"
        assert row["current_period_start"], f"пусто при top_level={top}"
        assert row["current_period_end"], f"пусто при top_level={top}"

    # совсем без периода: начало берём из даты создания, а не роняем подписку
    bare = {"id": "e", "type": "customer.subscription.created", "created": 1785000000,
            "data": {"object": {"id": "s", "customer": "c", "status": "active",
                                "created": 1785000000}}}
    _, row = snapshot(bare, "t")
    assert row["current_period_start"]


def test_customer_updated_snapshots_the_new_email():
    """Смена email в Stripe обязана доезжать: иначе письма уходят на старый
    адрес, а склейка держится за мёртвый hash."""
    from stripe_sync.mapper import normalize_email, snapshot
    evt = {"type": "customer.updated", "created": 1786000000,
           "data": {"object": {"id": "cus_9", "email": "New@Mail.Test",
                                "name": "Ann", "created": 1780000000}}}
    out = snapshot(evt, "t1")
    assert out is not None
    table, row = out
    assert table == "stripe_customers"
    assert row["customer_id"] == "cus_9"
    assert row["email_norm"] == normalize_email("New@Mail.Test")
    assert row["email_hash"] != ""
    # customer без email (гостевой) - строка есть, hash честно пуст
    evt["data"]["object"]["email"] = None
    _t, row2 = snapshot(evt, "t1")
    assert row2["email_hash"] == "" and row2["email_norm"] == ""


def test_payment_method_snapshots_card_expiry():
    """Срок карты - для перехвата невольного оттока (карта истечёт -> платёж
    не пройдёт). Источник - события payment_method.*"""
    from stripe_sync.mapper import snapshot
    evt = {"type": "payment_method.attached", "created": 1786000000,
           "data": {"object": {"id": "pm_1", "customer": "cus_7",
                               "card": {"brand": "visa", "last4": "4242",
                                        "exp_month": 3, "exp_year": 2027}}}}
    out = snapshot(evt, "t1")
    assert out is not None
    table, row = out
    assert table == "stripe_cards"
    assert row["customer_id"] == "cus_7" and row["last4"] == "4242"
    assert row["exp_month"] == 3 and row["exp_year"] == 2027
    # без карты/клиента - не снапшотим
    evt["data"]["object"]["card"] = None
    assert snapshot(evt, "t1") is None
