"""Бизнес-контекст: всё, что система ЗНАЕТ об этом бизнесе, одним блоком.

Правило (методология §8, распространено на ВСЮ генерацию): генерик-промпт
запрещён. Каждый LLM-вызов - офферы, тексты, аналитик, классификатор отмен -
получает этот блок целиком. Тест test_business_context.py следит, чтобы ни
один генератор не потерял его молча.

Контекст двухслойный, и слои помечены:
  • ЗАЯВЛЕННОЕ (claimed) - анкета онбординга и разбор сайта: что бизнес
    говорит о себе. Может врать или устареть.
  • ИЗМЕРЕННОЕ (measured) - его же данные в нашей базе: реальные планы из
    Stripe, названные причины отмен, распределение по стадиям, достоверные
    замеры кампаний. Не врёт.
Модель обязана видеть разницу: решение на замере и решение на самоописании -
разные решения (тот же принцип, что uplift_or_prior в офферах).

Fail-soft: любой отвалившийся кусок = честная пометка "no measured data yet",
а не молчаливая дыра. Генерация без базы (тесты, dry-run) живёт на claimed.
"""

from __future__ import annotations

import json


def _q(client, sql: str, params: dict) -> list:
    try:
        return client.query(sql, parameters=params).result_rows
    except Exception:               # noqa: BLE001 - нет таблицы/базы = нет слоя
        return []


def business_context(client, tenant: str, answers: dict | None = None) -> dict:
    """Полный контекст бизнеса. client=None -> только claimed-слой."""
    if answers is None:
        try:
            from saas_senders import load_tenant_channels
        except ImportError:
            from stripe_sync.saas_senders import load_tenant_channels  # type: ignore
        tc = load_tenant_channels(tenant)
        answers = {**(tc.get("site_profile") or {}),
                   **(tc.get("onboarding_answers") or {})}

    ctx: dict = {"claimed": dict(answers or {}), "measured": {}}
    if client is None:
        return ctx
    m = ctx["measured"]

    # Реальные планы из Stripe - факт биллинга, не анкета
    plans = _q(client,
               "SELECT plan_id, toFloat64(mrr), toUInt32(monthly_tokens) "
               "FROM retention.tenant_plans_current "
               "WHERE tenant_id = %(t)s AND mrr > 0 ORDER BY mrr",
               {"t": tenant})
    if plans:
        m["stripe_plans"] = [{"plan_id": p[0], "usd_month": p[1],
                              "units": int(p[2])} for p in plans]

    # Названные причины отмен - самое дорогое знание о том, ПОЧЕМУ уходят
    reasons = _q(client,
                 "SELECT category, count() FROM retention.cancel_reasons "
                 "WHERE tenant_id = %(t)s AND category != 'other' "
                 "GROUP BY category ORDER BY count() DESC LIMIT 5",
                 {"t": tenant})
    if reasons:
        m["cancel_reasons"] = [{"reason": r[0], "count": int(r[1])}
                               for r in reasons]

    # Где стоят люди сейчас - масштаб каждой стадии
    stages = _q(client,
                "SELECT stage, count() FROM retention.user_actions "
                "WHERE tenant_id = %(t)s GROUP BY stage",
                {"t": tenant})
    if stages:
        m["stage_counts"] = {s[0]: int(s[1]) for s in stages}

    # Достоверные замеры кампаний - что УЖЕ доказанно работает или нет
    uplift = _q(client,
                "SELECT campaign_id, conv_target, conv_control, n_target, "
                "n_control FROM retention.uplift_reports "
                "WHERE tenant_id = %(t)s AND n_target >= 30 AND n_control >= 30 "
                "ORDER BY computed_at DESC LIMIT 6",
                {"t": tenant})
    seen = set()
    proven = []
    for r in uplift:
        if r[0] in seen:
            continue
        seen.add(r[0])
        proven.append({"campaign": r[0],
                       "uplift_pp": round((float(r[1]) - float(r[2])) * 100, 1),
                       "n": int(r[3]) + int(r[4])})
    if proven:
        m["campaign_uplift"] = proven
    return ctx


def context_block(ctx: dict) -> str:
    """Prompt-блок из контекста. Всегда начинается с маркера слоёв - модель
    обязана отличать самоописание бизнеса от его измеренных данных."""
    claimed = ctx.get("claimed") or {}
    measured = ctx.get("measured") or {}
    lines = [
        "=== BUSINESS CONTEXT (ground every output in this; generic output "
        "not tied to it will be rejected) ===",
        "-- CLAIMED by the business (questionnaire + own website; may be "
        "stale): --",
        json.dumps(claimed, ensure_ascii=False),
        "-- MEASURED from its live data (billing, users, named cancel "
        "reasons, proven campaign lift; trust this over claims): --",
        json.dumps(measured, ensure_ascii=False) if measured
        else "no measured data yet - the business is newly connected",
        "=== END BUSINESS CONTEXT ===",
    ]
    return "\n".join(lines)
