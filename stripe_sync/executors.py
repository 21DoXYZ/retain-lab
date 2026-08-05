"""Исполнители офферов (Phase 3): Stripe Level C + tenant callback Level A.

Контракт: execute(executor, offer, user, cfg) -> (ok, detail). DRY_RUN
(SIGNALS_DRY_RUN, дефолт 1 — как chains/senders.py): в сеть ничего не уходит,
payload печатается, возвращается (True, 'dry_run'). Реальный режим: Stripe —
по STRIPE_API_KEY; callback — POST на CALLBACK_URL c Bearer CALLBACK_TOKEN
(паттерн bonus_grant, но на stdlib urllib — без внешних зависимостей).

Билдеры payload — чистые функции (юнит-тестируются без сети).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

_RETRIES = 3
_TIMEOUT = 30


@dataclass(frozen=True)
class ExecConfig:
    dry_run: bool = True
    stripe_api_key: str = ""
    callback_url: str = ""
    callback_token: str = ""

    @classmethod
    def from_env(cls) -> "ExecConfig":
        return cls(
            dry_run=os.environ.get("SIGNALS_DRY_RUN", "1") not in ("0", "false", "False", ""),
            stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip(),
            callback_url=os.environ.get("CALLBACK_URL", "").strip(),
            callback_token=os.environ.get("CALLBACK_TOKEN", "").strip(),
        )


# ── чистые билдеры payload ────────────────────────────────────────────────────

def build_coupon(offer: dict) -> dict:
    p = offer["params"]
    coupon: dict[str, Any] = {"percent_off": p["percent_off"], "duration": p["duration"]}
    if p["duration"] == "repeating":
        coupon["duration_in_months"] = p["duration_in_months"]
    return coupon


def build_trial_end(offer: dict, now_unix: int) -> int:
    return now_unix + int(offer["params"]["days"]) * 86400


def build_pause(offer: dict, now_unix: int) -> dict:
    resume = now_unix + int(offer["params"]["months"]) * 30 * 86400
    return {"behavior": "mark_uncollectible", "resumes_at": resume}


def build_balance_credit(offer: dict) -> dict:
    # отрицательная сумма = кредит в пользу клиента
    return {"amount": -int(round(float(offer["params"]["amount_usd"]) * 100)), "currency": "usd"}


def build_callback_body(offer: dict, user: dict, tenant_id: str) -> dict:
    body = {
        "tenant_id": tenant_id,
        "identity_id": user.get("identity_id", ""),
        "client_user_id": user.get("client_user_id", ""),
        "offer_id": offer["offer_id"],
    }
    body.update(offer["params"])   # command/tokens/feature/days/...
    return body


# ── исполнение ────────────────────────────────────────────────────────────────

def _post_callback(url: str, token: str, body: dict) -> tuple[bool, str]:
    data = json.dumps(body, separators=(",", ":")).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    last = ""
    for attempt in range(_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                if 200 <= resp.status < 300:
                    return True, f"http_{resp.status}"
                last = f"http_{resp.status}"
        except urllib.error.HTTPError as exc:
            last = f"http_{exc.code}"
            if 400 <= exc.code < 500:
                return False, last          # не ретраим клиентские ошибки
        except Exception as exc:            # сеть/таймаут — ретраим
            last = type(exc).__name__
        time.sleep(min(2 ** attempt, 5))
    return False, last


def execute(offer: dict, user: dict, tenant_id: str, cfg: ExecConfig) -> tuple[bool, str]:
    executor = offer["executor"]
    now_unix = int(time.time())

    if executor == "client_callback":
        body = build_callback_body(offer, user, tenant_id)
        if cfg.dry_run:
            print(f"[offer dry_run] callback -> {json.dumps(body, separators=(',', ':'))}", flush=True)
            return True, "dry_run"
        if not cfg.callback_url:
            return False, "callback_not_configured"
        return _post_callback(cfg.callback_url, cfg.callback_token, body)

    # ── Stripe Level C ────────────────────────────────────────────────────────
    if executor == "stripe_coupon":
        payload = {"coupon": build_coupon(offer), "customer": user.get("stripe_customer_id", "")}
    elif executor == "trial_extend":
        payload = {"subscription": user.get("subscription_id", ""),
                   "trial_end": build_trial_end(offer, now_unix)}
    elif executor == "pause_collection":
        payload = {"subscription": user.get("subscription_id", ""),
                   "pause_collection": build_pause(offer, now_unix)}
    elif executor == "balance_credit":
        payload = {"customer": user.get("stripe_customer_id", ""),
                   **build_balance_credit(offer)}
    else:
        return False, f"unknown_executor:{executor}"

    if cfg.dry_run:
        print(f"[offer dry_run] {executor} -> {json.dumps(payload, separators=(',', ':'))}", flush=True)
        return True, "dry_run"
    if not cfg.stripe_api_key:
        return False, "stripe_not_configured"

    import stripe
    stripe.api_key = cfg.stripe_api_key
    try:
        if executor == "stripe_coupon":
            coupon = stripe.Coupon.create(**payload["coupon"])
            stripe.Customer.modify(payload["customer"], coupon=coupon.id)
            return True, f"coupon:{coupon.id}"
        if executor == "trial_extend":
            stripe.Subscription.modify(payload["subscription"], trial_end=payload["trial_end"],
                                       proration_behavior="none")
            return True, "trial_extended"
        if executor == "pause_collection":
            stripe.Subscription.modify(payload["subscription"],
                                       pause_collection=payload["pause_collection"])
            return True, "paused"
        if executor == "balance_credit":
            stripe.Customer.create_balance_transaction(
                payload["customer"], amount=payload["amount"], currency=payload["currency"])
            return True, "credited"
    except Exception as exc:
        return False, f"stripe_error:{type(exc).__name__}"
    return False, "unreachable"
