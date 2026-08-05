"""api/saas.py — JSON-домен Revenue Autopilot (SaaS-пресет, Phase 5).

Экран SPA: /leak-audit. Эндпоинт: GET /api/v1/saas/leak-audit?tenant=

Отчёт «где утекают деньги» (REBUILD §Phase 5) поверх SaaS-витрин saas_schema.sql
(математика стадий - user_actions, та же, что везде: паритет цифр):
  • dunning            - стадия DUNNING: MRR под угрозой прямо сейчас;
  • dead_trials        - trialing с истёкшим trial_end (не оплатили, не ушли):
                         потенциал = MRR их плана;
  • silent_cancels_30d - отменившиеся за 30 дней БЕЗ события cancel_flow_started
                         (ушли молча - их никто не пытался удержать);
  • under_upgrades     - стадия UPGRADE (burn >= 80% лимита): недобор expansion,
                         оценка 0.5 x MRR (как value_at_stake);
  • headline_monthly   - сумма dunning + silent + upgrade: «утекает ~$X/мес».

Регистрация - по переменной `bp` (пакет api/ авто-подхватывает модуль).
"""
from __future__ import annotations

from flask import Blueprint, request

from .core import require_auth, api_json
from player_board import q

bp = Blueprint('api_saas', __name__, url_prefix='/api/v1')

LEAK_ROLES = ('super_admin', 'head_retention', 'director', 'analyst',
              'finance', 'marketing_manager')

DEFAULT_TENANT = 'hubcontent'


def _flt(x) -> float:
    try:
        v = float(x or 0)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


@bp.get('/saas/leak-audit')
@require_auth(roles=LEAK_ROLES)
def leak_audit():
    tenant = request.args.get('tenant') or DEFAULT_TENANT

    # q() возвращает (column_names, rows) - берём первую строку данных
    dunning = q(
        "SELECT count(), coalesce(sum(toFloat64(mrr)), 0) "
        "FROM user_actions WHERE tenant_id = {t:String} AND stage = 'DUNNING'",
        {'t': tenant})[1][0]

    dead_trials = q(
        """
        SELECT count(), coalesce(sum(toFloat64(p.mrr)), 0)
        FROM stripe_subscriptions_current s
        LEFT JOIN tenant_plans_current p
          ON p.tenant_id = s.tenant_id AND p.plan_id = s.plan_id
        WHERE s.tenant_id = {t:String} AND s.status = 'trialing'
          AND s.trial_end IS NOT NULL AND s.trial_end < now()
        """,
        {'t': tenant})[1][0]

    silent = q(
        """
        SELECT count(), coalesce(sum(toFloat64(p.mrr)), 0)
        FROM stripe_subscriptions_current s
        LEFT JOIN tenant_plans_current p
          ON p.tenant_id = s.tenant_id AND p.plan_id = s.plan_id
        WHERE s.tenant_id = {t:String} AND s.status = 'canceled'
          AND s.canceled_at >= now() - INTERVAL 30 DAY
          AND s.customer_id NOT IN (
              SELECT stripe_customer_id FROM identities_current i
              JOIN saas_events_resolved e ON e.identity_id = i.identity_id
              WHERE i.tenant_id = {t:String}
                AND e.event_type = 'cancel_flow_started')
        """,
        {'t': tenant})[1][0]

    upgrades = q(
        "SELECT count(), coalesce(sum(value_at_stake), 0) "
        "FROM user_actions WHERE tenant_id = {t:String} AND stage = 'UPGRADE'",
        {'t': tenant})[1][0]

    dunning_mrr = _flt(dunning[1])
    silent_mrr = _flt(silent[1])
    upgrade_pot = _flt(upgrades[1])

    return api_json({
        'tenant': tenant,
        'headline_monthly_leak': round(dunning_mrr + silent_mrr + upgrade_pot, 2),
        'blocks': {
            'dunning': {'count': int(dunning[0]), 'mrr': round(dunning_mrr, 2)},
            'dead_trials': {'count': int(dead_trials[0]),
                            'potential_mrr': round(_flt(dead_trials[1]), 2)},
            'silent_cancels_30d': {'count': int(silent[0]),
                                   'mrr': round(silent_mrr, 2)},
            'under_upgrades': {'count': int(upgrades[0]),
                               'expansion_potential': round(upgrade_pot, 2)},
        },
    })
