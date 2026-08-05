"""Эвристический скоринг heur-v1 (Phase 2): прозрачные веса вместо ML.

Контракт под будущий ML (§0.5): вход — плоский dict фич (тот же, что пишется
в user_scores.features), выход — 4 скора. Веса — Шпаргалка §3; допущение v1:
горизонт LTV = 6 месяцев MRR (кривых когорт ещё нет — появятся с данными).
"""

from __future__ import annotations

VERSION = "heur-v1"
LTV_HORIZON_MONTHS = 6.0

PAYING_STATUSES = {"active", "past_due"}


def _clamp(x: float, lo: float = 0.01, hi: float = 0.95) -> float:
    return max(lo, min(hi, x))


def compute_scores(f: dict) -> dict:
    """f: фичи одной identity (см. scoring.py FEATURE_QUERY). Возвращает скоры."""
    status = f.get("sub_status") or ""
    paying = status in PAYING_STATUSES
    trialing = status == "trialing"
    mrr = float(f.get("plan_mrr") or 0.0)
    tokens_limit = float(f.get("monthly_tokens") or 0.0)
    burn = (float(f.get("tokens_spent_month") or 0) / tokens_limit) if tokens_limit else 0.0

    # P(convert) — для неплатящих: путь к первой оплате; платящий уже дошёл.
    if paying:
        p_convert = 1.0
    else:
        p_convert = 0.05
        if f.get("generations_total", 0) > 0:
            p_convert += 0.25
        if f.get("generations_total", 0) >= 3:
            p_convert += 0.10
        if f.get("paywall_views", 0) > 0:
            p_convert += 0.20
        if f.get("checkout_starts", 0) > 0:
            p_convert += 0.25
        p_convert -= 0.02 * min(float(f.get("days_since_seen") or 0), 30.0)
        p_convert = _clamp(p_convert)

    # P(churn) — только для платящих.
    if paying:
        p_churn = 0.08
        prev = f.get("generations_prev_7d", 0)
        if prev > 0 and f.get("generations_7d", 0) <= prev * 0.5:
            p_churn += 0.30
        if f.get("cancel_flow_14d", 0) > 0 or f.get("cancel_scheduled"):
            p_churn += 0.30
        if f.get("generations_7d", 0) == 0 and prev == 0:
            p_churn += 0.15   # не пользуется ≥14 дней
        if f.get("failed_recent"):
            p_churn += 0.25
        p_churn = _clamp(p_churn)
    else:
        p_churn = 0.0

    # LTV v1: горизонт 6 мес × MRR плана, взвешенный на выживание/конверсию.
    if paying:
        ltv = mrr * LTV_HORIZON_MONTHS * (1.0 - p_churn)
    elif trialing:
        ltv = mrr * LTV_HORIZON_MONTHS * p_convert
    else:
        ltv = 0.0

    # Power — готовность к апгрейду (только платящие).
    power = 0.0
    if paying:
        if burn >= 0.8:
            power += 0.5
        elif burn >= 0.6:
            power += 0.2
        if f.get("gen_days_this_month", 0) >= 15:
            power += 0.3
        if f.get("paywall_views", 0) > 0:
            power += 0.2
        power = min(power, 1.0)

    return {
        "p_convert": round(p_convert, 4),
        "p_churn": round(p_churn, 4),
        "ltv_estimate": round(ltv, 2),
        "power_score": round(power, 4),
    }
