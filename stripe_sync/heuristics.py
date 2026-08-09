"""Эвристический скоринг heur-v2 (Phase 2): прозрачные веса вместо ML.

Контракт под будущий ML (§0.5): вход — плоский dict фич (тот же, что пишется
в user_scores.features), выход — 5 скоров (v3: +buy_intent).

v2 после аудита против лучших практик рынка:
  • cold-start: новичок без событий - НЕ мертвец (раньше days_since_seen=999
    прибивал p_convert свежего сайнапа к полу);
  • failed_payment убран из p_churn: несписание - ФАКТ, им владеет стадия
    DUNNING (методология §3: «деньги на факте не спрашивают скор»), в скоре он
    двоился;
  • LTV - через ожидаемое время жизни 1/p_churn (мес., кап 24), а не
    фиксированные 6 месяцев с косметическим (1-p);
  • поведение сниппета v2 наконец скорится: фрустрация (js-ошибки, rage
    clicks) и обвал времени в продукте - ранние сигналы ухода.

v3: перформанс (INP) в p_churn - тормоза это тихий отток; НОВЫЙ скор
buy_intent - намерение купить из кросс-сессионных заходов на прайсинг,
пейвола, старта чекаута (отдельно от p_convert=шанс и power=упёрся в лимит).
"""

from __future__ import annotations

VERSION = "heur-v4"

# Ожидаемое время жизни. КАК СЧИТАЕМ (v4, после разбора «откуда $1,238»):
# v3 делил 1 на p_churn - но p_churn это БАЛЛЬНЫЙ СКОР поведения, а не
# калиброванная месячная вероятность: 1/скор давал 12.5 месяцев из
# захардкоженной константы 0.08, без единого факта об удержании тенанта.
# v4: база = ИЗМЕРЕННАЯ месячная отписка тенанта (ушедшие / подписко-месяцы,
# считает scoring.py по stripe_subscriptions); скор поведения лишь МОДУЛИРУЕТ
# её множителем риска; горизонт ОГРАНИЧЕН наблюдаемой историей - не обещаем
# дольше, чем 2x того, что видели своими глазами. Мало данных - прайор по
# типу бизнеса с честной пометкой basis='prior'.
LTV_MAX_MONTHS = 24.0
LTV_MIN_MONTHS = 1.0
TRIAL_PRIOR_MONTHS = 6.0   # у триала своей истории удержания ещё нет
PRIOR_CHURN_M = 0.06       # прайор месячной отписки SaaS (5-7% рынок), пока
                           # своей когорты мало; вытесняется измеренной
CHURN_SCORE_BASELINE = 0.08  # скор «здорового» платящего: множитель риска = 1

PAYING_STATUSES = {"active", "past_due"}


def _clamp(x: float, lo: float = 0.01, hi: float = 0.95) -> float:
    return max(lo, min(hi, x))


def lifecycle_months(p_churn_score: float, ctx: dict | None = None) -> tuple[float, str]:
    """(ожидаемые месяцы жизни, basis) из скора риска + контекста тенанта.

    ctx (scoring.py, tenant_lifecycle): base_churn_m - измеренная месячная
    отписка (None = мало данных), obs_months - сколько месяцев мы вообще
    наблюдаем подписки тенанта. Скор -> множитель к базе (0.5..2.5, нейтрален
    на CHURN_SCORE_BASELINE): поведение усиливает или ослабляет базовый темп,
    но не подменяет его собой."""
    ctx = ctx or {}
    base = ctx.get("base_churn_m")
    basis = "measured" if base is not None else "prior"
    base = float(base) if base is not None else PRIOR_CHURN_M

    mult = 1.0 + (float(p_churn_score) - CHURN_SCORE_BASELINE) * 2.0
    mult = max(0.5, min(2.5, mult))
    churn_m = max(0.01, min(0.5, base * mult))

    # потолок доказуемости: видели N месяцев - не обещаем больше 2N
    obs = float(ctx.get("obs_months") or 0.0)
    cap = max(3.0, min(LTV_MAX_MONTHS, obs * 2.0)) if obs > 0 else 12.0
    months = max(LTV_MIN_MONTHS, min(cap, 1.0 / churn_m))
    return round(months, 1), basis


