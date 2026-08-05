"""Stripe → единая шина saas.events: чистые функции маппинга (без I/O).

Контракт события — retention.saas_events (saas_schema.sql), словарь типов —
Шпаргалка §1 "События биллинга". event_id = stripe:<evt_...> — повторная
доставка вебхука даёт тот же id, витрины дедупят по нему.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# Stripe event type → наш event_type. customer.subscription.updated разбирается
# отдельно в map_event (отмена по cancel_at_period_end — это своё событие).
EVENT_TYPES: dict[str, str] = {
    "invoice.payment_failed": "billing.payment_failed",
    "invoice.paid": "billing.invoice_paid",
    "customer.subscription.created": "billing.subscription_created",
    "customer.subscription.updated": "billing.subscription_updated",
    "customer.subscription.deleted": "billing.subscription_canceled",
    "checkout.session.completed": "billing.checkout_completed",
    "checkout.session.expired": "billing.checkout_abandoned",
    "charge.refunded": "billing.refund",
}


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def email_hash(email: str | None) -> str:
    norm = normalize_email(email)
    if not norm:
        return ""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def ts_str(unix_ts: int | float | None) -> str:
    """Unix-секунды → 'YYYY-MM-DD HH:MM:SS.mmm' (UTC), как ждёт DateTime64(3)."""
    if not unix_ts:
        return ""
    dt = datetime.fromtimestamp(float(unix_ts), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _amount(cents: int | None) -> float:
    return round((cents or 0) / 100.0, 2)


def _base(evt: dict[str, Any], tenant_id: str, event_type: str) -> dict[str, Any]:
    return {
        "event_id": f"stripe:{evt.get('id', '')}",
        "tenant_id": tenant_id,
        "event_type": event_type,
        "ts": ts_str(evt.get("created")),
        "source": "stripe",
        "client_user_id": "",
        "email_hash": "",
        "stripe_customer_id": "",
        "amount": 0.0,
        "currency": "",
        "plan_id": "",
        "subscription_id": "",
        "invoice_id": "",
        "charge_id": "",
        "status": "",
        "session_id": "",
        "page": "",
        "tokens_spent": 0,
        "tokens_balance": 0,
        "meta": "",
    }


def _customer_id(obj: dict[str, Any]) -> str:
    cust = obj.get("customer")
    if isinstance(cust, dict):
        return cust.get("id", "") or ""
    return cust or ""


def _sub_plan(sub: dict[str, Any]) -> tuple[str, str, float, str, str]:
    """(plan_id, price_id, amount, currency, interval) из items подписки."""
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return "", "", 0.0, "", ""
    price = items[0].get("price") or {}
    recurring = price.get("recurring") or {}
    return (
        price.get("lookup_key") or price.get("nickname") or price.get("id", "") or "",
        price.get("id", "") or "",
        _amount(price.get("unit_amount")),
        (price.get("currency") or "").lower(),
        recurring.get("interval") or "",
    )


def map_event(evt: dict[str, Any], tenant_id: str) -> dict[str, Any] | None:
    """Stripe Event (dict) → событие saas_events; None = тип не наш."""
    stripe_type = evt.get("type", "")
    our_type = EVENT_TYPES.get(stripe_type)
    if not our_type:
        return None

    obj: dict[str, Any] = (evt.get("data") or {}).get("object") or {}
    row = _base(evt, tenant_id, our_type)
    row["stripe_customer_id"] = _customer_id(obj)

    if stripe_type.startswith("invoice."):
        row["invoice_id"] = obj.get("id", "") or ""
        row["subscription_id"] = obj.get("subscription") or ""
        row["amount"] = _amount(
            obj.get("amount_due") if stripe_type == "invoice.payment_failed" else obj.get("amount_paid")
        )
        row["currency"] = (obj.get("currency") or "").lower()
        row["status"] = obj.get("status") or ""
        row["meta"] = json.dumps(
            {"attempt_count": obj.get("attempt_count", 0),
             "next_payment_attempt": obj.get("next_payment_attempt")},
            separators=(",", ":"),
        )

    elif stripe_type.startswith("customer.subscription."):
        plan_id, price_id, amount, currency, interval = _sub_plan(obj)
        row["subscription_id"] = obj.get("id", "") or ""
        row["plan_id"] = plan_id
        row["amount"] = amount
        row["currency"] = currency
        row["status"] = obj.get("status") or ""
        # отмена в конце периода приходит как .updated — размечаем отдельным типом
        if stripe_type == "customer.subscription.updated" and obj.get("cancel_at_period_end"):
            row["event_type"] = "billing.subscription_cancel_scheduled"
        row["meta"] = json.dumps(
            {"interval": interval, "price_id": price_id,
             "trial_end": obj.get("trial_end"),
             "cancel_at_period_end": bool(obj.get("cancel_at_period_end"))},
            separators=(",", ":"),
        )

    elif stripe_type.startswith("checkout.session."):
        details = obj.get("customer_details") or {}
        row["session_id"] = obj.get("id", "") or ""
        row["subscription_id"] = obj.get("subscription") or ""
        row["amount"] = _amount(obj.get("amount_total"))
        row["currency"] = (obj.get("currency") or "").lower()
        row["status"] = obj.get("status") or ""
        row["email_hash"] = email_hash(details.get("email") or obj.get("customer_email"))
        row["client_user_id"] = str(obj.get("client_reference_id") or "")

    elif stripe_type == "charge.refunded":
        row["charge_id"] = obj.get("id", "") or ""
        row["invoice_id"] = obj.get("invoice") or ""
        row["amount"] = _amount(obj.get("amount_refunded"))
        row["currency"] = (obj.get("currency") or "").lower()
        row["status"] = "refunded"

    return row


# ── Снапшоты объектов для stripe_* (вебхук держит raw-таблицы свежими) ────────

def snapshot(evt: dict[str, Any], tenant_id: str) -> tuple[str, dict[str, Any]] | None:
    """Stripe Event → (таблица, строка) для ReplacingMergeTree, или None."""
    stripe_type = evt.get("type", "")
    obj: dict[str, Any] = (evt.get("data") or {}).get("object") or {}
    now = ts_str(evt.get("created"))

    if stripe_type.startswith("customer.subscription."):
        plan_id, price_id, amount, currency, interval = _sub_plan(obj)
        return "stripe_subscriptions", {
            "tenant_id": tenant_id,
            "subscription_id": obj.get("id", "") or "",
            "customer_id": _customer_id(obj),
            "status": obj.get("status") or "",
            "plan_id": plan_id,
            "price_id": price_id,
            "amount": amount,
            "currency": currency,
            "bill_interval": interval,
            "current_period_start": ts_str(obj.get("current_period_start")),
            "current_period_end": ts_str(obj.get("current_period_end")),
            "trial_start": ts_str(obj.get("trial_start")) or None,
            "trial_end": ts_str(obj.get("trial_end")) or None,
            "cancel_at": ts_str(obj.get("cancel_at")) or None,
            "canceled_at": ts_str(obj.get("canceled_at")) or None,
            "created_ts": ts_str(obj.get("created")),
            "updated_at": now,
        }

    if stripe_type.startswith("invoice."):
        return "stripe_invoices", {
            "tenant_id": tenant_id,
            "invoice_id": obj.get("id", "") or "",
            "customer_id": _customer_id(obj),
            "subscription_id": obj.get("subscription") or "",
            "status": obj.get("status") or "",
            "amount_due": _amount(obj.get("amount_due")),
            "amount_paid": _amount(obj.get("amount_paid")),
            "currency": (obj.get("currency") or "").lower(),
            "attempt_count": int(obj.get("attempt_count") or 0),
            "next_payment_attempt": ts_str(obj.get("next_payment_attempt")) or None,
            "created_ts": ts_str(obj.get("created")),
            "updated_at": now,
        }

    if stripe_type == "charge.refunded":
        return "stripe_charges", {
            "tenant_id": tenant_id,
            "charge_id": obj.get("id", "") or "",
            "customer_id": _customer_id(obj),
            "invoice_id": obj.get("invoice") or "",
            "amount": _amount(obj.get("amount")),
            "currency": (obj.get("currency") or "").lower(),
            "status": obj.get("status") or "",
            "refunded": 1 if obj.get("refunded") else 0,
            "created_ts": ts_str(obj.get("created")),
            "updated_at": now,
        }

    return None
