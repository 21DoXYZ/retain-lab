"""Эвристический скоринг heur-v2 (Phase 2): прозрачные веса вместо ML.

Контракт под будущий ML (§0.5): вход — плоский dict фич (тот же, что пишется
в user_scores.features), выход — 4 скора.

v2 после аудита против лучших практик рынка:
  • cold-start: новичок без событий - НЕ мертвец (раньше days_since_seen=999
    прибивал p_convert свежего сайнапа к полу);
  • failed_payment убран из p_churn: несписание - ФАКТ, им владеет стадия
    DUNNING (методология §3: «деньги на факте не спрашивают скор»), в скоре он
    двоился;
  • LTV - через ожидаемое время жизни 1/p_churn (мес., кап 24), а не
    фиксированные 6 месяцев с косметическим (1-p);
  • поведение сниппета v2 наконец скорится: фрустрация (js-ошибки, rage
    clicks) и обвал времени в продукте - ранние сигналы ухода, которых нет
    в метриках использования.
"""

from __future__ import annotations

VERSION = "heur-v2"

# Ожидаемое время жизни: p_churn трактуем как месячный риск. Кап сверху -
# «вечных» клиентов не бывает; кап снизу - даже уходящий платит этот месяц.
LTV_MAX_MONTHS = 24.0
LTV_MIN_MONTHS = 1.0
TRIAL_PRIOR_MONTHS = 6.0   # у триала своей истории удержания ещё нет

PAYING_STATUSES = {"active", "past_due"}


def _clamp(x: float, lo: float = 0.01, hi: float = 0.95) -> float:
    return max(lo, min(hi, x))


def expected_months(p_churn_monthly: float) -> float:
    """Месяцы ожидаемой жизни из месячного риска ухода."""
    if p_churn_monthly <= 0:
        return LTV_MAX_MONTHS
    return max(LTV_MIN_MONTHS, min(LTV_MAX_MONTHS, 1.0 / p_churn_monthly))


def compute_scores(f: dict) -> dict:
    """f: фичи одной identity (см. scoring.py FEATURE_QUERY). Возвращает скоры."""
    status = f.get("sub_status") or ""
    paying = status in PAYING_STATUSES
    trialing = status == "trialing"
    mrr = float(f.get("plan_mrr") or 0.0)
    tokens_limit = float(f.get("monthly_tokens") or 0.0)
    burn = (float(f.get("tokens_spent_month") or 0) / tokens_limit) if tokens_limit else 0.0

    # Сколько дней человек молчит. У никогда-не-виденного это возраст аккаунта
    # (tenure), а не «999»: свежий сайнап ещё ничего не успел, он не мёртв.
    tenure = float(f.get("tenure_days") or 0.0)
    seen_raw = f.get("days_since_seen")
    days_quiet = float(seen_raw) if seen_raw is not None and float(seen_raw) < 998 \
        else tenure

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
        p_convert -= 0.02 * min(days_quiet, 30.0)
        p_convert = _clamp(p_convert)

    # P(churn) — только для платящих. Несписание сюда НЕ входит: это факт
    # стадии DUNNING, а не поведенческая вероятность.
    if paying:
        p_churn = 0.08
        prev = f.get("generations_prev_7d", 0)
        if prev > 0 and f.get("generations_7d", 0) <= prev * 0.5:
            p_churn += 0.30
        if f.get("cancel_flow_14d", 0) > 0 or f.get("cancel_scheduled"):
            p_churn += 0.30
        if f.get("generations_7d", 0) == 0 and prev == 0 and tenure >= 14:
            p_churn += 0.15   # не пользуется ≥14 дней (и успел бы начать)

        # Поведение сниппета v2: фрустрация и обвал времени в продукте.
        # Продукт у человека падает или бесит - он уйдёт раньше, чем это
        # увидят метрики использования.
        if int(f.get("js_errors_7d") or 0) >= 3:
            p_churn += 0.10
        if int(f.get("rage_clicks_7d") or 0) >= 3:
            p_churn += 0.10
        act_prev = float(f.get("active_sec_prev_7d") or 0.0)
        act_now = float(f.get("active_sec_7d") or 0.0)
        if act_prev >= 600 and act_now <= act_prev * 0.4:
            p_churn += 0.15   # жил в продукте - и почти исчез
        p_churn = _clamp(p_churn)
    else:
        p_churn = 0.0

    # LTV v2: MRR × ожидаемые месяцы жизни (выживание, не фиксированный
    # горизонт). Это ВЫРУЧКА - в маржу переводит слой офферов (economics.py),
    # у которого есть себестоимость тенанта; здесь её честно нет.
    if paying:
        ltv = mrr * expected_months(p_churn)
    elif trialing:
        ltv = mrr * TRIAL_PRIOR_MONTHS * p_convert
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