def expected_months(p_churn_monthly: float) -> float:
    """Месяцы жизни из месячного риска (для ставки в гейте офферов).
    Для LTV использовать lifecycle_months - там база измеренная."""
    if p_churn_monthly <= 0:
        return LTV_MAX_MONTHS
    return max(LTV_MIN_MONTHS, min(LTV_MAX_MONTHS, 1.0 / p_churn_monthly))


def compute_scores(f: dict, ctx: dict | None = None) -> dict:
    """f: фичи одной identity (см. scoring.py FEATURE_QUERY). Возвращает скоры.

    ctx - жизненный цикл ТЕНАНТА (tenant_lifecycle в scoring.py): измеренная
    месячная отписка, наблюдаемые месяцы, средний чек. Без ctx LTV честно
    живёт на прайорах (basis='prior')."""
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

        # Поведение сниппета: фрустрация, обвал времени, тормоза продукта.
        # Всё это - ранние сигналы ухода раньше метрик использования.
        if int(f.get("js_errors_7d") or 0) >= 3:
            p_churn += 0.10
        if int(f.get("rage_clicks_7d") or 0) >= 3:
            p_churn += 0.10
        act_prev = float(f.get("active_sec_prev_7d") or 0.0)
        act_now = float(f.get("active_sec_7d") or 0.0)
        if act_prev >= 600 and act_now <= act_prev * 0.4:
            p_churn += 0.15   # жил в продукте - и почти исчез
        # перформанс как исход: медленный отклик (INP) = тихая фрустрация.
        # INP > 500мс - плохо по порогам Google, > 1000мс - очень плохо.
        inp = int(f.get("inp_ms") or 0)
        if inp > 1000:
            p_churn += 0.10
        elif inp > 500:
            p_churn += 0.05
        p_churn = _clamp(p_churn)
    else:
        p_churn = 0.0

    # LTV v4: MRR × месяцы жизни, где темп ухода ИЗМЕРЕН по когорте тенанта,
    # скор поведения его модулирует, а горизонт ограничен видимой историей.
    # Это ВЫРУЧКА - в маржу переводит слой офферов (economics.py), у которого
    # есть себестоимость тенанта; здесь её честно нет.
    months, ltv_basis = lifecycle_months(p_churn, ctx)
    if paying:
        ltv = mrr * months
    elif trialing:
        # у триала mrr обычно 0 - берём средний чек тенанта; и это ставка на
        # конверсию, поэтому весь горизонт дисконтируется её вероятностью
        price = mrr or float((ctx or {}).get("avg_price") or 0.0)
        ltv = price * min(TRIAL_PRIOR_MONTHS, months) * p_convert
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

    # Buy-intent: НАМЕРЕНИЕ купить/расшириться, отдельно от p_convert (шанс)
    # и power (уперся в лимит). Кросс-сессионные заходы на прайсинг - самый
    # сильный сигнал; пейвол, старт чекаута, свежая активность - подтверждают.
    buy = 0.0
    pv = int(f.get("pricing_visits") or 0)
    if pv >= 3:
        buy += 0.45
    elif pv == 2:
        buy += 0.30
    elif pv == 1:
        buy += 0.15
    if int(f.get("checkout_starts") or 0) > 0:
        buy += 0.30
    if int(f.get("paywall_views") or 0) > 0:
        buy += 0.15
    if int(f.get("downloads_14d") or 0) > 0:
        buy += 0.05      # адаптация фич - косвенный интент
    if int(f.get("apple_pay") or 0) > 0:
        buy += 0.05      # карта в кошельке - готов платить технически
    buy_intent = round(min(buy, 1.0), 4)

    return {
        "p_convert": round(p_convert, 4),
        "p_churn": round(p_churn, 4),
        "ltv_estimate": round(ltv, 2),
        "ltv_months": months,
        "ltv_basis": ltv_basis,
        "power_score": round(power, 4),
        "buy_intent": buy_intent,
    }
