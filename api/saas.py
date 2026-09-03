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

import datetime as _dt

from flask import Blueprint, request

from .core import require_auth, api_json, current_tenant_scope
from player_board import q

bp = Blueprint('api_saas', __name__, url_prefix='/api/v1')

_UA = 'RevenueAutopilot/1.0 (+https://retivo.digital)'

LEAK_ROLES = ('super_admin', 'head_retention', 'director', 'analyst',
              'finance', 'marketing_manager')

# Права на запись настроек (каналы, онбординг, автопилот) - только владельцы.
CHANNEL_WRITE_ROLES = ('super_admin', 'director', 'head_retention')

# Роль «работа с клиентом»: support видит юзеров и переписку, пишет людям
# (инбокс, ручные касания, контакты) - и НИЧЕГО больше: ни кампаний, ни
# офферов, ни настроек, ни денег. Владелец нанимает человека под общение,
# не открывая ему бизнес.
CLIENT_READ_ROLES = LEAK_ROLES + ('support',)
CLIENT_WRITE_ROLES = CHANNEL_WRITE_ROLES + ('support',)

# Пространства по умолчанию НЕТ: тенант приходит из скоупа пользователя или
# ?tenant=. Для платформенного пользователя дефолт = единственное заведённое
# пространство (пока клиент один), иначе он обязан выбрать.


def _host() -> str:
    """Публичный домен платформы (SAAS_HOST): из него строятся все URL, которые
    клиент вставляет в чужие панели - вебхуки Stripe и Resend, ingest."""
    import os as _os
    return _os.environ.get('SAAS_HOST', '').strip()


def _flt(x) -> float:
    try:
        v = float(x or 0)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


@bp.get('/saas/leak-audit')
@require_auth(roles=LEAK_ROLES)
def leak_audit():
    tenant = _tenant_arg()

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
    dead_count, dead_mrr = int(dead_trials[0]), _flt(dead_trials[1])

    # Триал живёт не только в Stripe: у продуктов с экспортом «триал» - это
    # план в САМОМ продукте. Мёртвый триал по-продуктовому: человек РЕАЛЬНО
    # пробовал (есть ценные действия), аккаунту 14+ дней, платить не начал.
    product_trials = int(q(
        """
        SELECT count() FROM user_actions ua
        LEFT JOIN user_event_features f
          ON f.tenant_id = ua.tenant_id AND f.identity_id = ua.identity_id
        WHERE ua.tenant_id = {t:String}
          AND ua.sub_status NOT IN ('active', 'past_due', 'trialing')
          AND f.generations_total > 0
          AND f.first_seen <= now() - INTERVAL 14 DAY
        """, {'t': tenant})[1][0][0])
    dead_count += product_trials

    # Деньги мёртвых триалов - ТОЛЬКО по измеренной конверсии (scoring пишет
    # trial_conv в lifecycle_measured): count x средний чек x конверсия.
    # Замера нет - показываем счёт без суммы, а не выдумку.
    if product_trials:
        try:
            from stripe_sync.knowledge import load as _kb
            lc = _kb(_ch_direct(), tenant, 'lifecycle_measured')
            conv = lc.get('trial_conv')
            avgp = _flt(lc.get('avg_price'))
            if conv is not None and avgp > 0:
                dead_mrr += round(product_trials * avgp * float(conv), 2)
        except Exception:  # noqa: BLE001
            pass

    silent = q(
        """
        SELECT count(), coalesce(sum(toFloat64(p.mrr)), 0)
        FROM stripe_subscriptions_current s
        LEFT JOIN tenant_plans_current p
          ON p.tenant_id = s.tenant_id AND p.plan_id = s.plan_id
        WHERE s.tenant_id = {t:String} AND s.status = 'canceled'
          AND s.canceled_at >= now() - INTERVAL 30 DAY
          AND s.customer_id NOT IN (
              -- окно 60д (аудит r3 2026-08-26): без границы по ts подзапрос
              -- резолвил ВСЮ историю событий; отмена нас интересует за 30д,
              -- флоу отмены раньше неё тем более в этом окне
              SELECT i.stripe_customer_id FROM identities_current i
              JOIN saas_events e ON e.tenant_id = i.tenant_id
                AND e.client_user_id = i.client_user_id
              WHERE i.tenant_id = {t:String}
                AND e.event_type = 'cancel_flow_started'
                AND e.ts >= now() - INTERVAL 60 DAY)
        """,
        {'t': tenant})[1][0]

    # Недобор апгрейдов = РАЗНИЦА до следующего тарифа. Считает её вьюха
    # user_actions по лестнице tenant_plan_ladder - одно определение на все
    # экраны, чтобы «денег на кону» у юзера и сумма на этом экране сходились.
    upgrades = q(
        "SELECT count(), coalesce(sum(value_at_stake), 0) "
        "FROM user_actions WHERE tenant_id = {t:String} AND stage = 'UPGRADE'",
        {'t': tenant})[1][0]
    upgrade_pot = _flt(upgrades[1])
    ladder_size = int(q(
        "SELECT count() FROM tenant_plans_current "
        "WHERE tenant_id = {t:String} AND mrr > 0", {'t': tenant})[1][0][0])

    dunning_mrr = _flt(dunning[1])
    silent_mrr = _flt(silent[1])
    # известна ли лестница тарифов - от этого зависит, честно ли показывать
    # потенциал апгрейда цифрой
    ladder_known = ladder_size > 1

    return api_json({
        'tenant': tenant,
        'headline_monthly_leak': round(dunning_mrr + silent_mrr + upgrade_pot, 2),
        'upgrade_estimate_known': ladder_known,
        'blocks': {
            'dunning': {'count': int(dunning[0]), 'mrr': round(dunning_mrr, 2)},
            'dead_trials': {'count': dead_count,
                            'potential_mrr': round(dead_mrr, 2)},
            'silent_cancels_30d': {'count': int(silent[0]),
                                   'mrr': round(silent_mrr, 2)},
            'under_upgrades': {'count': int(upgrades[0]),
                               'expansion_potential': round(upgrade_pot, 2)},
        },
    })


@bp.get('/saas/uplift')
@require_auth(roles=LEAK_ROLES)
def uplift():
    """Последний uplift-отчёт по каждой кампании (uplift_reports пишет
    stripe_sync/uplift_report.py, расписание - Пн 08:00). Инкремент = 
    (conv_target - conv_control) x N_target x средний чек; n_control=0 -> n/a."""
    tenant = _tenant_arg()

    rows = q(
        """
        SELECT campaign_id,
               argMax(period_start, computed_at)    AS period_start,
               argMax(period_end, computed_at)      AS period_end,
               argMax(n_target, computed_at)        AS n_target,
               argMax(n_control, computed_at)       AS n_control,
               argMax(conv_target, computed_at)     AS conv_target,
               argMax(conv_control, computed_at)    AS conv_control,
               argMax(avg_check, computed_at)       AS avg_check,
               argMax(incremental_usd, computed_at) AS incremental_usd,
               argMax(goal_event, computed_at)      AS goal_event,
               max(computed_at)                     AS computed_at_max
        FROM uplift_reports
        WHERE tenant_id = {t:String}
        GROUP BY campaign_id
        ORDER BY campaign_id
        """,
        {'t': tenant})[1]

    campaigns = []
    total = 0.0
    for r in rows:
        has_holdout = int(r[4]) > 0
        inc = _flt(r[8]) if has_holdout else None
        if inc is not None:
            total += inc
        campaigns.append({
            'campaign_id': r[0],
            'period_start': str(r[1]),
            'period_end': str(r[2]),
            'n_target': int(r[3]),
            'n_control': int(r[4]),
            'conv_target': _flt(r[5]),
            'conv_control': _flt(r[6]),
            'avg_check': round(_flt(r[7]), 2),
            'incremental_usd': inc,
            # мало людей в группах - цифра есть, но это ранний сигнал, а не
            # измеренный результат; экран обязан это показать
            'confident': int(r[3]) >= 30 and int(r[4]) >= 30,
            'goal_event': r[9],
            'computed_at': str(r[10]),
        })

    return api_json({
        'tenant': tenant,
        'total_incremental': round(total, 2),
        'campaigns': campaigns,
    })


@bp.get('/saas/home')
@require_auth(roles=LEAK_ROLES)
def home():
    """Домашний дашборд владельца: цифры + статусы онбординга. Один вызов -
    всё, что нужно главной, чтобы ответить «что происходит и что делать»."""
    tenant = _tenant_arg()

    mrr = _flt(q(
        "SELECT coalesce(sum(mrr), 0) FROM mrr_facts WHERE tenant_id = {t:String}",
        {'t': tenant})[1][0][0])

    stages = {r[0]: int(r[1]) for r in q(
        "SELECT stage, count() FROM user_actions WHERE tenant_id = {t:String} GROUP BY stage",
        {'t': tenant})[1]}

    dunning_mrr = _flt(q(
        "SELECT coalesce(sum(toFloat64(mrr)), 0) FROM user_actions "
        "WHERE tenant_id = {t:String} AND stage = 'DUNNING'", {'t': tenant})[1][0][0])

    camp = q(
        """
        SELECT countIf(status = 'active'), sum(control)
        FROM campaign_enrollments_current WHERE tenant_id = {t:String}
        """, {'t': tenant})[1][0]
    # Касание = то, что ДОШЛО (или дошло бы в боевом режиме). Отбитые попытки
    # и отложенные повторы касаниями не считаем - иначе цифра на главной врёт.
    touches_7d = int(q(
        "SELECT count() FROM campaign_send_log "
        "WHERE tenant_id = {t:String} AND ts >= now() - INTERVAL 7 DAY "
        "AND status IN ('sent', 'queued', 'issued', 'dry_run')",
        {'t': tenant})[1][0][0])

    # Онбординг: демо-данные или живой Stripe; сниппет уже шлёт события?
    live_customers = int(q(
        "SELECT count() FROM stripe_customers WHERE tenant_id = {t:String} "
        "AND NOT startsWith(customer_id, 'cus_mock') "
        "AND NOT startsWith(customer_id, 'cus_demo')",
        {'t': tenant})[1][0][0])
    snippet_events = int(q(
        "SELECT count() FROM saas_events WHERE tenant_id = {t:String} AND source = 'snippet'",
        {'t': tenant})[1][0][0])

    # Живой пульс: кто в продукте прямо сейчас и насколько база жива.
    pr = q(
        "SELECT countIf(toUnixTimestamp(last_seen) > 0"
        f"  AND dateDiff('second', last_seen, now()) < {ONLINE_THRESHOLD_S}),"
        " countIf(toUnixTimestamp(last_seen) > 0 AND last_seen >= now() - INTERVAL 1 DAY),"
        " countIf(toUnixTimestamp(last_seen) > 0 AND last_seen >= now() - INTERVAL 7 DAY),"
        " countIf(sub_status IN ('active', 'past_due')),"
        " countIf(sub_status = 'trialing')"
        " FROM user_actions WHERE tenant_id = {t:String}", {'t': tenant})[1][0]
    ur = q(
        "SELECT uniqExactIf(identity_id, event_type = 'signup' AND ts >= now() - INTERVAL 7 DAY),"
        " countIf(event_type = 'generation_completed' AND ts >= today()),"
        " countIf(event_type = 'generation_completed' AND ts >= now() - INTERVAL 7 DAY)"
        # deduped, не resolved: пересинк экспорта кладёт события повторно, а
        # resolved их не схлопывает - pulse завышал генерации (аудит 08-26)
        " FROM saas_events_deduped WHERE tenant_id = {t:String}", {'t': tenant})[1][0]
    pulse = {'online_now': int(pr[0] or 0), 'active_today': int(pr[1] or 0),
             'active_7d': int(pr[2] or 0), 'paying': int(pr[3] or 0),
             'trialing': int(pr[4] or 0), 'signups_7d': int(ur[0] or 0),
             'generations_today': int(ur[1] or 0), 'generations_7d': int(ur[2] or 0)}

    # Измеренная экономика (product_sync -> knowledge): {} - замера ещё нет
    measured = _measured_costs(tenant)

    return api_json({
        # каждый блок собран в своём try/except (_home_*): упавший кусок
        # отдаёт None, а не роняет весь дашборд - урок инцидента 08-13
        'yesterday': _home_yesterday_block(tenant),
        'digest': _home_digest(tenant),
        'series': _home_series(tenant),
        'funnel': _home_funnel(tenant),
        'actions': _home_actions(tenant),
        'machine_week': _home_machine_week(tenant),
        'people': _home_people(tenant),
        'tenant': tenant,
        'mrr': round(mrr, 2),
        'users_total': sum(stages.values()),
        'stages': stages,
        'at_risk_now': stages.get('DUNNING', 0) + stages.get('SAVE', 0),
        'dunning_mrr': round(dunning_mrr, 2),
        'pulse': pulse,
        'measured': {
            'revenue_usd': measured.get('measured_revenue_usd'),
            'provider_cost_usd': measured.get('measured_provider_cost_usd'),
            'margin_pct': measured.get('measured_margin_pct'),
            'unit_cost_usd': measured.get('measured_unit_cost_usd'),
            'window_days': measured.get('measured_window_days'),
        } if measured else None,
        'campaigns': {'active_enrollments': int(camp[0] or 0),
                      'holdout': int(camp[1] or 0),
                      'touches_7d': touches_7d},
        'setup': {'stripe_connected': live_customers > 0,
                  'snippet_connected': snippet_events > 0,
                  'channels_connected': _any_channel_active(tenant),
                  'offers_ready': _offers_step_done(tenant),
                  'autopilot': _autopilot_resolved(_campaigns_conf(tenant), tenant)},
    })


# ── Блоки дашборда владельца: история, тренды, решения ───────────────────────
# Дашборд отвечает на четыре вопроса собственника: что случилось пока меня не
# было, куда движется, что машина сделала за меня и что требует МЕНЯ.

def _home_yesterday_block(tenant: str) -> dict | None:
    """«Заработал или потерял за ночь»: вчерашний кэш + отмены/рефанды (JTBD-1)."""
    try:
        from stripe_sync import launches_payload as lp
        return lp.home_yesterday(q, tenant)
    except Exception as exc:  # noqa: BLE001
        print(f'[home] {tenant}: yesterday failed: {exc}', flush=True)
        return None


def _home_digest(tenant: str) -> dict | None:
    """«Пока вас не было»: человеческий дайджест за 24 часа."""
    try:
        ev = q("""
            SELECT
              uniqExactIf(identity_id, event_type = 'signup'),
              uniqExactIf(identity_id, event_type = 'billing.invoice_paid'),
              uniqExactIf(identity_id, event_type IN
                ('billing.subscription_cancelled', 'billing.subscription_cancel_scheduled')),
              countIf(event_type = 'feedback'
                      AND JSONExtractString(meta, 'category') IN ('bug', 'complaint')),
              countIf(event_type = 'support_ticket'),
              uniqExactIf(identity_id, event_type = 'generation_completed'),
              countIf(event_type = 'generation_completed'),
              uniqExactIf(identity_id, event_type = 'checkout_started')
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND ts >= now() - INTERVAL 1 DAY
            """, {'t': tenant})[1][0]
        return {'signups': int(ev[0]), 'new_paying': int(ev[1]),
                'cancels': int(ev[2]), 'bug_reports': int(ev[3]),
                'tickets': int(ev[4]), 'creators': int(ev[5]),
                'generations': int(ev[6]), 'checkouts': int(ev[7])}
    except Exception as exc:  # noqa: BLE001
        print(f'[home] {tenant}: digest failed: {exc}', flush=True)
        return None


def _home_series(tenant: str) -> dict | None:
    """Спарклайны за 14 дней: тренд важнее числа."""
    try:
        days = [r for r in q("""
            SELECT toDate(ts) AS d,
                   uniqExactIf(identity_id, source IN ('snippet', 'product')),
                   countIf(event_type = 'generation_completed')
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND ts >= today() - 13
            GROUP BY d ORDER BY d
            """, {'t': tenant})[1]]
        signup_days = {str(r[0]): int(r[1]) for r in q("""
            SELECT toDate(first_seen) AS d, count()
            FROM user_event_features
            WHERE tenant_id = {t:String} AND first_seen >= today() - 13
            GROUP BY d
            """, {'t': tenant})[1]}
        from datetime import date, timedelta
        grid = [(date.today() - timedelta(days=13 - i)) for i in range(14)]
        by_day = {str(r[0]): (int(r[1]), int(r[2])) for r in days}
        return {
            'days': [d.strftime('%d.%m') for d in grid],
            'active': [by_day.get(str(d), (0, 0))[0] for d in grid],
            'generations': [by_day.get(str(d), (0, 0))[1] for d in grid],
            'signups': [signup_days.get(str(d), 0) for d in grid],
        }
    except Exception as exc:  # noqa: BLE001
        print(f'[home] {tenant}: series failed: {exc}', flush=True)
        return None


def _home_funnel(tenant: str) -> dict | None:
    """Воронка до денег: где именно теряются люди. Наши данные позволяют
    видеть каждый шаг - signup -> проект -> ценность -> оплата."""
    try:
        r = q("""
            SELECT count(),
                   countIf(coalesce(f.projects_total, 0) > 0),
                   countIf(coalesce(f.generations_total, 0) > 0),
                   countIf(ua.sub_status IN ('active', 'past_due'))
            FROM user_actions ua
            LEFT JOIN user_event_features f
              ON f.tenant_id = ua.tenant_id AND f.identity_id = ua.identity_id
            WHERE ua.tenant_id = {t:String}
            """, {'t': tenant})[1][0]
        steps = [int(r[0]), int(r[1]), int(r[2]), int(r[3])]
        # самый большой обрыв (в людях) - его дашборд подсвечивает красным
        drops = [steps[i] - steps[i + 1] for i in range(3)]
        worst = drops.index(max(drops)) if any(drops) else -1
        return {'steps': steps, 'worst_gap': worst}
    except Exception as exc:  # noqa: BLE001
        print(f'[home] {tenant}: funnel failed: {exc}', flush=True)
        return None


def _home_actions(tenant: str) -> list | None:
    """Очередь «требует вашего решения»: дашборд-пульт, а не витрина."""
    out = []
    try:
        tch = ca.load_tenants().get(tenant, {}) or {}

        pending = int(q(
            "SELECT count() FROM ai_insights_current WHERE tenant_id = {t:String} "
            "AND status = 'new'", {'t': tenant})[1][0][0])
        if pending:
            out.append({'key': 'insights', 'count': pending, 'href': '/insights'})

        if not _autopilot_resolved(_campaigns_conf(tenant), tenant):
            waiting = int(q(
                "SELECT countIf(status = 'active') FROM campaign_enrollments_current "
                "WHERE tenant_id = {t:String}", {'t': tenant})[1][0][0])
            out.append({'key': 'autopilot_off', 'count': waiting, 'href': '/campaigns'})

        wa_status = str(tch.get('wa_personal_status') or '')
        if wa_status and wa_status != 'WORKING':
            out.append({'key': 'wa_down', 'count': 0, 'href': '/channel-settings'})

        cards = int(q("""
            SELECT count() FROM card_expiry_current ce
            JOIN user_actions ua ON ua.tenant_id = {t:String}
              AND ua.stripe_customer_id = ce.customer_id
            WHERE ce.tenant_id = {t:String} AND ce.days_to_expiry BETWEEN 0 AND 14
              AND ua.sub_status IN ('active', 'past_due')
            """, {'t': tenant})[1][0][0])
        if cards:
            out.append({'key': 'cards_expiring', 'count': cards, 'href': '/users'})

        guard = q(
            "SELECT status FROM pipeline_health WHERE tenant_id = {t:String} "
            "AND stage = 'ops_guard'", {'t': tenant})[1]
        if guard and str(guard[0][0]) == 'error':
            out.append({'key': 'infra', 'count': 0, 'href': '/pipeline'})

        # ТРЕВОГА ДОСТАВЛЯЕМОСТИ: bounce > 3% или жалобы > 0.1% за сутки
        # (при >= 20 реальных отправках) - домен под угрозой, чинить сразу
        dl = q("""
            SELECT
              (SELECT countIf(status = 'sent') FROM campaign_send_log
               WHERE tenant_id = {t:String} AND action = 'email'
                 AND ts >= now() - INTERVAL 1 DAY) AS sent,
              countIf(event_type IN ('bounced', 'delivery_delayed')),
              countIf(event_type = 'complained')
            FROM email_events
            WHERE tenant_id = {t:String} AND ts >= now() - INTERVAL 1 DAY
            """, {'t': tenant})[1][0]
        sent, bounced, complained = int(dl[0]), int(dl[1]), int(dl[2])
        if sent >= 20 and (bounced / sent > 0.03 or complained / sent > 0.001):
            out.append({'key': 'delivery_alarm',
                        'count': bounced + complained, 'href': '/uplift'})
        return out
    except Exception as exc:  # noqa: BLE001
        print(f'[home] {tenant}: actions failed: {exc}', flush=True)
        return out or None


def _home_machine_week(tenant: str) -> dict | None:
    """«Автопилот за неделю»: что машина сделала за владельца."""
    try:
        t = q("""
            SELECT countIf(status IN ('sent', 'queued')),
                   countIf(status = 'dry_run'),
                   countIf(status = 'rejected')
            FROM campaign_send_log
            WHERE tenant_id = {t:String} AND ts >= now() - INTERVAL 7 DAY
            """, {'t': tenant})[1][0]
        shown = int(q(
            "SELECT count() FROM saas_events_deduped WHERE tenant_id = {t:String} "
            "AND event_type = 'inapp_shown' AND ts >= now() - INTERVAL 7 DAY",
            {'t': tenant})[1][0][0])
        offers = q("""
            SELECT countIf(status IN ('issued', 'dry_run')), countIf(status = 'rejected')
            FROM offers_issued
            WHERE tenant_id = {t:String} AND issued_at >= now() - INTERVAL 7 DAY
            """, {'t': tenant})[1][0]
        uplift = _flt(q(
            "SELECT coalesce(sum(inc), 0) FROM ("
            "  SELECT campaign_id, argMax(incremental_usd, computed_at) AS inc"
            "  FROM uplift_reports WHERE tenant_id = {t:String} GROUP BY campaign_id)",
            {'t': tenant})[1][0][0])
        return {'sent': int(t[0]), 'dry_run': int(t[1]), 'rejected': int(t[2]),
                'inapp_shown': shown, 'offers_issued': int(offers[0]),
                'offers_rejected': int(offers[1]),
                'uplift_usd': round(uplift, 2)}
    except Exception as exc:  # noqa: BLE001
        print(f'[home] {tenant}: machine failed: {exc}', flush=True)
        return None


def _home_people(tenant: str) -> dict | None:
    """На кого смотреть сегодня: деньги под риском и горячие к покупке."""
    try:
        def _rows(sql):
            return [{'identity_id': r[0],
                     'email': r[1] or r[2] or str(r[0])[:8],
                     'mrr': round(_flt(r[3]), 0), 'score': round(_flt(r[4]), 2)}
                    for r in q(sql, {'t': tenant})[1]]
        at_risk = _rows("""
            SELECT identity_id, email_norm, client_user_id, toFloat64(mrr),
                   coalesce(p_churn, 0)
            FROM user_actions WHERE tenant_id = {t:String}
              AND sub_status IN ('active', 'past_due') AND coalesce(p_churn, 0) >= 0.2
            ORDER BY value_at_stake DESC, p_churn DESC LIMIT 5""")
        hot = _rows("""
            SELECT identity_id, email_norm, client_user_id, toFloat64(mrr),
                   greatest(coalesce(buy_intent, 0), coalesce(burn_rate, 0))
            FROM user_actions WHERE tenant_id = {t:String}
              AND (coalesce(buy_intent, 0) >= 0.3 OR coalesce(burn_rate, 0) >= 0.6)
            ORDER BY 5 DESC LIMIT 5""")
        if not at_risk and not hot:
            return None
        return {'at_risk': at_risk, 'hot': hot}
    except Exception as exc:  # noqa: BLE001
        print(f'[home] {tenant}: people failed: {exc}', flush=True)
        return None


def _autopilot_blockers(tenant: str) -> list:
    """Чего не хватает, чтобы автопилот имел смысл. Пусто - можно включать."""
    out = []
    if not _any_channel_active(tenant):
        out.append('no_channel')
    if not _offers_step_done(tenant):
        out.append('no_offers')
    live_users = int(q("SELECT count() FROM user_actions WHERE tenant_id = {t:String}",
                       {'t': tenant})[1][0][0])
    if not live_users:
        out.append('no_users')
    return out


def _any_channel_active(tenant: str) -> bool:
    """Хоть один внешний канал доведён до конца (email verified+from или
    телеграм-бот подключён). In-app не считаем - он живёт на сниппете."""
    tch = ca.load_tenants().get(tenant, {}) or {}
    # ключ КЛИЕНТА важнее платформенного: с ним канал живой, даже если у
    # платформы своего аккаунта Resend нет вовсе
    email_ok = ca.email_state(tch, bool(_tenant_resend_key(tenant))) == 'active'
    return email_ok or bool(tch.get('telegram_bot_token'))


def _tenant_offers(tenant: str) -> list:
    """Каталог офферов тенанта с учётом правок - компакт для онбординга.
    Шаг «офферы» закрыт, если что-то правлено ЛИБО отмечено «проверено»."""
    import json as _json
    from pathlib import Path as _Path
    from stripe_sync import overrides as ovr
    p = _Path(__file__).resolve().parent.parent / 'stripe_sync' / 'offers_catalog.json'
    catalog = ovr.merge_catalog(
        (_json.loads(p.read_text()).get(tenant) or {}) if p.exists() else {},
        ovr.load_tenant(tenant))
    return [{'offer_id': o['offer_id'], 'title': o['title'],
             'max_per_user_30d': int(o.get('max_per_user_30d') or 0),
             'edited': bool(o.get('_edited')),
             'custom': bool(o.get('_custom')),
             'disabled': bool(o.get('_disabled'))}
            for o in catalog.get('offers', [])]


def _offers_step_done(tenant: str) -> bool:
    if any(o['edited'] for o in _tenant_offers(tenant)):
        return True
    return bool((ca.load_tenants().get(tenant, {}) or {}).get('offers_reviewed'))


def _snippet_token(tenant: str = '') -> str:
    """Сниппет-токен тенанта. Класс токена ПУБЛИЧНЫЙ (он лежит в открытом HTML
    сайта клиента, как write-key у Segment/Amplitude) - показывать его в UI
    онбординга можно и нужно; маски - для казино-легаси /keys."""
    import json as _json
    if not tenant:
        return ''
    try:
        with open(_os.environ.get('TOKENS_FILE', '/secrets/tokens.json')) as fh:
            data = _json.load(fh)
    except Exception:
        return ''
    # ТОЛЬКО свой токен. Раньше при отсутствии ключа подставлялся ПЕРВЫЙ
    # ПОПАВШИЙСЯ токен из файла - то есть ЧУЖОЙ: клиент вставлял такой
    # сниппет на сайт, ingest отбивал события как чужое пространство (403),
    # и человек часами не понимал, почему «поставил, а данных нет».
    own = data.get(tenant) if isinstance(data, dict) else None
    return str(own) if own else ''


@bp.get('/saas/onboarding')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_onboarding():
    """Всё для визарда «Get started» одним вызовом: статусы 4 шагов, ГОТОВЫЙ
    сниппет с живым токеном, Stripe-блок, сводка каналов."""
    tenant = _tenant_arg()
    host = _os.environ.get('SAAS_HOST', '').strip()
    token = _snippet_token(tenant)

    # Тег с ДЕКЛАРАТИВНОЙ привязкой юзера: серверный шаблон клиента подставит
    # data-user-id/email залогиненного - события сразу крепятся к юзеру, без
    # ручного ra.identify. Плейсхолдеры USER_ID/USER_EMAIL клиент заменит.
    snippet_html = (
        f'<script src="https://{host}/snippet/ra.js"\n'
        f'        data-endpoint="https://{host}/ingest/saas/events"\n'
        f'        data-token="{token}" data-tenant="{tenant}"\n'
        f'        data-user-id="USER_ID" data-user-email="USER_EMAIL"></script>'
    ) if host and token else ''

    live_customers = int(q(
        "SELECT count() FROM stripe_customers WHERE tenant_id = {t:String} "
        "AND NOT startsWith(customer_id, 'cus_mock') "
        "AND NOT startsWith(customer_id, 'cus_demo')",
        {'t': tenant})[1][0][0])
    snippet_events = int(q(
        "SELECT count() FROM saas_events WHERE tenant_id = {t:String} AND source = 'snippet'",
        {'t': tenant})[1][0][0])

    # Событий нет, но с сайта СТУЧАТСЯ с неподходящим ключом? Это почти всегда
    # старый код на сайте после перевыпуска токена. Молчать про это - обречь
    # клиента искать ошибку у себя.
    rejects = q(
        "SELECT count(), max(ts), any(origin), any(token_prefix) "
        "FROM ingest_rejects WHERE tenant_id = {t:String} "
        "AND ts >= now() - INTERVAL 24 HOUR", {'t': tenant})[1][0]
    reject_info = ({'count': int(rejects[0]), 'last_seen': str(rejects[1]),
                    'origin': str(rejects[2] or ''),
                    'token_prefix': str(rejects[3] or '')}
                   if int(rejects[0]) > 0 and snippet_events == 0 else None)

    # Для кнопки «проверить сейчас»: когда последний раз что-то приходило.
    last_event = q(
        "SELECT toString(max(ts)) FROM saas_events "
        "WHERE tenant_id = {t:String} AND source = 'snippet'", {'t': tenant})[1][0][0]

    # РАЗБОР ПО СИГНАЛАМ. «События идут» - ещё не значит «продукт подключён»:
    # без identify мы видим визиты, но не людей; без момента ценности мертвы
    # стадии «не начал пользоваться» и «затих». Показываем это отдельно,
    # чтобы клиент видел, чего именно не хватает, а не гадал.
    sig = q(
        "SELECT countIf(client_user_id != '') AS identified, "
        "countIf(event_type IN ('value_moment', 'generation_completed')) AS vm, "
        "countIf(event_type = 'page_view') AS pv, "
        "countIf(event_type = 'cancel_flow_started') AS cf "
        "FROM saas_events WHERE tenant_id = {t:String} AND source = 'snippet'",
        {'t': tenant})[1][0]
    signals = {'identified': int(sig[0]), 'value_moments': int(sig[1]),
               'page_views': int(sig[2]), 'cancel_flow': int(sig[3])}

    ch = _channels_payload(tenant)['channels']
    camp_conf = _campaigns_conf(tenant)

    offers_list = _tenant_offers(tenant)
    offers_edited = any(o['edited'] for o in offers_list)
    offers_reviewed = bool((ca.load_tenants().get(tenant, {}) or {}).get('offers_reviewed'))

    _tc = ca.load_tenants().get(tenant, {}) or {}

    return api_json({
        'tenant': tenant,
        'steps': {
            'snippet': snippet_events > 0,
            'stripe': live_customers > 0,
            'channels': _any_channel_active(tenant),
            'offers': offers_edited or offers_reviewed,
            'autopilot': _autopilot_resolved(camp_conf, tenant),
        },
        'autopilot_blockers': _autopilot_blockers(tenant),
        'offers': offers_list,
        'snippet': {'token': token, 'html': snippet_html, 'rejects': reject_info,
                    'events': snippet_events, 'last_event': str(last_event or ''),
                    'signals': signals,
                    'ingest_url': f'https://{host}/ingest/saas/events' if host else ''},
        'stripe': {
            # URL СВОЙ у каждого пространства: без хвоста события некуда класть
            'webhook_url': f'https://{host}/stripe/webhook/{tenant}' if host else '',
            'events': ['checkout.session.completed', 'customer.subscription.created',
                       'customer.subscription.updated', 'customer.subscription.deleted',
                       'invoice.paid', 'invoice.payment_failed',
                       'charge.refunded', 'charge.dispute.created'],
            'secret_set': bool(str(_tc.get('stripe_webhook_secret') or '').strip()),
            'api_key_set': bool(str(_tc.get('stripe_api_key') or '').strip()),
        },
        'channels': [{'channel': c['channel'], 'state': c['state']} for c in ch],
        'answers': _tc.get('onboarding_answers') or {},
        'ai_enabled': _ai_enabled(),
    })


def _ai_enabled() -> bool:
    """AI-компоновщик доступен: любой из ключей (Anthropic приоритетнее)."""
    return _platform('ANTHROPIC_API_KEY') or _platform('OPENAI_API_KEY')


def _avg_plan_price(tenant: str) -> float:
    """Средний чек из Stripe-планов (важнее ручного ответа опросника)."""
    try:
        return _flt(q(
            "SELECT coalesce(avg(toFloat64(mrr)), 0) FROM tenant_plans_current "
            "WHERE tenant_id = {t:String} AND mrr > 0", {'t': tenant})[1][0][0])
    except Exception:
        return 0.0


def _measured_costs(tenant: str) -> dict:
    """Измеренная экономика (product_sync -> knowledge). {} - замера ещё нет."""
    try:
        from stripe_sync.knowledge import load as kb_load
        return kb_load(_ch_direct(), tenant, 'measured_costs')
    except Exception:
        return {}


@bp.post('/saas/scan')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_scan_site():
    """Прочитать сайт клиента и достать профиль продукта (предзаполнение
    опросника). Ничего не сохраняет как ответы - владелец правит и жмёт
    «Собрать офферы» сам."""
    from stripe_sync.site_scan import scan

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    from stripe_sync.client_brief import (BRIEF_VERSION, answers_from_brief,
                                          diff_briefs)
    from stripe_sync.site_scan import analyse

    body = request.get_json(silent=True) or {}
    url = str(body.get('url', ''))
    tc = ca.load_tenants().get(tenant, {}) or {}
    if not url:
        # «Проанализировать заново» - берём адрес из прошлого разбора
        url = str((tc.get('client_brief') or {}).get('site_url')
                  or (tc.get('onboarding_answers') or {}).get('app_url') or '')
    if not url:
        return _bad('invalid_url')

    facts, brief, visited, note = analyse(url)
    if note in ('invalid_url', 'site_unreachable'):
        return _bad(note)

    from stripe_sync import knowledge as kb
    from stripe_sync.economics import build as build_economics
    from stripe_sync.economics import with_measured

    ch = _ch_direct()
    prev = kb.load(ch, tenant, 'brief')
    prev_snapshot = {**(prev.get('analysis') or {}),
                     'plans': (prev.get('facts') or {}).get('plans') or []}
    now_snapshot = {**brief, 'plans': facts.get('plans') or []}
    changes = diff_briefs(prev_snapshot, now_snapshot) if prev else []

    answers = tc.get('onboarding_answers') or {}
    prefill = answers_from_brief(brief, facts)
    econ = build_economics(facts.get('plans') or [],
                           with_measured({**prefill, **answers},
                                         kb.load(ch, tenant, 'measured_costs')))

    if facts or brief:
        # ЗНАНИЕ - в своё хранилище с версиями (секреты туда не попадают),
        # факты дополнительно в конфиг: их читают промпты офферов и текстов.
        kb.save(ch, tenant, 'brief',
                {'version': BRIEF_VERSION, 'site_url': url,
                 'facts': facts, 'analysis': brief, 'pages': visited}, url)
        kb.save(ch, tenant, 'economics', econ, url)
        ca.update_tenant(tenant, {'site_profile': facts,
                                  'site_scanned_pages': visited})
        # Цвет бренда - из того же разбора сайта: им красятся письма кампаний.
        # Руками выставленный цвет (source != scan) скан не перетирает.
        if not tc.get('brand_color') or tc.get('brand_color_source') == 'scan':
            from stripe_sync.site_scan import brand_color_from_url
            bc = brand_color_from_url(url)
            if bc:
                ca.update_tenant(tenant, {'brand_color': bc,
                                          'brand_color_source': 'scan'})
                print(f'[scan] {tenant}: brand_color {bc}', flush=True)
    print(f'[scan] {tenant}: {url} -> {"ok" if facts else note} '
          f'({len(visited)} страниц, изменений: {len(changes)})', flush=True)
    return api_json({'profile': facts, 'brief': brief, 'pages': visited,
                     'note': note, 'changes': changes, 'economics': econ,
                     'prefill': prefill})


@bp.get('/saas/questionnaire')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_questionnaire():
    """Опросник селф-онбординга офферов + сохранённые ответы."""
    from stripe_sync.compose import QUESTIONS
    tenant = _tenant_arg()
    answers = (ca.load_tenants().get(tenant, {}) or {}).get('onboarding_answers') or {}
    return api_json({'questions': QUESTIONS, 'answers': answers,
                     'ai_enabled': _ai_enabled(),
                     'avg_plan_price': _avg_plan_price(tenant)})


@bp.post('/saas/questionnaire')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_questionnaire_submit():
    """Селф-онбординг: ответы -> детерминированная сборка офферов
    (compose_offers) + AI-слой при наличии ANTHROPIC_API_KEY (каждый AI-оффер
    валидируется теми же схемами). Пересборка идемпотентна (A_/AI_)."""
    from stripe_sync import overrides as ovr
    from stripe_sync.compose import compose_offers, validate_answers

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    raw = (request.get_json(silent=True) or {}).get('answers') or {}
    answers, reason = validate_answers(raw)
    if reason:
        return _bad(reason)

    from stripe_sync.economics import with_measured
    avg_price = _avg_plan_price(tenant) or float(answers.get('avg_plan_price') or 0)
    base = compose_offers(with_measured(answers, _measured_costs(tenant)), avg_price)

    # контекст с сайта клиента (аудитория, момент ценности, тарифы) - в промпты
    site = (ca.load_tenants().get(tenant, {}) or {}).get('site_profile') or {}
    if site:
        answers = {**answers, 'site_profile': site}

    ai_note = 'ai_not_configured'
    ai_offers = []
    if _ai_enabled():
        from stripe_sync.ai_compose import ai_compose
        from stripe_sync.business_context import business_context
        _bctx = business_context(_ch_direct(), tenant, answers)
        ai_offers, ai_note = ai_compose(answers, avg_price, context=_bctx)

    # AI-набор (если есть) вытесняет детерминированный: он богаче, но прошёл
    # те же схемы; без AI - живёт база. Ручные C_ офферы не трогаются.
    final = list(ai_offers) if ai_offers else list(base)

    # ДОБОР: у каждой цепочки с offer-шагом должен быть оффер. Роли, которые
    # модель не покрыла (частый случай - winback), закрываем детерминированным
    # оффером из compose - иначе шаг молча логировал бы no_offer_bound.
    needed = {'activation', 'conversion', 'save', 'upgrade', 'winback'}
    covered = {str(o.get('role') or '') for o in final}
    added = []
    for o in base:
        r = str(o.get('role') or '')
        if r in needed and r not in covered:
            final.append(o)
            covered.add(r)
            added.append(o['offer_id'])
    if added:
        print(f'[onboarding] {tenant}: добор ролей детерминированными: {added}', flush=True)

    from stripe_sync.compose import dedupe_offers
    final = dedupe_offers(final)          # один подарок - одна строка в каталоге
    ovr.replace_auto_offers(tenant, final)
    ca.update_tenant(tenant, {'onboarding_answers': answers,
                              'offers_reviewed': True,
                              'callback_url': answers.get('callback_url') or None})

    # Тексты кампаний под продукт: ПОЛНЫЙ рефреш каждого текстового шага -
    # AI-текст, иначе детерминированный шаблон, иначе сброс к базе. Иначе при
    # ресабмите отброшенный гардом AI-шаг оставлял текст ПРЕЖНЕГО продукта.
    from stripe_sync.compose import compose_campaign_copy
    det_map = compose_campaign_copy(answers)
    ai_map = {}
    copy_note = 'deterministic'
    if _ai_enabled():
        from stripe_sync.ai_compose import ai_compose_copy
        from stripe_sync.business_context import business_context
        ai_map, note = ai_compose_copy(
            answers, context=business_context(_ch_direct(), tenant, answers))
        copy_note = 'ai' if ai_map else note

    conf = _campaigns_conf(tenant)
    by_id = {c['campaign_id']: c for c in conf.get('campaigns', [])}
    written = 0
    for cid, camp in by_id.items():
        for i, step in enumerate(camp.get('steps', [])):
            if step.get('action') == 'offer':
                continue
            txt = (ai_map.get(cid) or {}).get(i) or (det_map.get(cid) or {}).get(i)
            if txt:
                ovr.set_campaign_step(tenant, cid, i,
                                      {'subject': txt.get('subject', ''),
                                       'body': txt.get('body', ''),
                                       'src': 'generated'})
                written += 1
            else:
                ovr.set_campaign_step(tenant, cid, i, None)

    # Привязка авто-офферов к offer-шагам каркаса (роль -> шаг).
    bind_roles = {'K1_activation': 'activation', 'K2_trial_conversion': 'conversion',
                  'K4_save': 'save', 'K5_upgrade': 'upgrade', 'K6_winback': 'winback'}
    by_role = {}
    for o in final:
        r = str(o.get('role') or '')
        if r and r not in by_role:
            by_role[r] = o['offer_id']
    # фолбэк по подстроке id - для офферов без role
    for o in final:
        oid = o['offer_id'].lower()
        for role, marker in (('activation', 'bonus'), ('conversion', 'trial'),
                             ('save', 'pause'), ('upgrade', 'discount'), ('winback', 'winback')):
            if role not in by_role and marker in oid:
                by_role[role] = o['offer_id']
    bound = 0
    for cid, role in bind_roles.items():
        camp = by_id.get(cid)
        oid = by_role.get(role)
        if not camp or not oid:
            continue
        for i, st in enumerate(camp['steps']):
            if st.get('action') == 'offer':
                ovr.set_campaign_step(tenant, cid, i,
                                      {'offer_id': oid, 'src': 'generated'})
                bound += 1
                break

    print(f'[onboarding] {tenant}: опросник -> {len(final)} офферов '
          f'(ai={"yes" if ai_offers else ai_note}), тексты={copy_note} '
          f'({written} шагов), офферы привязаны к {bound} шагам', flush=True)
    return api_json({'created': [o['offer_id'] for o in final],
                     'ai': bool(ai_offers), 'ai_note': ai_note,
                     'copy': copy_note, 'copy_steps': written,
                     'offers_bound': bound})


@bp.post('/saas/onboarding/offers-reviewed')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_onboarding_offers_reviewed():
    """Владелец подтвердил, что просмотрел каталог офферов (шаг онбординга)."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    ca.update_tenant(tenant, {'offers_reviewed': True})
    return saas_onboarding()


@bp.get('/saas/users')
@require_auth(roles=CLIENT_READ_ROLES)
def saas_users():
    """Список юзеров SaaS-контура: identity + стадия + действие + скоры.
    ?stage=DUNNING - фильтр; сортировка: ценность на кону, затем MRR."""
    tenant = _tenant_arg()
    stage = (request.args.get('stage') or '').upper()
    online_only = str(request.args.get('online') or '') in ('1', 'true')
    search = str(request.args.get('q') or '').strip().lower()[:120]
    seen = str(request.args.get('seen') or '').strip()        # 1d | 7d | 30d
    pay = str(request.args.get('status') or '').strip()       # paying|trial|free

    where = "tenant_id = {t:String}"
    params = {'t': tenant}
    if stage:
        where += " AND stage = {s:String}"
        params['s'] = stage
    if online_only:
        # «сейчас на сайте»: последнее событие младше порога presence
        where += (" AND toUnixTimestamp(last_seen) > 0"
                  f" AND dateDiff('second', last_seen, now()) < {ONLINE_THRESHOLD_S}")
    if search:
        # поиск по почте / id юзера / Stripe-клиенту, без регистра
        where += (" AND (positionCaseInsensitive(email_norm, {srch:String}) > 0"
                  " OR positionCaseInsensitive(client_user_id, {srch:String}) > 0"
                  " OR positionCaseInsensitive(stripe_customer_id, {srch:String}) > 0)")
        params['srch'] = search
    if seen in ('1d', '7d', '30d'):
        days = {'1d': 1, '7d': 7, '30d': 30}[seen]
        where += (" AND toUnixTimestamp(last_seen) > 0"
                  f" AND last_seen >= now() - INTERVAL {days} DAY")
    if pay == 'paying':
        where += " AND sub_status IN ('active', 'past_due')"
    elif pay == 'trial':
        where += " AND sub_status = 'trialing'"
    elif pay == 'free':
        where += " AND sub_status NOT IN ('active', 'past_due', 'trialing')"

    # Фильтр по типу контакта (?contact=email,telegram&no_contact=1&contact_consent=1).
    # Тот же движок, что у сегментов кампаний - alias пустой (FROM user_actions
    # без псевдонима). {t:String} уже в params.
    from stripe_sync import segment as _seg
    c_tokens = str(request.args.get('contact') or '').strip()
    c_no = str(request.args.get('no_contact') or '') in ('1', 'true')
    c_consent = str(request.args.get('contact_consent') or '') in ('1', 'true')
    if c_tokens or c_no:
        c_conds, _cu = _seg.contact_conditions(c_tokens, c_no, c_consent, alias='')
        for c in c_conds:
            where += f" AND {c}"

    rows = q(
        f"""
        SELECT identity_id, email_norm, client_user_id, stripe_customer_id,
               sub_status, plan_id, toFloat64(mrr), stage, recommended_action,
               value_at_stake, coalesce(p_convert, 0), coalesce(p_churn, 0),
               coalesce(ltv_estimate, 0),
               if(toUnixTimestamp(last_seen) = 0, '', toString(last_seen)),
               stage_note,
               if(toUnixTimestamp(last_seen) = 0, 1000000,
                  dateDiff('second', last_seen, now()))
        FROM user_actions WHERE {where}
        ORDER BY value_at_stake DESC, mrr DESC
        LIMIT 500
        """, params)[1]

    users = [{
        'identity_id': r[0], 'email': r[1], 'client_user_id': r[2],
        'stripe_customer_id': r[3], 'sub_status': r[4], 'plan_id': r[5],
        'mrr': round(_flt(r[6]), 2), 'stage': r[7], 'action': r[8],
        'value_at_stake': round(_flt(r[9]), 2),
        'p_convert': round(_flt(r[10]), 2), 'p_churn': round(_flt(r[11]), 2),
        'ltv': round(_flt(r[12]), 2), 'last_seen': r[13],
        'stage_note': r[14],
        'online': len(r) > 15 and _flt(r[15]) < ONLINE_THRESHOLD_S,
    } for r in rows]

    # Пометки контактов: один проход по contacts_current + телефоны Stripe,
    # аннотируем срез в Python (дёшево, срез <= 500). email/inapp - из строки.
    chan_by_cuid: dict[str, set] = {}
    for cuid, chan in q(
            "SELECT client_user_id, channel FROM contacts_current "
            "WHERE tenant_id = {t:String} AND client_user_id != ''",
            {'t': tenant})[1]:
        chan_by_cuid.setdefault(str(cuid), set()).add(str(chan))
    phone_cids = {str(r[0]) for r in q(
        "SELECT DISTINCT customer_id FROM stripe_customers "
        "WHERE tenant_id = {t:String} AND phone != ''", {'t': tenant})[1]}
    for u in users:
        chans = chan_by_cuid.get(u['client_user_id'], set()) if u['client_user_id'] else set()
        has_phone = bool(chans & {'whatsapp', 'sms'}) or u['stripe_customer_id'] in phone_cids
        u['contacts'] = {
            'email': bool(u['email']),
            'inapp': bool(u['client_user_id']),
            'whatsapp': 'whatsapp' in chans,
            'telegram': 'telegram' in chans,
            'sms': 'sms' in chans,
            'phone': has_phone,
        }

    stages = {r[0]: int(r[1]) for r in q(
        "SELECT stage, count() FROM user_actions WHERE tenant_id = {t:String} GROUP BY stage",
        {'t': tenant})[1]}

    # счётчик «сейчас на сайте» для чипа фильтра - всегда по всем, не по срезу
    online_count = int(q(
        "SELECT count() FROM user_actions WHERE tenant_id = {t:String}"
        " AND toUnixTimestamp(last_seen) > 0"
        f" AND dateDiff('second', last_seen, now()) < {ONLINE_THRESHOLD_S}",
        {'t': tenant})[1][0][0])

    # Плашка «это демо-данные» появляется, только если мы РЕАЛЬНО насыпали
    # моков. Раньше признаком было «нет живых клиентов Stripe» - и плашка врала
    # дважды: на пустом тенанте и у клиента, который поставил сниппет раньше,
    # чем подключил биллинг.
    mock_customers = int(q(
        "SELECT count() FROM stripe_customers WHERE tenant_id = {t:String} "
        "AND (startsWith(customer_id, 'cus_mock') "
        "OR startsWith(customer_id, 'cus_demo'))",
        {'t': tenant})[1][0][0])
    demo = mock_customers > 0

    return api_json({'tenant': tenant, 'stages': stages, 'users': users,
                     'online_count': online_count, 'demo': demo})


@bp.get('/saas/offers')
@require_auth(roles=LEAK_ROLES)
def saas_offers():
    """Каталог офферов тенанта (stripe_sync/offers_catalog.json - есть в образе
    борда: COPY . .) + статистика выдач из offers_issued."""
    import json as _json
    import os as _os

    tenant = _tenant_arg()
    path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         'stripe_sync', 'offers_catalog.json')
    from stripe_sync import overrides as ovr
    _base = _json.load(open(path))
    catalog = ovr.merge_catalog({**(_base.get('_default') or {}),
                                 **(_base.get(tenant) or {})},
                                ovr.load_tenant(tenant))

    stats = {r[0]: {'issued': int(r[1]), 'dry_run': int(r[2]),
                    'holdout': int(r[3]), 'rejected': int(r[4])}
             for r in q(
        """
        SELECT offer_id, countIf(status = 'issued'), countIf(status = 'dry_run'),
               countIf(status = 'holdout'), countIf(status = 'rejected')
        FROM offers_issued WHERE tenant_id = {t:String} GROUP BY offer_id
        """, {'t': tenant})[1]}

    offers = [{
        'offer_id': o['offer_id'], 'title': o['title'], 'executor': o['executor'],
        'monetary': bool(o.get('monetary')),
        'cost_estimate': _flt(o.get('cost_estimate')),
        'max_per_user_30d': int(o.get('max_per_user_30d') or 0),
        'params': o.get('params') or {},
        'role': str(o.get('role') or ''),
        'edited': bool(o.get('_edited')),
        'custom': bool(o.get('_custom')),
        'disabled': bool(o.get('_disabled')),
        'stats': stats.get(o['offer_id'],
                           {'issued': 0, 'dry_run': 0, 'holdout': 0, 'rejected': 0}),
    } for o in catalog.get('offers', [])]

    # ЭКОНОМИКА РЯДОМ С КАЖДЫМ ПОДАРКОМ. Без неё каталог - список технических
    # строк: непонятно, кому это уйдёт, когда и во что обойдётся.
    from stripe_sync.economics import gross_margin, unit_cost, unit_price, verdict
    # ТИПОВОЙ тариф, а не средний по лестнице: экономика подарка считается от
    # того, что платит обычный клиент, а не от среднего между стартовым и топом
    ladder = sorted(_flt(r[0]) for r in q(
        "SELECT toFloat64(mrr) FROM tenant_plans_current "
        "WHERE tenant_id = {t:String} AND mrr > 0", {'t': tenant})[1])
    price = (ladder[len(ladder) // 2] if len(ladder) >= 3
             else (ladder[0] if ladder else 0.0))

    # ОКУПАЕМОСТЬ СЧИТАЕТСЯ ИЗ МАРЖИ, А НЕ ИЗ ЧЕКА. Тариф за $99 с валовой
    # маржой 10% приносит $10 в месяц: подарок возвращается из этих $10.
    answers = (ca.load_tenants().get(tenant, {}) or {}).get('onboarding_answers') or {}
    units = _flt(answers.get('monthly_units'))
    u_cost, cost_basis = unit_cost(answers, unit_price(price, units))
    margin = gross_margin(answers)
    if margin is None and cost_basis in ('stated', 'assumed') and units and price:
        u_price = unit_price(price, units)
        if u_price and u_cost is not None:
            margin = round(max(0.0, 1.0 - u_cost / u_price), 4)

    role_stage = {'activation': 'ACTIVATE', 'conversion': 'CONVERT',
                  'dunning': 'DUNNING', 'save': 'SAVE', 'upgrade': 'UPGRADE',
                  'winback': 'WINBACK'}
    # ЛЕСТНИЦА УСТУПОК И ЦЕННОСТЬ СДЕЛКИ. Оффер - это обмен: отдаём часть маржи
    # сейчас, чтобы сохранить поток маржи потом. Порядок и пригодность считает
    # offer_value; здесь он применяется к типовому клиенту, чтобы владелец видел
    # ту же арифметику, по которой система будет выбирать подарок в цепочке.
    from stripe_sync.offer_value import (TIER_NAMES, gift_budget, margin_at_stake,
                                         rank, tier_of, uplift_or_prior)
    monthly_margin = round(price * margin, 2) if (price and margin) else None
    stake = margin_at_stake(monthly_margin, 12)
    budget = gift_budget(stake)

    candidates = []
    for o in offers:
        role = str(o.get('role') or '')
        o['stage'] = role_stage.get(role, '')
        # cost_estimate у денежных подарков - это ЖИВЫЕ деньги (себестоимость
        # подаренного или прямой кредит); у скидок и паузы - недополученная
        # выручка, которая из кармана не уходит.
        cash = (_flt(o.get('cost_estimate'))
                if o.get('executor') in ('client_callback', 'balance_credit') else 0.0)
        if o.get('executor') == 'client_callback' and \
                str((o.get('params') or {}).get('command') or '').endswith('_discount'):
            cash = 0.0                 # скидка на докупку живых денег не уносит
        o['economics'] = (verdict(o.get('cost_estimate'), price, margin, cash)
                          if price else {})
        if o['economics']:
            o['economics']['basis'] = cost_basis
        lift, lift_src = uplift_or_prior(None, str(o.get('executor') or ''))
        o['uplift_source'] = lift_src
        candidates.append({'offer_id': o['offer_id'], 'executor': o.get('executor'),
                           'params': o.get('params') or {}, 'cash': cash,
                           'revenue': max(0.0, _flt(o.get('cost_estimate')) - cash),
                           'uplift': lift})

    # Лестница действует ВНУТРИ СТАДИИ. Подарок для «не начал пользоваться» и
    # подарок для «собирается уходить» уйдут разным людям и не конкурируют:
    # ранжировать их вместе значит блокировать один другим без причины.
    stage_of = {o['offer_id']: o.get('stage') or '' for o in offers}
    # Самая частая названная причина ухода: под неё подбирается рычаг. Общий
    # оффер спасает 5-10% уходящих, подобранный под причину - 15-30%.
    top_reason = ''
    try:
        rows = q("SELECT category FROM retention.cancel_reasons "
                 "WHERE tenant_id = {t:String} AND category != 'other' "
                 "GROUP BY category ORDER BY count() DESC LIMIT 1", {'t': tenant})[1]
        top_reason = str(rows[0][0]) if rows else ''
    except Exception:                     # таблицы может не быть - это не отказ
        top_reason = ''

    by_id = {}
    for stage in set(stage_of.values()):
        group = [c for c in candidates if stage_of.get(c['offer_id']) == stage]
        # причина ухода осмысленна только там, где человек уже уходит
        reason = top_reason if stage in ('SAVE', 'WINBACK') else ''
        by_id.update({r['offer_id']: r for r in
                      rank(group, stake, budget, reason=reason)})

    # РАЗБОР ПО МЕТОДОЛОГИИ. Каталог мог собраться правилами год назад, а
    # экономика клиента с тех пор изменилась: разбор пересчитывается на каждом
    # открытии экрана и говорит, что в наборе стало неверным.
    from stripe_sync.offer_review import review_catalog, split_catalog_notes
    cash_by_id = {c['offer_id']: c['cash'] for c in candidates}
    reviewed = review_catalog(
        [{**o, '_cash': cash_by_id.get(o['offer_id']),
          '_stage': o.get('stage')} for o in offers],
        {'cost_basis': cost_basis, 'gross_margin': margin,
         'monthly_margin': monthly_margin, 'gift_budget': budget,
         'reason': top_reason,
         'has_topup': any(str((o.get('params') or {}).get('command') or '')
                          .endswith('_discount') for o in offers)})
    reviewed, catalog_notes = split_catalog_notes(reviewed)
    review_by_id = {r['offer_id']: r for r in reviewed}
    for o in offers:
        row = by_id.get(o['offer_id'])
        if not row:
            o['tier'] = tier_of({'executor': o.get('executor'),
                                 'params': o.get('params') or {}})
            o['tier_name'] = TIER_NAMES.get(o['tier'], '')
            continue
        o['tier'] = row['tier']
        o['tier_name'] = row['tier_name']
        o['ev'] = row['ev']
        o['blocked'] = row['blocked']

    for o in offers:
        r = review_by_id.get(o['offer_id']) or {}
        o['review'] = {'verdict': r.get('verdict', 'ok'),
                       'flags': r.get('flags', []),
                       'alternative': r.get('alternative')}

    return api_json({'tenant': tenant, 'control_pct': catalog.get('control_pct', 10),
                     'p_convert_cap': catalog.get('p_convert_cap'),
                     'churn_floor': catalog.get('churn_floor'),
                     'monthly_price': round(price, 2) if price else None,
                     'monthly_margin': monthly_margin,
                     'margin_at_stake': stake,
                     'gift_budget': budget,
                     'cost_basis': cost_basis,
                     'catalog_notes': catalog_notes,
                     'offers': offers})


# ── Каналы: клиентский флоу подключения (Phase 4) ────────────────────────────
# Партнёрская модель: аккаунты провайдеров наши, клиент подключает только
# идентичность бренда (поддомен, альфа-имя, свой бот). Состояние - в
# secrets/tenants.json (том rw у board), пишет его stripe_sync.channels_admin.

import os as _os
import secrets as _secrets

from stripe_sync import channels_admin as ca


def _tenant_resend_key(tenant: str) -> str:
    """Ключ Resend для тенанта: свой аккаунт клиента > платформенный."""
    own = str((ca.load_tenants().get(tenant, {}) or {}).get('resend_api_key') or '').strip()
    return own or _os.environ.get('RESEND_API_KEY', '').strip()


def _platform(name: str) -> bool:
    return bool(_os.environ.get(name, '').strip())


def _requested_tenant() -> str:
    return str(request.args.get('tenant')
               or (request.get_json(silent=True) or {}).get('tenant') or '')


def resolve_tenant(scope: str, requested: str, default: str) -> tuple[str, str]:
    """(tenant, '') либо ('', reason). Скоуп '*' - платформа: любой запрошенный
    или дефолт; клиентский скоуп - ТОЛЬКО свой тенант (чужой -> forbidden);
    пустой скоуп (сбой/нет строки) - fail-closed."""
    if scope == '*':
        return (requested or default), ''
    if not scope:
        return '', 'tenant_scope_unresolved'
    if requested and requested != scope:
        return '', 'forbidden_tenant'
    return scope, ''


def _default_tenant() -> str:
    """Дефолт платформенного пользователя: TENANT_ID из env, иначе единственное
    заведённое пространство. Двух и больше - выбирай явно (?tenant=)."""
    import os as _os
    env = _os.environ.get('TENANT_ID', '').strip()
    if env:
        return env
    # Сервисные пространства (сквозные самопроверки платформы) не считаются:
    # появление ra-selftest не должно отбирать дефолт у единственного живого
    # клиента - иначе у супер-админа 400 на каждом экране.
    conf = ca.load_tenants()
    known = sorted(t for t in _known_tenants()
                   if not (conf.get(t, {}) or {}).get('service'))
    return known[0] if len(known) == 1 else ''


def _tenant_arg() -> str:
    """Эффективный тенант ЧТЕНИЯ с изоляцией по скоупу пользователя.
    При нарушении скоупа поднимаем 403 через flask.abort."""
    from flask import abort, make_response
    tenant, reason = resolve_tenant(current_tenant_scope(), _requested_tenant(),
                                    _default_tenant())
    if reason:
        abort(make_response(api_json(None, 403, reason)))
    if not tenant:
        abort(make_response(api_json(None, 400, 'no_tenant_selected')))
    return tenant


def _known_tenants() -> set:
    """Тенанты, в которые разрешена ЗАПИСЬ: git-конфиг кампаний (кроме
    _default) + уже заведённые в tenants.json. Иначе ?tenant=мусор плодил бы
    фантомные записи в runtime-файлах."""
    import json as _json
    import os as _os
    from pathlib import Path as _Path
    out = set(ca.load_tenants().keys())
    p = _Path(__file__).resolve().parent.parent / 'stripe_sync' / 'saas_campaigns.json'
    try:
        out |= {k for k in _json.loads(p.read_text()).keys() if k != '_default'}
    except Exception:
        pass
    try:
        with open(_os.environ.get('TOKENS_FILE', '/secrets/tokens.json')) as fh:
            out |= {k for k in _json.load(fh).keys() if not k.startswith('_')}
    except Exception:
        pass
    return out


def _tenant_arg_write():
    """(tenant, None) либо (None, error-response) для write-ручек."""
    t = _tenant_arg()
    if t not in _known_tenants():
        return None, _bad('unknown_tenant', 404)
    return t, None


def _channels_payload(tenant: str) -> dict:
    email_users = int(q(
        "SELECT countIf(email_norm != '') FROM user_actions WHERE tenant_id = {t:String}",
        {'t': tenant})[1][0][0])

    cov = {r[0]: {'contacts': int(r[1]), 'consented': int(r[2])} for r in q(
        """
        SELECT channel, count(), countIf(consent = 1)
        FROM contacts_current WHERE tenant_id = {t:String} GROUP BY channel
        """, {'t': tenant})[1]}

    tch = ca.load_tenants().get(tenant, {}) or {}
    resend_key = bool(_tenant_resend_key(tenant))
    dt_key = _platform('DECISION_API_KEY')
    bot_user = str(tch.get('telegram_bot_username', ''))

    # In-app: живёт на сниппете - "подключён", если события сниппета идут
    # и юзеры идентифицированы (им есть кому показывать баннеры).
    identified = int(q(
        "SELECT countIf(client_user_id != '') FROM user_actions "
        "WHERE tenant_id = {t:String}", {'t': tenant})[1][0][0])
    snippet_alive = int(q(
        "SELECT count() FROM saas_events WHERE tenant_id = {t:String} "
        "AND source = 'snippet' AND ts > now() - INTERVAL 7 DAY",
        {'t': tenant})[1][0][0]) > 0

    channels = [
        {'channel': 'email', 'provider': 'Resend', 'state': ca.email_state(tch, resend_key),
         'detail': tch.get('email_from') or tch.get('email_domain', ''),
         'contacts': email_users, 'consented': email_users,
         'email': {'domain': tch.get('email_domain', ''),
                   'from': tch.get('email_from', ''),
                   'own_account': bool(tch.get('resend_api_key')),
                   'webhook_secret_set': bool(tch.get('resend_webhook_secret')),
                   # этот URL клиент вставляет в Resend - Webhooks
                   'webhook_url': (f'https://{_host()}/public/resend/webhook?tenant={tenant}'
                                   if _host() else ''),
                   # брендинг писем: цвет кнопки/шапки и его происхождение
                   'brand_color': tch.get('brand_color', ''),
                   'brand_color_source': tch.get('brand_color_source', ''),
                   'dns_records': tch.get('email_dns_records', [])}},
        {'channel': 'inapp', 'provider': 'Site snippet',
         'state': 'active' if snippet_alive and identified else 'not_connected',
         'detail': '', 'contacts': identified, 'consented': identified},
        {'channel': 'sms', 'provider': 'DecisionTelecom',
         'state': ca.messaging_state(tch, 'sms', dt_key),
         'detail': tch.get('sms_sender') or tch.get('requested_sms_sender', ''),
         **cov.get('sms', {'contacts': 0, 'consented': 0})},
        {'channel': 'viber', 'provider': 'DecisionTelecom',
         'state': ca.messaging_state(tch, 'viber', dt_key),
         'detail': tch.get('viber_sender') or tch.get('requested_viber_sender', ''),
         **cov.get('viber', {'contacts': 0, 'consented': 0})},
        {'channel': 'telegram', 'provider': 'Telegram Bot API',
         'state': ca.telegram_state(tch),
         'detail': f'@{bot_user}' if bot_user else '',
         'telegram': {'bot_username': bot_user,
                      'connect_link': f'https://t.me/{bot_user}?start=' if bot_user else ''},
         **cov.get('telegram', {'contacts': 0, 'consented': 0})},
        _wa_channel_row(tenant, tch, cov),
    ]
    return {'tenant': tenant, 'channels': channels}


def _wa_channel_row(tenant: str, tch: dict, cov: dict) -> dict:
    """Строка WhatsApp: Cloud API (WABA клиента), статусы шаблонов, вебхук."""
    connected = bool(tch.get('wa_token') and tch.get('wa_phone_number_id'))
    personal_status = str(tch.get('wa_personal_status') or '')
    registry = dict(tch.get('wa_templates') or {})
    import hashlib as _hl
    import hmac as _hm
    from stripe_sync.email_delivery import UNSUB_SECRET as _us
    host = _os.environ.get('SAAS_HOST', 'retivo.digital')
    return {
        'channel': 'whatsapp',
        'provider': 'Meta Cloud API' if connected else (
            'Personal number' if personal_status == 'WORKING' else 'Meta Cloud API'),
        'state': ('active' if connected or personal_status == 'WORKING'
                  else 'not_connected'),
        'detail': str(tch.get('wa_phone_display')
                      or tch.get('wa_personal_number') or ''),
        'whatsapp': {
            'personal': {'status': personal_status,
                         'number': str(tch.get('wa_personal_number') or ''),
                         'automation': bool(tch.get('wa_personal_automation')),
                         'daily_cap': int(tch.get('wa_personal_daily_cap') or 20)},
            'cloud_connected': connected,
            'phone_display': str(tch.get('wa_phone_display') or ''),
            'has_waba': bool(tch.get('wa_waba_id')),
            'has_app_secret': bool(tch.get('wa_app_secret')),
            'webhook_url': f'https://{host}/public/wa/webhook/{tenant}',
            'webhook_verify_token': _hm.new(
                _us.encode(), f'wawh|{tenant}'.encode(),
                _hl.sha256).hexdigest()[:32] if connected else '',
            'templates': [
                {'name': name, 'status': str(info.get('status') or ''),
                 'campaign_id': str(info.get('campaign_id') or ''),
                 'step_idx': int(info.get('step_idx') or 0),
                 'category': str(info.get('category') or ''),
                 'reason': str(info.get('reason') or '')}
                for name, info in sorted(registry.items())],
        },
        **cov.get('whatsapp', {'contacts': 0, 'consented': 0})}


@bp.get('/saas/channels')
@require_auth(roles=LEAK_ROLES)
def channels():
    return api_json(_channels_payload(_tenant_arg()))


# ── ИИ-аналитик: рекомендации и их применение ────────────────────────────────

@bp.get('/saas/insights')
@require_auth(roles=LEAK_ROLES)
def saas_insights():
    """Рекомендации ИИ-аналитика (Пн 08:10) + сводка причин отмены."""
    tenant = _tenant_arg()

    rows = q(
        """
        SELECT insight_id, campaign_id, step_idx, kind, title, rationale,
               suggestion, status, toString(period_start), toString(period_end)
        FROM ai_insights_current
        WHERE tenant_id = {t:String} AND status != 'dismissed'
        ORDER BY created_at_max DESC
        LIMIT 20
        """, {'t': tenant})[1]
    import json as _json
    insights = [{
        'insight_id': r[0], 'campaign_id': r[1], 'step_idx': int(r[2]),
        'kind': r[3], 'title': r[4], 'rationale': r[5],
        'suggestion': _json.loads(r[6] or '{}'), 'status': r[7],
        'period': f'{r[8]} - {r[9]}',
    } for r in rows]

    reasons = [{'category': r[0], 'count': int(r[1]), 'mrr': _flt(r[2]),
                'examples': list(r[3])[:3]} for r in q(
        """
        SELECT category, count(), sum(toFloat64(mrr)), groupArray(summary)
        FROM cancel_reasons WHERE tenant_id = {t:String}
        GROUP BY category ORDER BY count() DESC
        """, {'t': tenant})[1]]

    # Продуктовые гипотезы (product_insights, Вт 08:00): что менять в продукте
    product = None
    try:
        from stripe_sync.knowledge import load as _kb
        product = _kb(_ch_direct(), tenant, 'product_insights') or None
    except Exception:  # noqa: BLE001
        pass

    return api_json({'tenant': tenant, 'insights': insights,
                     'cancel_reasons': reasons, 'product': product})


@bp.post('/saas/insights/act')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_insight_act():
    """Применить рекомендацию (правка идёт через тот же overrides-слой, что и
    ручное редактирование) либо отклонить. LLM сам ничего не применяет."""
    from stripe_sync import overrides as ovr
    import json as _json

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    iid = str(body.get('insight_id', ''))
    action = str(body.get('action', ''))
    if action not in ('apply', 'dismiss'):
        return _bad('unknown_action')

    row = q(
        """
        SELECT campaign_id, step_idx, kind, suggestion, title, rationale,
               toString(period_start), toString(period_end)
        FROM ai_insights_current
        WHERE tenant_id = {t:String} AND insight_id = {i:String}
        """, {'t': tenant, 'i': iid})[1]
    if not row:
        return _bad('unknown_insight', 404)
    campaign_id, step_idx, kind, suggestion_raw = row[0][0], int(row[0][1]), row[0][2], row[0][3]
    sug = _json.loads(suggestion_raw or '{}')

    applied = ''
    if action == 'apply':
        if kind == 'change_delay' and step_idx >= 0:
            ovr.set_campaign_step(tenant, campaign_id, step_idx,
                                  {'delay_h': float(sug['delay_h'])})
            applied = f'delay_h={sug["delay_h"]}'
        elif kind == 'rewrite_copy' and step_idx >= 0:
            ovr.set_campaign_step(tenant, campaign_id, step_idx,
                                  {'subject': sug.get('subject', ''),
                                   'body': sug.get('body', ''), 'src': 'generated'})
            applied = 'copy'
        elif kind == 'cut_offer' and step_idx >= 0:
            ovr.set_campaign_step(tenant, campaign_id, step_idx, {'offer_id': ''})
            applied = 'offer_unbound'
        else:
            # drop_step/raise_cap/scale_up/no_action - решение владельца руками
            return _bad(f'manual_only:{kind}')

    # статус пишем новой строкой (ReplacingMergeTree по insight_id)
    import clickhouse_connect as _cc
    import os as _os4
    cl = _cc.get_client(host=_os4.environ.get('CH_HOST', 'clickhouse'),
                        port=int(_os4.environ.get('CH_PORT', '8123')),
                        username=_os4.environ.get('CH_USER', 'default'),
                        password=_os4.environ.get('CH_PASSWORD', ''),
                        database=_os4.environ.get('CH_DB', 'retention'))
    from datetime import datetime as _dt, timezone as _tz
    cl.insert('retention.ai_insights',
              [[tenant, iid, row[0][6], row[0][7], campaign_id, step_idx, kind,
                row[0][4], row[0][5], '{}', suggestion_raw,
                'applied' if action == 'apply' else 'dismissed',
                _dt.now(tz=_tz.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]]],
              column_names=['tenant_id', 'insight_id', 'period_start', 'period_end',
                            'campaign_id', 'step_idx', 'kind', 'title', 'rationale',
                            'evidence', 'suggestion', 'status', 'created_at'])
    print(f'[insight] {tenant}: {iid} -> {action} {applied}', flush=True)
    return api_json({'insight_id': iid, 'action': action, 'applied': applied})


# ── Кампании: что автопилот шлёт юзерам + рубильник ──────────────────────────

def _campaigns_conf(tenant: str) -> dict:
    import json as _json
    from pathlib import Path
    from stripe_sync import overrides as ovr
    p = Path(__file__).resolve().parent.parent / 'stripe_sync' / 'saas_campaigns.json'
    data = _json.loads(p.read_text()) if p.exists() else {}
    conf = data.get(tenant) or data.get('_default') or {}
    conf = ovr.merge_campaign_conf(conf, ovr.load_tenant(tenant))
    try:
        from stripe_sync.knowledge import load as _kb_load
        conf = ovr.apply_ab_winners(conf, _kb_load(_ch_direct(), tenant, 'ab_winners'))
    except Exception:
        pass
    return conf


def _autopilot_resolved(conf: dict, tenant: str) -> bool:
    tc = ca.load_tenants().get(tenant, {}) or {}
    if 'autopilot' in tc:
        return bool(tc['autopilot'])
    return bool(conf.get('autopilot'))


def _ab_stats(tenant: str, cid: str, step_idx: int, variants: list) -> dict:
    """Статистика A/B шага для экрана: отправки/открытия/клики по вариантам.

    Вариант юзера восстанавливается тем же хэшем, что его назначал движок
    (pick_variant) - хранить назначение не нужно. dry_run считаем отдельно:
    до включения автопилота владелец видит, что сплит уже делит людей."""
    from stripe_sync.ab_winner import winner as _winner

    # тот же хэш, что назначает вариант в движке (campaign_tick.pick_variant);
    # сам campaign_tick борду не импортировать - он flat-only (executors)
    import hashlib as _hl2

    def pick_variant(identity: str, campaign_id: str, step_idx_: int, n_: int) -> int:
        if n_ <= 1:
            return 0
        seed = f"{campaign_id}:{step_idx_}:{identity}".encode()
        return int(_hl2.md5(seed).hexdigest()[:8], 16) % n_

    n = len(variants)
    sent_rows = q("""
        SELECT identity_id, countIf(status = 'sent'), countIf(status = 'dry_run')
        FROM campaign_send_log
        WHERE tenant_id = {t:String} AND campaign_id = {c:String}
          AND step_idx = {i:UInt32} AND action = 'email'
          AND status IN ('sent', 'dry_run')
        GROUP BY identity_id
        """, {'t': tenant, 'c': cid, 'i': step_idx})[1]
    emails = {r[0]: str(r[1] or '').lower() for r in q(
        "SELECT identity_id, email_norm FROM identities_current "
        "WHERE tenant_id = {t:String}", {'t': tenant})[1]}
    engaged = {}
    for r in q("""
        SELECT lower(address), event_type FROM email_events
        WHERE tenant_id = {t:String} AND campaign_id = {c:String}
          AND step_idx = {i:UInt32} AND event_type IN ('opened', 'clicked')
        """, {'t': tenant, 'c': cid, 'i': step_idx})[1]:
        engaged.setdefault(str(r[0]), set()).add(str(r[1]))

    stats = [{'sent': 0, 'dry': 0, 'opened': 0, 'clicked': 0} for _ in range(n)]
    for ident, sent, dry in sent_rows:
        k = pick_variant(ident, cid, step_idx, n)
        stats[k]['sent'] += int(sent)
        stats[k]['dry'] += int(dry)
        ev = engaged.get(emails.get(ident, ''), set())
        if int(sent):
            stats[k]['opened'] += 1 if 'opened' in ev or 'clicked' in ev else 0
            stats[k]['clicked'] += 1 if 'clicked' in ev else 0

    win = _winner({k: {'sent': s['sent'], 'clicked': s['clicked']}
                   for k, s in enumerate(stats)})
    return {'variants': [{'subject': str((v or {}).get('subject') or ''),
                          **stats[k]} for k, v in enumerate(variants)],
            'winner': win}


def _campaigns_payload(tenant: str) -> dict:
    conf = _campaigns_conf(tenant)

    # Названия офферов: шаг цепочки хранит машинный id (AI_discount20_1mo),
    # а владелец должен видеть человеческое название подарка.
    import json as _json2
    import os as _os2
    from stripe_sync import overrides as _ovr
    _path = _os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))),
                           'stripe_sync', 'offers_catalog.json')
    _cbase = _json2.load(open(_path))
    _cat = _ovr.merge_catalog({**(_cbase.get('_default') or {}),
                               **(_cbase.get(tenant) or {})},
                              _ovr.load_tenant(tenant))
    offer_titles = {o['offer_id']: str(o.get('title') or o['offer_id'])
                    for o in _cat.get('offers', [])}

    enr = {r[0]: {'enrolled': int(r[1]), 'active': int(r[2]), 'holdout': int(r[3]),
                  'done': int(r[4]), 'exited': int(r[5])} for r in q(
        """
        SELECT campaign_id, count(), countIf(status = 'active'),
               countIf(control = 1), countIf(status = 'done'),
               countIf(status = 'exited')
        FROM campaign_enrollments_current WHERE tenant_id = {t:String}
        GROUP BY campaign_id
        """, {'t': tenant})[1]}

    touches = {r[0]: int(r[1]) for r in q(
        """
        SELECT campaign_id, countIf(status IN ('sent', 'queued', 'issued', 'dry_run'))
        FROM campaign_send_log WHERE tenant_id = {t:String} GROUP BY campaign_id
        """, {'t': tenant})[1]}

    empty = {'enrolled': 0, 'active': 0, 'holdout': 0, 'done': 0, 'exited': 0}
    campaigns = [{
        'campaign_id': c['campaign_id'],
        'title': c.get('title', c['campaign_id']),
        'entry_stage': c.get('entry_stage', ''),
        'goal': c.get('goal', {}),
        'steps': [{'delay_h': s.get('delay_h', 0), 'action': s.get('action', ''),
                   'channel': s.get('channel', 'email' if s.get('action') == 'email' else ''),
                   'subject': s.get('subject', ''), 'body': s.get('body', ''),
                   'offer_id': s.get('offer_id', ''),
                   'offer_title': offer_titles.get(s.get('offer_id', ''), ''),
                   'cta_label': s.get('cta_label', ''),
                   'cta_url': s.get('cta_url', ''),
                   'edited': bool(s.get('_edited')),
                   # template - каркас платформы, generated - собрано по опроснику,
                   # manual - владелец правил руками
                   'source': (s.get('_src') or 'manual') if s.get('_edited') else 'template',
                   } for s in c.get('steps', [])],
        'stats': {**enr.get(c['campaign_id'], empty),
                  'touches': touches.get(c['campaign_id'], 0)},
        'custom': bool(c.get('_custom')),
        'status': str(c.get('status') or 'active'),
        'audience_note': str(c.get('audience_note') or ''),
    } for c in conf.get('campaigns', [])]

    # A/B: статистика вариантов у шагов, где сплит объявлен
    for c_out, c_in in zip(campaigns, conf.get('campaigns', [])):
        for idx, (s_out, s_in) in enumerate(zip(c_out['steps'],
                                                c_in.get('steps', []))):
            variants = s_in.get('variants') or []
            if len(variants) >= 2 and not s_in.get('variants_off'):
                try:
                    s_out['ab'] = _ab_stats(tenant, c_out['campaign_id'],
                                            idx, variants)
                except Exception as exc:  # noqa: BLE001 - статистика не роняет экран
                    print(f'[campaigns] {tenant}: ab stats failed: {exc}', flush=True)

    import os as _os3
    platform_dry = _os3.environ.get('SIGNALS_DRY_RUN', '1') not in ('0', 'false', 'False', '')
    answers = (ca.load_tenants().get(tenant, {}) or {}).get('onboarding_answers') or {}
    return {'tenant': tenant, 'autopilot': _autopilot_resolved(conf, tenant),
            'platform_dry_run': platform_dry,
            # пока опросник не заполнен, на экране лежит НЕЙТРАЛЬНЫЙ каркас
            # платформы - экран обязан сказать это прямо, а не выдавать его
            # за тексты клиента
            'tailored': bool(answers),
            'product_name': str(answers.get('product_name') or ''),
            'app_url': str(answers.get('app_url') or ''),
            'control_pct': int(conf.get('control_pct', 10)), 'campaigns': campaigns}


@bp.get('/saas/campaigns')
@require_auth(roles=LEAK_ROLES)
def saas_campaigns():
    return api_json(_campaigns_payload(_tenant_arg()))


@bp.get('/saas/launch-check')
@require_auth(roles=LEAK_ROLES)
def saas_launch_check():
    """Предполётный чеклист: не опозоримся ли, когда письма начнут доходить.

    Автопроверки - кодом (подписи, плейсхолдеры, тире, привязки, домен),
    ручные (ящик для ответов, DMARC, «прочитал тестовое письмо сам») -
    подтверждает владелец, подтверждения хранятся в конфиге тенанта."""
    from stripe_sync.launch_check import (check_copy, check_identity,
                                          check_offers_bound, check_sender,
                                          manual_items, verdict)

    tenant = _tenant_arg()
    tch = ca.load_tenants().get(tenant, {}) or {}
    conf = _campaigns_conf(tenant)
    tailored = bool(tch.get('onboarding_answers'))

    checks = [check_sender(str(tch.get('email_from') or ''))]
    # Корпоративная подпись (методология §8a): полный комплект = имя + роль +
    # компания + фото. Фолбэк из отправителя работает, но это жёлтый статус -
    # письмо без лица и роли выглядит системным.
    ident = dict(tch.get('email_identity') or {})
    full = all(str(ident.get(k) or '').strip()
               for k in ('name', 'role', 'company', 'avatar_url'))
    if full:
        sig_detail = f"{ident['name']} · {ident['role']} · фото"
        checks.append({'key': 'signature', 'status': 'pass', 'detail': sig_detail})
    else:
        from stripe_sync.email_delivery import signature_block
        _sig = signature_block(str(tch.get('email_from') or ''),
                               str((tch.get('onboarding_answers') or {})
                                   .get('product_name') or ''))
        missing = [k for k in ('name', 'role', 'company', 'avatar_url')
                   if not str(ident.get(k) or '').strip()]
        checks.append({'key': 'signature', 'status': 'warn' if _sig else 'fail',
                       'detail': 'нет: ' + ', '.join(missing)})
    checks += check_identity(tch, tailored)
    checks += check_copy(conf)
    checks.append(check_offers_bound(conf))

    # предохранители - показываем значениями, чтобы владелец видел страховку
    import os as _os5
    platform_live = _os5.environ.get('SIGNALS_DRY_RUN', '1') in ('0', 'false', 'False', '')
    checks.append({'key': 'platform_live',
                   'status': 'pass' if platform_live else 'fail', 'detail': ''})
    try:
        supp = int(q('SELECT count() FROM email_suppressions_current '
                     'WHERE tenant_id = {t:String}', {'t': tenant})[1][0][0])
        checks.append({'key': 'suppressions', 'status': 'pass', 'detail': str(supp)})
    except Exception:  # noqa: BLE001
        pass
    try:
        due24 = int(q("""
            SELECT uniqExact(identity_id) FROM campaign_enrollments_current
            WHERE tenant_id = {t:String} AND status = 'active'
              AND next_step_at <= now() + INTERVAL 1 DAY
            """, {'t': tenant})[1][0][0])
        checks.append({'key': 'first_wave', 'status': 'pass', 'detail': str(due24)})
    except Exception:  # noqa: BLE001
        pass

    checks += manual_items(dict(tch.get('launch_confirms') or {}))
    return api_json({'tenant': tenant, 'checks': checks,
                     'verdict': verdict(checks),
                     'autopilot': _autopilot_resolved(conf, tenant)})


@bp.post('/saas/launch-check/confirm')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_launch_check_confirm():
    from stripe_sync.launch_check import MANUAL_KEYS

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    key = str(body.get('key') or '')
    if key not in MANUAL_KEYS:
        return _bad('unknown_check')
    tch = ca.load_tenants().get(tenant, {}) or {}
    confirms = dict(tch.get('launch_confirms') or {})
    confirms[key] = bool(body.get('ok', True))
    ca.update_tenant(tenant, {'launch_confirms': confirms})
    print(f'[launch] {tenant}: {key} -> {confirms[key]}', flush=True)
    return api_json({'key': key, 'ok': confirms[key]})


# ── Ручные кампании: сегмент по фильтрам + свои шаги, исполняет штатный тик ──


def _segment_rows(tenant: str, audience: dict, limit: int = 0):
    """(rows, unknown): кто попадает в сегмент прямо сейчас."""
    from stripe_sync.segment import audience_sql, build
    conds, sparams, unknown = build(audience or {})
    rows = q(audience_sql(conds, limit), {'t': tenant, **sparams})[1]
    return rows, unknown


@bp.post('/saas/segments/preview')
@require_auth(roles=LEAK_ROLES)
def saas_segment_preview():
    """Живое превью сегмента: сколько людей, скольким реально можно написать."""
    tenant = _tenant_arg()
    audience = (request.get_json(silent=True) or {}).get('audience') or {}
    try:
        rows, unknown = _segment_rows(tenant, audience)
    except Exception as exc:  # noqa: BLE001
        print(f'[segment] {tenant}: preview failed: {exc}', flush=True)
        return _bad('segment_failed')
    with_email = sum(1 for r in rows if r[2])
    with_cuid = sum(1 for r in rows if r[3])
    from stripe_sync.segment import describe

    # Достижимость по каналам: тот же сегмент + условие «есть контакт X».
    # email/inapp уже посчитаны по строкам; для мессенджеров/телефона - count.
    from stripe_sync import segment as _seg
    conds, sparams, _ = _seg.build(audience)
    reach = {'email': with_email, 'inapp': with_cuid}
    try:
        where = " AND ".join(["ua.tenant_id = {t:String}"] + conds)
        for tok in ('phone', 'whatsapp', 'telegram'):
            sql = (f"SELECT count() {_seg.AUDIENCE_FROM} "
                   f"WHERE {where} AND {_seg.contact_expr(tok, 'ua', False)}")
            reach[tok] = int(q(sql, {'t': tenant, **sparams})[1][0][0])
    except Exception as exc:  # noqa: BLE001 - счётчики не роняют превью
        print(f'[segment] {tenant}: reach failed: {exc}', flush=True)

    return api_json({
        'tenant': tenant, 'count': len(rows),
        'reachable_email': with_email, 'reachable_inapp': with_cuid,
        'reach': reach,
        'description': describe(audience), 'ignored_filters': unknown,
        'sample': [{'identity_id': r[0], 'stage': r[1], 'email': r[2]}
                   for r in rows[:8]],
    })


@bp.post('/saas/campaigns/custom')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_campaign_custom_create():
    """Создать ручную кампанию на отфильтрованный сегмент и зачислить его
    СНАПШОТОМ. Дальше работает штатный тик: dry-run до автопилота, подавления,
    тихие часы, лог касаний - все предохранители общие с автокампаниями."""
    import re as _re
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from stripe_sync import overrides as ovr
    from stripe_sync.campaign_tick import holdout_split, next_step_time
    from stripe_sync.segment import describe

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}

    from stripe_sync.segment import validate_steps
    title = str(body.get('title') or '').strip()[:80]
    if len(title) < 3:
        return _bad('title_required')
    steps, reason = validate_steps(body.get('steps') or [])
    if reason:
        return _bad(reason)
    audience = body.get('audience') or {}
    try:
        control_pct = max(0, min(50, int(body.get('control_pct', 10))))
    except (TypeError, ValueError):
        control_pct = 10

    try:
        rows, unknown = _segment_rows(tenant, audience)
    except Exception as exc:  # noqa: BLE001
        print(f'[segment] {tenant}: audience failed: {exc}', flush=True)
        return _bad('segment_failed')
    if not rows:
        return _bad('segment_empty')

    slug = _re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:24] or 'campaign'
    now = _dt.now(tz=_tz.utc)
    cid = f"M_{slug}_{now.strftime('%m%d%H%M')}"

    # предупреждения методологии копирайта (§8) - не блокируют, но видны
    warnings = []
    try:
        from stripe_sync.copy_review import review_step
        profile = (ca.load_tenants().get(tenant, {}) or {}).get('onboarding_answers') or {}
        for i, st in enumerate(steps):
            flags = review_step(st.get('subject', ''), st.get('body', ''),
                                cid, st['action'], profile) or []
            warnings += [f"step_{i}:{f.get('code', f)}" if isinstance(f, dict)
                         else f'step_{i}:{f}' for f in flags]
    except Exception:  # noqa: BLE001
        pass

    ovr.add_custom_campaign(tenant, {
        'campaign_id': cid, 'title': title, 'status': 'active',
        'goal_event': str(body.get('goal_event') or ''),
        'audience': audience, 'audience_note': describe(audience),
        'created_at': now.strftime('%Y-%m-%d %H:%M:%S'),
        'steps': steps,
    })

    ch = _ch_direct()
    cols = ['tenant_id', 'campaign_id', 'identity_id', 'control', 'entry_stage',
            'step_idx', 'next_step_at', 'status', 'enrolled_at', 'updated_at']
    first_at = next_step_time(steps, now, 0)
    enroll_rows, control_n = [], 0
    for r in rows:
        control = holdout_split(tenant, cid, r[0], control_pct)
        control_n += 1 if control else 0
        enroll_rows.append([tenant, cid, r[0], 1 if control else 0,
                            str(r[1] or 'MANUAL'), 0, first_at, 'active', now, now])
    ch.insert('retention.campaign_enrollments', enroll_rows, column_names=cols)

    print(f'[custom_camp] {tenant}: {cid} "{title}" enrolled={len(enroll_rows)} '
          f'control={control_n} audience={describe(audience)}', flush=True)
    return api_json({'campaign_id': cid, 'enrolled': len(enroll_rows),
                     'control': control_n, 'ignored_filters': unknown,
                     'copy_warnings': warnings,
                     'autopilot': _autopilot_resolved(_campaigns_conf(tenant), tenant)})


@bp.post('/saas/campaigns/custom/status')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_campaign_custom_status():
    """Пауза/архив ручной кампании. Архив дополнительно закрывает активные
    зачисления - иначе тик продолжил бы слать шаги."""
    from stripe_sync import overrides as ovr

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    cid = str(body.get('campaign_id') or '')
    status = str(body.get('status') or '')
    if not cid.startswith('M_') or status not in ('active', 'paused', 'archived'):
        return _bad('invalid_request')
    if not ovr.set_custom_campaign_status(tenant, cid, status):
        return _bad('unknown_campaign', 404)
    if status == 'archived':
        ch = _ch_direct()
        ch.command(
            "ALTER TABLE retention.campaign_enrollments UPDATE status = 'exited', "
            "updated_at = now() WHERE tenant_id = %(t)s AND campaign_id = %(c)s "
            "AND status = 'active' SETTINGS mutations_sync = 1",
            parameters={'t': tenant, 'c': cid})
    print(f'[custom_camp] {tenant}: {cid} -> {status}', flush=True)
    return api_json({'campaign_id': cid, 'status': status})


@bp.post('/saas/campaigns/step')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_campaign_step_edit():
    """Правка текста/тайминга шага кампании из CRM. reset=true - вернуть базу.
    Структуру (добавить/удалить шаг, сменить канал) правит платформа."""
    from stripe_sync import overrides as ovr

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    cid = str(body.get('campaign_id', ''))
    try:
        idx = int(body.get('step_idx'))
    except (TypeError, ValueError):
        return _bad('invalid_step')

    base = _campaigns_conf(tenant)
    camp = next((c for c in base.get('campaigns', []) if c['campaign_id'] == cid), None)
    if camp is None or not (0 <= idx < len(camp.get('steps', []))):
        return _bad('unknown_step')

    if body.get('reset'):
        ovr.set_campaign_step(tenant, cid, idx, None)
        print(f'[edit] {tenant}: {cid} step {idx} сброшен к базе', flush=True)
        return api_json(_campaigns_payload(tenant))

    patch = {}
    subject = body.get('subject')
    if subject is not None:
        patch['subject'] = str(subject).strip()[:200]
    text = body.get('body')
    if text is not None:
        text = str(text).strip()
        if not text or len(text) > 2000:
            return _bad('invalid_body')
        patch['body'] = text
    for f in ('cta_label', 'cta_url'):
        if body.get(f) is not None:
            patch[f] = str(body[f]).strip()[:300]
    if body.get('delay_h') is not None:
        try:
            dh = float(body['delay_h'])
        except (TypeError, ValueError):
            return _bad('invalid_delay')
        if not 0 <= dh <= 720:
            return _bad('invalid_delay')
        patch['delay_h'] = dh
    if not patch:
        return _bad('nothing_to_update')

    ovr.set_campaign_step(tenant, cid, idx, patch)
    print(f'[edit] {tenant}: {cid} step {idx} обновлён {sorted(patch)}', flush=True)

    # Методология текстов §8 и для рукописных шагов: владельца не блокируем
    # (его текст - его право), но флаги показываем сразу при сохранении.
    copy_flags = []
    if 'subject' in patch or 'body' in patch:
        try:
            from stripe_sync.business_context import business_context
            from stripe_sync.copy_review import review_step
            payload_now = _campaigns_payload(tenant)
            step_now = next(
                (st for c in payload_now.get('campaigns', [])
                 if c.get('campaign_id') == cid
                 for j, st in enumerate(c.get('steps', [])) if j == idx), {})
            profile = business_context(None, tenant).get('claimed') or {}
            role = 'inapp' if step_now.get('action') == 'inapp' else 'email'
            copy_flags = review_step(step_now.get('subject', ''),
                                     step_now.get('body', ''), cid, role, profile)
        except Exception as exc:  # noqa: BLE001 - ревью не роняет сохранение
            print(f'[edit] {tenant}: copy_review пропущен: {exc}', flush=True)
    out = _campaigns_payload(tenant)
    out['copy_flags'] = copy_flags
    return api_json(out)


@bp.post('/saas/offers/update')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_offer_edit():
    """Правка щедрости/лимитов оффера. params - только существующие числовые
    ключи оффера (контракт исполнителя не расширяем). reset=true - база."""
    import json as _json
    import os as _os2
    from stripe_sync import overrides as ovr

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    oid = str(body.get('offer_id', ''))

    path = _os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))),
                          'stripe_sync', 'offers_catalog.json')
    base = _json.load(open(path)).get(tenant, {})
    offer = next((o for o in base.get('offers', []) if o['offer_id'] == oid), None)
    if offer is None:
        return _bad('unknown_offer')

    if body.get('reset'):
        ovr.set_offer(tenant, oid, None)
        return api_json({'ok': True})

    patch = {}
    if body.get('title') is not None:
        title = str(body['title']).strip()[:120]
        if title:
            patch['title'] = title
    if body.get('max_per_user_30d') is not None:
        try:
            cap = int(body['max_per_user_30d'])
        except (TypeError, ValueError):
            return _bad('invalid_cap')
        if not 0 <= cap <= 100:
            return _bad('invalid_cap')
        patch['max_per_user_30d'] = cap
    p_in = body.get('params') or {}
    p_out = {}
    for k, v in p_in.items():
        if k not in (offer.get('params') or {}):
            return _bad(f'unknown_param:{k}')
        cur = offer['params'][k]
        if isinstance(cur, bool) or not isinstance(cur, (int, float)):
            return _bad(f'param_not_editable:{k}')
        try:
            num = float(v)
        except (TypeError, ValueError):
            return _bad(f'invalid_param:{k}')
        if not 0 <= num <= 1_000_000:
            return _bad(f'invalid_param:{k}')
        p_out[k] = int(num) if float(num).is_integer() else num
    if p_out:
        patch['params'] = p_out
    if not patch:
        return _bad('nothing_to_update')

    ovr.set_offer(tenant, oid, patch)
    print(f'[edit] {tenant}: оффер {oid} обновлён {sorted(patch)}', flush=True)
    return api_json({'ok': True})


@bp.post('/saas/users/source')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_users_source():
    """Подключить ПОСТОЯННЫЙ источник базы юзеров (без кода на стороне клиента).

    Поддержаны: Supabase, Clerk и любой собственный админский API продукта
    (URL + токен). Проверяем живым запросом и сразу говорим, сколько людей
    видим - клиент не остаётся гадать, сработало или нет.
    """
    from stripe_sync.connectors import probe

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    kind = str(body.get('kind') or '').strip()

    if not kind:                       # отключение источника
        ca.update_tenant(tenant, {'users_source': None})
        return api_json({'tenant': tenant, 'connected': False})

    cfg = {'kind': kind,
           'url': str(body.get('url') or '').strip(),
           'key': str(body.get('key') or '').strip(),
           'list_path': str(body.get('list_path') or '').strip(),
           'id_field': str(body.get('id_field') or 'id').strip(),
           'email_field': str(body.get('email_field') or 'email').strip(),
           'created_field': str(body.get('created_field') or 'created_at').strip()}
    if kind in ('supabase', 'json', 'export') and not cfg['url']:
        return _bad('url_required')
    if not cfg['key'] and kind != 'json':
        return _bad('key_required')

    ok, reason, seen = probe(cfg)
    if not ok:
        return _bad(f'source_{reason}', 400)

    ca.update_tenant(tenant, {'users_source': cfg})
    # первая синхронизация сразу, не дожидаясь часового расписания
    people = 0
    try:
        from stripe_sync.connectors import fetch_users
        from stripe_sync.users_import import COLUMNS as UCOLS, to_events
        rows, _report = to_events(fetch_users(cfg), tenant)
        if rows:
            ch = _ch_direct()
            ch.insert('retention.saas_events', rows, column_names=UCOLS)
            people = _restitch(ch, tenant)
    except Exception as exc:  # noqa: BLE001
        print(f'[users_source] {tenant}: первая синхронизация позже: {exc}', flush=True)
    print(f'[users_source] {tenant}: подключён {kind}, видно юзеров: {seen}', flush=True)
    return api_json({'tenant': tenant, 'connected': True, 'kind': kind,
                     'users_seen': seen, 'people': people})


@bp.post('/saas/users/import')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_users_import():
    """Разовая загрузка базы юзеров клиента (CSV/JSON из его админки).

    Сниппет видит только то, что происходит после установки. Всё, что было до,
    лежит в базе клиента - и без этой загрузки экран юзеров показывает горстку
    людей вместо реальной базы. Каждая строка становится обычным событием
    регистрации, дальше работает штатный конвейер.
    """
    from stripe_sync.users_import import COLUMNS, parse_rows, preview, to_events

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    raw = str(body.get('data', ''))
    if len(raw) > 8_000_000:
        return _bad('file_too_large')
    rows = parse_rows(raw)
    if not rows:
        return _bad('nothing_to_import')
    if body.get('preview'):
        # СНАЧАЛА ПОКАЗАТЬ, ПОТОМ ГРУЗИТЬ: человек видит, какие колонки мы
        # распознали и сколько строк уйдёт в брак, и решает сам.
        return api_json({'tenant': tenant, **preview(rows)})
    events, report = to_events(rows, tenant)
    if not events:
        return _bad('no_id_or_email_columns')

    ch = _ch_direct()
    ch.insert('retention.saas_events', events, column_names=COLUMNS)
    # СРАЗУ СОБИРАЕМ ЛИЧНОСТИ. Иначе человек загрузил базу, открыл экран юзеров
    # и увидел пустоту: сборка идёт по расписанию раз в час, и выглядит это как
    # «ничего не приняли».
    stitched = _restitch(ch, tenant)
    print(f'[import] {tenant}: {report}, личностей собрано: {stitched}', flush=True)
    return api_json({'tenant': tenant, **report, 'people': stitched})


def _restitch(ch, tenant: str) -> int:
    """Пересборка личностей пространства здесь и сейчас (после загрузки базы)."""
    try:
        from stripe_sync.stitch import run_stitch
        now = _dt.datetime.now(tz=_dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        return int(run_stitch(ch, tenant, now).get('identities', 0))
    except Exception as exc:  # noqa: BLE001 - данные уже приняты, сборка догонит по расписанию
        print(f'[import] {tenant}: сборка личностей не удалась: {exc}', flush=True)
        return 0


def _ch_direct():
    """Отдельный клиент CH для записи (q() умеет только читать)."""
    import os as _os5

    import clickhouse_connect
    return clickhouse_connect.get_client(
        host=_os5.environ.get('CH_HOST', 'clickhouse'),
        port=int(_os5.environ.get('CH_PORT', '8123')),
        username=_os5.environ.get('CH_USER', 'default'),
        password=_os5.environ.get('CH_PASSWORD', ''),
        database=_os5.environ.get('CH_DB', 'retention'))


@bp.get('/saas/offers/suggestions')
@require_auth(roles=LEAK_ROLES)
def saas_offer_suggestions():
    """Что система предлагает добавить или починить - по ЖИВЫМ данным клиента.

    Ничего не применяется автоматически: это список с фактами и кнопкой.
    """
    import json as _json
    import os as _os4
    from stripe_sync import overrides as ovr
    from stripe_sync.compose import compose_offers
    from stripe_sync.offer_suggest import suggest

    tenant = _tenant_arg()

    path = _os4.path.join(_os4.path.dirname(_os4.path.dirname(_os4.path.abspath(__file__))),
                          'stripe_sync', 'offers_catalog.json')
    base = _json.load(open(path))
    catalog = ovr.merge_catalog({**(base.get('_default') or {}),
                                 **(base.get(tenant) or {})},
                                ovr.load_tenant(tenant)).get('offers', [])
    catalog = [{**o, 'disabled': bool(o.get('_disabled'))} for o in catalog]

    stages, stage_value = {}, {}
    for r in q("SELECT stage, count(), sum(value_at_stake) FROM user_actions "
               "WHERE tenant_id = {t:String} GROUP BY stage", {'t': tenant})[1]:
        stages[r[0]] = int(r[1])
        stage_value[r[0]] = _flt(r[2])

    rejects = {(r[0], r[1]): int(r[2]) for r in q(
        "SELECT offer_id, reason, count() FROM offers_issued "
        "WHERE tenant_id = {t:String} AND status = 'rejected' "
        "AND issued_at >= now() - INTERVAL 30 DAY GROUP BY offer_id, reason",
        {'t': tenant})[1]}

    tc = ca.load_tenants().get(tenant, {}) or {}
    answers = tc.get('onboarding_answers') or {}
    avg_price = _flt(q(
        "SELECT coalesce(avg(nullIf(toFloat64(mrr), 0)), 0) FROM tenant_plans_current "
        "WHERE tenant_id = {t:String}", {'t': tenant})[1][0][0])
    from stripe_sync.economics import with_measured
    composed = compose_offers(with_measured(answers, _measured_costs(tenant)),
                              avg_price) if answers else []

    return api_json({
        'tenant': tenant,
        'suggestions': suggest(catalog, stages, stage_value, rejects,
                               answers, avg_price, composed),
    })


@bp.post('/saas/offers/create')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_offer_create():
    """Создание оффера с нуля из CRM. Валидация - compose.validate_offer
    (единые схемы исполнителей с AI-компоновщиком); id генерится из названия."""
    import re as _re
    from stripe_sync import overrides as ovr
    from stripe_sync.compose import validate_offer

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    clean, reason = validate_offer(body)
    if reason:
        return _bad(reason)

    slug = _re.sub(r'[^a-z0-9]+', '_', clean['title'].lower()).strip('_')[:24] or 'offer'
    existing = {o['offer_id'] for o in _tenant_offers(tenant)}
    oid = f'C_{slug}'
    n = 2
    while oid in existing:
        oid = f'C_{slug}_{n}'
        n += 1
    clean['offer_id'] = oid

    ovr.add_custom_offer(tenant, clean)
    print(f'[edit] {tenant}: создан оффер {oid} ({clean["executor"]})', flush=True)
    return api_json({'offer_id': oid})


@bp.post('/saas/offers/disable')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_offer_disable():
    """Отключить/включить оффер (отключённый не выдаётся; custom при
    отключении удаляется совсем)."""
    from stripe_sync import overrides as ovr

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    oid = str(body.get('offer_id', ''))
    if oid not in {o['offer_id'] for o in _tenant_offers(tenant)}:
        return _bad('unknown_offer')
    ovr.set_offer_disabled(tenant, oid, bool(body.get('disabled', True)))
    print(f'[edit] {tenant}: оффер {oid} disabled={bool(body.get("disabled", True))}',
          flush=True)
    return api_json({'ok': True})


@bp.post('/saas/campaigns/autopilot')
@require_auth(roles=('super_admin', 'director'))
def saas_campaigns_autopilot():
    """Рубильник автопилота: false = все касания принудительно dry-run.
    Пишется в tenants.json (рантайм) - контент кампаний остаётся в git."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get('enabled'))
    if enabled:
        # ВКЛЮЧАТЬ НЕЧЕГО, ЕСЛИ НЕЧЕМ И НЕКОМУ. Автопилот без канала выдаёт
        # только отказы «нет контакта», без офферов - «оффер не привязан», а
        # владелец видит зелёный рубильник и думает, что работает.
        blockers = _autopilot_blockers(tenant)
        if blockers:
            return api_json({'blockers': blockers}, 409, 'autopilot_not_ready')
    ca.update_tenant(tenant, {'autopilot': enabled})
    print(f'[campaigns] {tenant}: autopilot -> {enabled}', flush=True)
    return api_json(_campaigns_payload(tenant))


def _bad(reason: str, code: int = 400):
    return api_json(None, code, reason)


@bp.post('/saas/channels/email/domain')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_email_domain():
    """Клиент вводит свой поддомен отправки (mail.клиент.com). С ключом Resend
    сразу создаём домен и возвращаем DNS-записи; без ключа фиксируем запрос
    (awaiting_provider) - создание догонит /verify, когда ключ появится."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    domain = str((request.get_json(silent=True) or {}).get('domain', '')).strip().lower()
    if not ca.DOMAIN_RE.match(domain):
        return _bad('invalid_domain')

    key = _tenant_resend_key(tenant)
    if not key:
        ca.update_tenant(tenant, {'email_domain': domain,
                                  'email_domain_status': 'awaiting_provider',
                                  'email_domain_id': None, 'email_dns_records': None})
        print(f'[channels] {tenant}: email domain {domain} запрошен (ключа Resend ещё нет)',
              flush=True)
        return api_json(_channels_payload(tenant))

    ok, status, data = ca.resend_create_domain(domain, key)
    if not ok:
        # Домен может быть уже заведён в аккаунте клиента (частый случай:
        # он оттуда уже шлёт письма). Тогда берём его как есть, а не требуем
        # заводить лишний поддомен ради новых DNS-записей.
        existing = ca.resend_find_domain(domain, key)
        if not existing:
            return _bad(f'resend_{status}', 502)
        data = existing
    # Статус берём У RESEND, а не ставим «ждём DNS» вслепую: домен клиента
    # часто УЖЕ подтверждён в его аккаунте, и требовать от него заново ставить
    # записи - выдумывать работу на ровном месте.
    ca.update_tenant(tenant, {'email_domain': domain,
                              'email_domain_id': str(data.get('id', '')),
                              'email_domain_status': str(data.get('status') or 'pending_dns'),
                              'email_dns_records': ca.dns_rows(data)})
    print(f'[channels] {tenant}: email domain {domain} создан в Resend', flush=True)
    return api_json(_channels_payload(tenant))


@bp.post('/saas/channels/email/verify')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_email_verify():
    """Кнопка «Проверить DNS»: дергаем верификацию и перечитываем статус."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    tch = ca.load_tenants().get(tenant, {}) or {}
    domain = str(tch.get('email_domain', ''))
    if not domain:
        return _bad('no_domain')
    key = _tenant_resend_key(tenant)
    if not key:
        return _bad('resend_not_configured', 409)

    dom_id = str(tch.get('email_domain_id', ''))
    if not dom_id:   # домен был запрошен до появления ключа - создаём сейчас
        ok, status, data = ca.resend_create_domain(domain, key)
        if not ok:
            return _bad(f'resend_{status}', 502)
        dom_id = str(data.get('id', ''))
        ca.update_tenant(tenant, {'email_domain_id': dom_id,
                                  'email_domain_status': 'pending_dns',
                                  'email_dns_records': ca.dns_rows(data)})

    ca.resend_verify_domain(dom_id, key)
    # open/click tracking включаем сразу (2026-08-26): без него Resend не шлёт
    # opened/clicked, и вся аналитика открытий тихо мертва
    try:
        ca.resend_enable_tracking(dom_id, key)
    except Exception:  # noqa: BLE001 - трекинг не критичен для верификации
        pass
    ok, status, data = ca.resend_get_domain(dom_id, key)
    if not ok:
        return _bad(f'resend_{status}', 502)
    st = str(data.get('status', 'pending'))
    ca.update_tenant(tenant, {
        'email_domain_status': 'verified' if st == 'verified' else 'pending_dns',
        'email_dns_records': ca.dns_rows(data)})
    print(f'[channels] {tenant}: verify {domain} -> {st}', flush=True)
    return api_json(_channels_payload(tenant))


@bp.post('/saas/channels/email/sender')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_email_sender():
    """Имя и адрес «От кого» - строго на подключённом домене тенанта."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    name = str(body.get('from_name', '')).strip().replace('<', '').replace('>', '')[:60]
    addr = str(body.get('from_email', '')).strip().lower()
    tch = ca.load_tenants().get(tenant, {}) or {}
    domain = str(tch.get('email_domain', ''))
    if not domain:
        return _bad('no_domain')
    if not ca.EMAIL_RE.match(addr) or not addr.endswith('@' + domain):
        return _bad('email_not_on_domain')
    email_from = f'{name} <{addr}>' if name else addr
    ca.update_tenant(tenant, {'email_from': email_from})
    return api_json(_channels_payload(tenant))


@bp.post('/saas/channels/email/key')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_email_key():
    """Свой аккаунт Resend: клиент вставляет ключ re_..., проверяем его живым
    запросом и сохраняем. Пустая строка - вернуться на платформенный аккаунт."""
    import urllib.error as _ue
    import urllib.request as _ur

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    key = str((request.get_json(silent=True) or {}).get('api_key', '')).strip()

    if not key:
        ca.update_tenant(tenant, {'resend_api_key': None})
        return api_json(_channels_payload(tenant))
    if not key.startswith('re_') or len(key) < 20:
        return _bad('invalid_resend_key')

    # живая проверка: ключ должен уметь читать домены аккаунта
    req = _ur.Request('https://api.resend.com/domains',
                      headers={'Authorization': f'Bearer {key}',
                               'User-Agent': _UA})
    try:
        with _ur.urlopen(req, timeout=20) as resp:
            if not (200 <= resp.status < 300):
                return _bad(f'resend_http_{resp.status}', 502)
    except _ue.HTTPError as exc:
        # 401 - ключ действительно не тот; 403 обычно значит, что провайдер
        # отбил НАШ запрос (заслон Cloudflare) - винить ключ клиента нельзя
        return _bad('invalid_resend_key' if exc.code == 401 else f'resend_http_{exc.code}',
                    400 if exc.code == 401 else 502)
    except Exception as exc:  # noqa: BLE001
        return _bad(f'resend_{type(exc).__name__}', 502)

    ca.update_tenant(tenant, {'resend_api_key': key})
    print(f'[channels] {tenant}: подключён собственный аккаунт Resend', flush=True)
    return api_json(_channels_payload(tenant))


@bp.post('/saas/channels/email/webhook-secret')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_email_webhook_secret():
    """Секрет подписи вебхука Resend своего аккаунта (whsec_...). Без него
    события доставки отклоняются - иначе кто угодно смог бы подделать баунс и
    занести чужой адрес в подавление."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    sec = str((request.get_json(silent=True) or {}).get('secret', '')).strip()
    if sec and not (sec.startswith('whsec_') and len(sec) >= 20):
        return _bad('invalid_webhook_secret')
    ca.update_tenant(tenant, {'resend_webhook_secret': sec or None})
    return api_json(_channels_payload(tenant))


@bp.post('/saas/onboarding/stripe')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def onboarding_stripe():
    """Ключи Stripe КЛИЕНТА: подписной секрет вебхука (whsec_, обязателен для
    приёма событий) и restricted-ключ (rk_/sk_, нужен только для купонов и
    цен планов). Пустая строка стирает ключ. Ключ проверяем живым запросом."""
    import urllib.error as _ue
    import urllib.request as _ur

    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    patch = {}

    if 'webhook_secret' in body:
        sec = str(body.get('webhook_secret') or '').strip()
        if sec and not (sec.startswith('whsec_') and len(sec) >= 20):
            return _bad('invalid_webhook_secret')
        patch['stripe_webhook_secret'] = sec or None

    if 'api_key' in body:
        key = str(body.get('api_key') or '').strip()
        if key:
            if not (key.startswith('rk_') or key.startswith('sk_')) or len(key) < 20:
                return _bad('invalid_stripe_key')
            req = _ur.Request('https://api.stripe.com/v1/customers?limit=1',
                              headers={'Authorization': f'Bearer {key}',
                                       'User-Agent': _UA})
            try:
                with _ur.urlopen(req, timeout=20) as resp:
                    if not (200 <= resp.status < 300):
                        return _bad(f'stripe_http_{resp.status}', 502)
            except _ue.HTTPError as exc:
                return _bad('invalid_stripe_key' if exc.code == 401
                            else f'stripe_http_{exc.code}',
                            400 if exc.code == 401 else 502)
            except Exception as exc:  # noqa: BLE001
                return _bad(f'stripe_{type(exc).__name__}', 502)
        patch['stripe_api_key'] = key or None

    if not patch:
        return _bad('nothing_to_save')
    ca.update_tenant(tenant, patch)
    print(f'[onboarding] {tenant}: ключи Stripe обновлены ({", ".join(patch)})', flush=True)
    return saas_onboarding()


@bp.post('/saas/channels/messaging')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_messaging():
    """Заявка на альфа-имя SMS/Viber. Регистрацию у DecisionTelecom ведёт
    платформа (менеджер DT), активация = перенос requested_* -> *_sender."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    patch = {}
    for kind in ('sms', 'viber'):
        val = str(body.get(f'{kind}_sender', '')).strip()
        if not val:
            continue
        if not ca.ALPHA_RE.match(val):
            return _bad(f'invalid_{kind}_sender')
        patch[f'requested_{kind}_sender'] = val
    if not patch:
        return _bad('nothing_to_update')
    ca.update_tenant(tenant, patch)
    print(f'[channels] {tenant}: заявка на альфа-имена {patch}', flush=True)
    return api_json(_channels_payload(tenant))


@bp.post('/saas/channels/telegram')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_telegram():
    """Подключение бота клиента: валидация токена (getMe) + вебхук на наш
    ingest с секретом. Пустой bot_token = отключить."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    token = str((request.get_json(silent=True) or {}).get('bot_token', '')).strip()

    if not token:
        old = (ca.load_tenants().get(tenant, {}) or {}).get('telegram_bot_token', '')
        if old:
            ca.telegram_delete_webhook(str(old))
        ca.update_tenant(tenant, {'telegram_bot_token': None,
                                  'telegram_bot_username': None,
                                  'telegram_webhook_secret': None})
        return api_json(_channels_payload(tenant))

    if not ca.BOT_TOKEN_RE.match(token):
        return _bad('telegram_invalid_token')
    ok, username = ca.telegram_get_me(token)
    if not ok:
        return _bad(username)

    host = _os.environ.get('SAAS_HOST', '').strip()
    if not host:
        return _bad('saas_host_not_set', 500)
    secret = _secrets.token_hex(24)
    ok, reason = ca.telegram_set_webhook(
        token, f'https://{host}/ingest/saas/tg/{tenant}', secret)
    if not ok:
        return _bad(f'webhook_failed:{reason}', 502)

    ca.update_tenant(tenant, {'telegram_bot_token': token,
                              'telegram_bot_username': username,
                              'telegram_webhook_secret': secret})
    print(f'[channels] {tenant}: telegram @{username} подключён, вебхук установлен',
          flush=True)
    return api_json(_channels_payload(tenant))


# ── WhatsApp Cloud API: подключение и шаблоны ────────────────────────────────
# Модель как с Resend: WABA и номер КЛИЕНТА, шлём его токеном. В треке A
# конфиг заводим мы (обслуживание руками), позже здесь появится Embedded
# Signup - кнопка «Connect WhatsApp».

@bp.post('/saas/channels/whatsapp')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_whatsapp():
    """Сохранить конфиг Cloud API тенанта. Пустой token = отключить.

    Токен проверяется живым запросом к номеру: сохранить нерабочий конфиг -
    значит узнать об этом в момент несписания у клиента."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    token = str(body.get('wa_token') or '').strip()
    if not token:
        ca.update_tenant(tenant, {'wa_token': None, 'wa_phone_number_id': None,
                                  'wa_phone_display': None, 'wa_waba_id': None,
                                  'wa_app_secret': None, 'wa_templates': None})
        return api_json({'ok': True, 'connected': False})

    phone_id = str(body.get('wa_phone_number_id') or '').strip()
    if not phone_id:
        return _bad('wa_phone_number_id_required')
    from stripe_sync.whatsapp_cloud import probe_number
    ok, detail = probe_number(token, phone_id)
    if not ok:
        return _bad(f'wa_probe_failed:{detail}')

    ca.update_tenant(tenant, {
        'wa_token': token, 'wa_phone_number_id': phone_id,
        'wa_phone_display': str(body.get('wa_phone_display') or detail or ''),
        'wa_waba_id': str(body.get('wa_waba_id') or '').strip() or None,
        'wa_app_secret': str(body.get('wa_app_secret') or '').strip() or None,
    })
    from stripe_sync.email_delivery import UNSUB_SECRET as _us
    import hashlib as _hl
    import hmac as _hm
    verify_token = _hm.new(_us.encode(), f'wawh|{tenant}'.encode(),
                           _hl.sha256).hexdigest()[:32]
    print(f'[channels] {tenant}: whatsapp подключён, номер {detail}', flush=True)
    return api_json({'ok': True, 'connected': True, 'phone': detail,
                     # для настройки вебхука в приложении Meta
                     'webhook_url': f"https://{_os.environ.get('SAAS_HOST', 'retivo.digital')}"
                                    f"/public/wa/webhook/{tenant}",
                     'webhook_verify_token': verify_token})


@bp.post('/saas/channels/whatsapp/templates')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_whatsapp_templates():
    """Собрать шаблоны из текстов кампаний и отправить на одобрение Meta.

    Идемпотентно: уже поданные (есть в реестре) не пересоздаются. Статусы
    одобрения приходят вебхуком; здесь всё уходит как PENDING."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    tc = ca.load_tenants().get(tenant, {}) or {}
    token = str(tc.get('wa_token') or '')
    waba = str(tc.get('wa_waba_id') or '')
    if not token or not waba:
        return _bad('whatsapp_not_connected')

    from stripe_sync.wa_templates import build_from_step
    from stripe_sync.whatsapp_cloud import create_template
    conf = _campaigns_conf(tenant)
    registry = dict(tc.get('wa_templates') or {})
    submitted, skipped = [], []
    for camp in conf.get('campaigns', []):
        for i, step in enumerate(camp.get('steps', [])):
            # whatsapp-шаблоны имеют смысл для текстовых шагов
            if step.get('action') not in ('email', 'message'):
                continue
            payload, reason = build_from_step(tenant, camp['campaign_id'], i, step)
            if payload is None:
                skipped.append({'campaign': camp['campaign_id'], 'step': i,
                                'reason': reason})
                continue
            if payload['name'] in registry:
                continue                     # уже подан - статус ведёт вебхук
            ok, detail = create_template(token, waba, payload['name'],
                                         payload['category'], payload['body'])
            if ok:
                registry[payload['name']] = {
                    'status': 'PENDING', 'campaign_id': camp['campaign_id'],
                    'step_idx': i, 'version': 1,
                    'params': payload['param_names'],
                    'category': payload['category']}
                submitted.append(payload['name'])
            else:
                skipped.append({'campaign': camp['campaign_id'], 'step': i,
                                'reason': detail})
    ca.update_tenant(tenant, {'wa_templates': registry})
    return api_json({'submitted': submitted, 'skipped': skipped,
                     'registry': registry})


# ── WhatsApp: ЛИЧНЫЙ номер через QR (трек C, только приём) ───────────────────
# Подключается как WhatsApp Web: отсканировал QR - работает. Неофициальный
# протокол: включение только с явным подтверждением риска бана; автокасания
# сюда не ходят технически (route_message умеет только Cloud API).

@bp.post('/saas/channels/whatsapp/personal')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def wa_personal_start():
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    if not body.get('accept_risk'):
        # без явного «понимаю, что номер могут забанить» не включаем
        return _bad('risk_not_accepted')
    from datetime import datetime, timezone

    from stripe_sync import wa_personal as wap
    ok, status = wap.start_session(tenant)
    if not ok:
        return _bad(f'waha_unavailable:{status}', 502)
    ca.update_tenant(tenant, {
        'wa_personal_status': status,
        'wa_personal_risk_accepted': datetime.now(tz=timezone.utc).isoformat()})
    print(f'[wa-personal] {tenant}: сессия запущена ({status})', flush=True)
    return api_json({'status': status})


@bp.get('/saas/channels/whatsapp/personal/qr')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def wa_personal_qr():
    """QR + живой статус. Фронт поллит, пока не WORKING."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    from stripe_sync import wa_personal as wap
    ok, status, number = wap.get_status(tenant)
    if not ok:
        return _bad(f'waha_unavailable:{status}', 502)
    # НИКАКОГО авто-оживления здесь. В момент привязки движок на секунды
    # перезапускает сокет, статус мелькает FAILED - оживление из поллинга
    # убивало почти завершённую привязку (Intentional Logout ровно в момент
    # скана). Упавшую сессию поднимает ТОЛЬКО явное нажатие кнопки: там
    # человек точно не сканирует прямо сейчас.
    qr = wap.get_qr_png(tenant) if status == 'SCAN_QR_CODE' else ''
    if status and status != 'NOT_STARTED':
        ca.update_tenant(tenant, {'wa_personal_status': status,
                                  'wa_personal_number': number or None})
    return api_json({'status': status, 'number': number, 'qr_png': qr})


@bp.post('/saas/channels/whatsapp/personal/automation')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def wa_personal_automation():
    """Тумблер автокасаний с личного номера. Отдельное согласие поверх
    QR-подключения: автоматика с личного номера - повышенный риск бана,
    и включает её владелец сам, с дневным лимитом (деф. 20/день)."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get('enabled'))
    patch = {'wa_personal_automation': enabled}
    try:
        cap = int(body.get('daily_cap') or 0)
        if 1 <= cap <= 100:
            patch['wa_personal_daily_cap'] = cap
    except (TypeError, ValueError):
        pass
    tch = ca.load_tenants().get(tenant, {}) or {}
    if enabled and str(tch.get('wa_personal_status') or '') != 'WORKING':
        return _bad('wa_session_not_working')
    ca.update_tenant(tenant, patch)
    print(f'[wa-personal] {tenant}: automation={"on" if enabled else "off"}', flush=True)
    return api_json({'enabled': enabled,
                     'daily_cap': patch.get('wa_personal_daily_cap',
                                            int(tch.get('wa_personal_daily_cap') or 20))})


@bp.post('/saas/channels/whatsapp/personal/disconnect')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def wa_personal_disconnect():
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    from stripe_sync import wa_personal as wap
    wap.drop_session(tenant)
    ca.update_tenant(tenant, {'wa_personal_status': None,
                              'wa_personal_number': None})
    return api_json({'ok': True})


# ── Инбокс личного WhatsApp: переписка + ручные ответы ───────────────────────
# Читает retention.wa_messages (пишет вебхук WAHA, оба направления). Ответ -
# единственный путь отправки в личный канал, и он требует живого человека.

@bp.get('/saas/wa/chats')
@require_auth(roles=CLIENT_READ_ROLES)
def wa_chats():
    tenant = _tenant_arg()
    rows = q(
        """
        SELECT chat_id,
               argMax(text, ts)                                   AS last_text,
               argMax(direction, ts)                              AS last_dir,
               max(ts)                                            AS last_ts,
               min(ts)                                            AS first_ts,
               argMaxIf(sender_name, ts, sender_name != '')       AS name,
               countIf(direction = 'in')                          AS inbound,
               count()                                            AS total
        FROM retention.wa_messages
        WHERE tenant_id = {t:String}
        GROUP BY chat_id
        ORDER BY last_ts DESC
        LIMIT 100
        """, {'t': tenant})[1]
    # привязка к юзеру продукта: контакт whatsapp с этим адресом (создаётся,
    # когда человек пришёл по подписанной connect-ссылке)
    bound = {str(r[0]): str(r[1]) for r in q(
        """
        SELECT address, client_user_id FROM retention.contacts_current
        WHERE tenant_id = {t:String} AND channel = 'whatsapp'
          AND client_user_id != ''
        """, {'t': tenant})[1]}
    # WhatsApp прячет номера за LID - карточка без разгадки показывает
    # бессмысленный идентификатор вместо телефона
    lids = {}
    if any('@lid' in str(r[0]) for r in rows):
        from stripe_sync.wa_personal import list_lids
        try:
            lids = list_lids(tenant)
        except Exception:  # noqa: BLE001 - WAHA лежит: карточка без номера
            lids = {}
    out = []
    for r in rows:
        digits = str(r[0]).split('@')[0]
        out.append({
            'chat_id': r[0], 'display': digits,
            'phone': lids.get(digits, digits if '@lid' not in str(r[0]) else ''),
            'last_text': r[1], 'last_dir': r[2], 'last_ts': str(r[3]),
            'first_ts': str(r[4]), 'name': r[5], 'inbound': int(r[6]),
            'total': int(r[7]),
            'client_user_id': bound.get(digits, '')})
    return api_json({'chats': out})


@bp.get('/saas/wa/messages')
@require_auth(roles=CLIENT_READ_ROLES)
def wa_messages():
    tenant = _tenant_arg()
    chat = str(request.args.get('chat') or '').strip()
    if not chat:
        return _bad('chat_required')
    rows = q(
        """
        SELECT wa_msg_id, direction, text, sender_name, ts
        FROM retention.wa_messages
        WHERE tenant_id = {t:String} AND chat_id = {c:String}
        ORDER BY ts ASC, wa_msg_id ASC LIMIT 500
        """, {'t': tenant, 'c': chat})[1]
    return api_json({'messages': [
        {'id': r[0], 'direction': r[1], 'text': r[2], 'name': r[3],
         'ts': str(r[4])} for r in rows]})


@bp.post('/saas/wa/reply')
@require_auth(roles=CLIENT_WRITE_ROLES)
def wa_reply():
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    chat = str(body.get('chat_id') or '').strip()
    text = str(body.get('text') or '').strip()
    if not chat or not text:
        return _bad('chat_and_text_required')
    from stripe_sync import wa_personal as wap
    ok, detail = wap.reply_as_human(tenant, chat, text)
    if not ok:
        return _bad(f'send_failed:{detail}', 502)
    # в тред сообщение ляжет эхом вебхука (message.any, fromMe) - с настоящим
    # id и без дублей; интерфейс показывает его оптимистично
    return api_json({'ok': True})


@bp.post('/saas/wa/start-chat')
@require_auth(roles=CLIENT_WRITE_ROLES)
def wa_start_chat():
    """Написать ПЕРВЫМ на новый номер - вручную, живым человеком.

    Проверяем, что номер вообще есть в WhatsApp (сообщение в пустоту - хуже
    честного отказа), берём канонический chat_id (часть аккаунтов живёт за
    @lid) и шлём тем же единственным ручным путём."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    phone = str(body.get('phone') or '').strip()
    text = str(body.get('text') or '').strip()
    if not phone or not text:
        return _bad('phone_and_text_required')
    from stripe_sync import wa_personal as wap
    exists, chat_id = wap.check_number(tenant, phone)
    if not exists:
        return _bad('number_not_on_whatsapp')
    ok, detail = wap.reply_as_human(tenant, chat_id, text)
    if not ok:
        return _bad(f'send_failed:{detail}', 502)
    # в тред ляжет эхом вебхука; фронт сразу открывает этот чат
    return api_json({'ok': True, 'chat_id': chat_id})


# ── Карточка юзера: всё о человеке + ручные действия ─────────────────────────
# Система юзероцентрична: вокруг человека собираются стадия, деньги, контакты,
# история касаний и события продукта - и отсюда же владелец действует руками:
# добавляет контакт, пишет в любой канал, зачисляет в кампанию.

def _user_row(tenant: str, ident: str):
    """Строка user_actions по identity_id ЛИБО client_user_id: в карточку
    ведут и таблица юзеров (identity), и WA-инбокс (client_user_id)."""
    rows = q(
        """
        SELECT identity_id, email_norm, client_user_id, stripe_customer_id,
               sub_status, plan_id, toFloat64(mrr), stage, recommended_action,
               value_at_stake, coalesce(p_convert, 0), coalesce(p_churn, 0),
               coalesce(ltv_estimate, 0),
               if(toUnixTimestamp(last_seen) = 0, '', toString(last_seen)),
               stage_note, coalesce(buy_intent, 0),
               if(toUnixTimestamp(last_seen) = 0, 1000000,
                  dateDiff('second', last_seen, now()))
        FROM user_actions
        WHERE tenant_id = {t:String}
          AND (identity_id = {i:String}
               OR (client_user_id = {i:String} AND client_user_id != ''))
        LIMIT 1
        """, {'t': tenant, 'i': ident})[1]
    return rows[0] if rows else None


# «Онлайн» = событие младше 3 минут: heartbeat идёт раз в 2, живой юзер не
# успевает протухнуть; порог длиннее - и «онлайн» видел бы уже ушедших.
ONLINE_THRESHOLD_S = 180


def _campaign_titles(tenant: str) -> list:
    import json as _json
    from pathlib import Path as _Path
    p = _Path(__file__).resolve().parent.parent / 'stripe_sync' / 'saas_campaigns.json'
    try:
        cfgs = _json.loads(p.read_text())
    except Exception:
        return []
    conf = cfgs.get(tenant) or cfgs.get('_default') or {}
    return [{'id': c['campaign_id'], 'title': str(c.get('title') or c['campaign_id'])}
            for c in conf.get('campaigns', [])]


def _autopilot_on(tenant: str) -> bool:
    """Живой ли автопилот тенанта: тот же резолв, что в campaign_tick.
    Карточка обязана честно сказать, что зачисление пойдёт вхолостую."""
    import json as _json
    from pathlib import Path as _Path

    # campaign_tick импортировать нельзя (flat-only модуль джоб) - резолв
    # зеркалим: рантайм-рубильник из tenants.json важнее git-конфига
    from stripe_sync.saas_senders import load_tenant_channels
    p = _Path(__file__).resolve().parent.parent / 'stripe_sync' / 'saas_campaigns.json'
    try:
        cfgs = _json.loads(p.read_text())
    except Exception:
        return False
    conf = cfgs.get(tenant) or cfgs.get('_default') or {}
    overrides = load_tenant_channels(tenant)
    if 'autopilot' in overrides:
        return bool(overrides['autopilot'])
    return bool(conf.get('autopilot'))


@bp.get('/saas/user')
@require_auth(roles=CLIENT_READ_ROLES)
def saas_user_card():
    tenant = _tenant_arg()
    ident = str(request.args.get('identity') or '').strip()
    if not ident:
        return _bad('identity_required')
    r = _user_row(tenant, ident)
    if not r:
        return _bad('user_not_found', 404)
    identity, email, cuid = str(r[0]), str(r[1]), str(r[2])

    user = {
        'identity_id': identity, 'email': email, 'client_user_id': cuid,
        'stripe_customer_id': r[3], 'sub_status': r[4], 'plan_id': r[5],
        'mrr': round(_flt(r[6]), 2), 'stage': r[7], 'action': r[8],
        'value_at_stake': round(_flt(r[9]), 2),
        'p_convert': round(_flt(r[10]), 2), 'p_churn': round(_flt(r[11]), 2),
        'ltv': round(_flt(r[12]), 2), 'last_seen': r[13], 'stage_note': r[14],
        'buy_intent': round(_flt(r[15]), 2) if len(r) > 15 else 0.0,
        'online': len(r) > 16 and _flt(r[16]) < ONLINE_THRESHOLD_S,
    }

    # Откуда взялся LTV: месяцы и basis лежат в фичах скоринга, замер когорты
    # (наблюдаемые месяцы, уходы) - в knowledge. Карточка обязана уметь
    # ответить на «с чего это вдруг», а не показывать голое число.
    try:
        import json as _json2
        # base-таблица: вьюха _current не выносит features
        fs = q("SELECT argMax(features, scored_at) FROM user_scores "
               "WHERE tenant_id = {t:String} AND identity_id = {i:String}",
               {'t': tenant, 'i': identity})[1]
        feats = _json2.loads(fs[0][0]) if fs and fs[0][0] else {}
        from stripe_sync.knowledge import load as _kb_load
        lc = _kb_load(_ch_direct(), tenant, 'lifecycle_measured')
        user['ltv_explain'] = {
            'months': feats.get('ltv_months'),
            'basis': feats.get('ltv_basis'),
            'observed_months': lc.get('obs_months'),
            'churned': lc.get('churned'),
            'sub_months': lc.get('sub_months'),
        }
    except Exception:
        user['ltv_explain'] = None

    # контакты каналов: лежат под client_user_id, у Stripe-only - под identity.
    # Ключа два, поэтому канал может встретиться дважды - берём запись под
    # cuid (основной ключ), identity - только как фолбэк.
    keys = [k for k in (cuid, identity) if k]
    by_channel: dict = {}
    if keys:
        for c in q(
            """
            SELECT channel, address, consent, consent_ts, client_user_id
            FROM contacts_current
            WHERE tenant_id = {t:String} AND client_user_id IN {k:Array(String)}
            ORDER BY channel
            """, {'t': tenant, 'k': keys})[1]:
            row = {'channel': c[0], 'address': c[1], 'consent': int(c[2]),
                   'consent_ts': str(c[3])}
            if c[0] not in by_channel or str(c[4]) == cuid:
                by_channel[c[0]] = row
    contacts = list(by_channel.values())

    # Телефон из Stripe Checkout (2026-08-28): показываем оператору в карточке.
    # consent=0 - оплата даёт согласие на сервисные касания, но НЕ на промо
    # SMS/WhatsApp (для этого нужно явное согласие; в US это ещё и TCPA). Так
    # оператор видит номер и может написать вручную, а автопилот его не трогает.
    stripe_phone = ''
    scid = str(r[3] or '')
    if scid:
        pr = q("SELECT argMax(phone, updated_at) FROM stripe_customers "
               "WHERE tenant_id = {t:String} AND customer_id = {c:String}",
               {'t': tenant, 'c': scid})[1]
        stripe_phone = str(pr[0][0]) if pr and pr[0] and pr[0][0] else ''
    if stripe_phone and not any(c['channel'] in ('whatsapp', 'sms')
                                for c in contacts):
        contacts.append({'channel': 'whatsapp', 'address': stripe_phone,
                         'consent': 0, 'consent_ts': '', 'source': 'stripe'})
    user['stripe_phone'] = stripe_phone

    email_suppressed = bool(email) and bool(q(
        "SELECT count() FROM email_suppressions_current "
        "WHERE tenant_id = {t:String} AND address = {a:String}",
        {'t': tenant, 'a': email.lower()})[1][0][0])

    enrollments = [{'campaign_id': e[0], 'status': e[1], 'step_idx': int(e[2]),
                    'next_step_at': str(e[3]), 'control': int(e[4]),
                    'enrolled_at': str(e[5])} for e in q(
        """
        SELECT campaign_id, status, step_idx, next_step_at, control, enrolled_at
        FROM campaign_enrollments_current
        WHERE tenant_id = {t:String} AND identity_id = {i:String}
        ORDER BY enrolled_at DESC
        """, {'t': tenant, 'i': identity})[1]]

    touches = [{'campaign_id': s[0], 'step_idx': int(s[1]), 'action': s[2],
                'detail': s[3], 'status': s[4], 'reason': s[5], 'ts': str(s[6])}
               for s in q(
        """
        SELECT campaign_id, step_idx, action, detail, status, reason, ts
        FROM campaign_send_log
        WHERE tenant_id = {t:String} AND identity_id = {i:String}
        ORDER BY ts DESC LIMIT 50
        """, {'t': tenant, 'i': identity})[1]]

    offers = [{'offer_id': o[0], 'campaign_id': o[1], 'status': o[2],
               'reason': o[3], 'cost_estimate': round(_flt(o[4]), 2),
               'issued_at': str(o[5])} for o in q(
        """
        SELECT offer_id, campaign_id, status, reason, cost_estimate, issued_at
        FROM offers_issued
        WHERE tenant_id = {t:String} AND identity_id = {i:String}
        ORDER BY issued_at DESC LIMIT 20
        """, {'t': tenant, 'i': identity})[1]]

    scid = str(r[3] or '')
    # Карта: срок действия для перехвата невольного оттока (истекает -> платёж
    # не пройдёт). Показываем всегда, предупреждение - если <=45 дней.
    card = None
    if scid:
        cr = q("""
            SELECT brand, last4, exp_month, exp_year, toInt32(days_to_expiry)
            FROM card_expiry_current
            WHERE tenant_id = {t:String} AND customer_id = {c:String}
            """, {'t': tenant, 'c': scid})[1]
        if cr:
            card = {'brand': str(cr[0][0]), 'last4': str(cr[0][1]),
                    'exp_month': int(cr[0][2]), 'exp_year': int(cr[0][3]),
                    'days_to_expiry': int(cr[0][4]),
                    'expiring_soon': 0 <= int(cr[0][4]) <= 45}

    events = [{'event_type': e[0], 'ts': str(e[1]), 'amount': round(_flt(e[2]), 2),
               'plan_id': e[3], 'page': e[4]} for e in q(
        """
        SELECT event_type, ts, amount, plan_id, page
        FROM saas_events
        WHERE tenant_id = {t:String}
          AND ((client_user_id = {c:String} AND {c:String} != '')
               OR (stripe_customer_id = {s:String} AND {s:String} != ''))
          AND event_type != 'heartbeat'  -- пульс кормит last_seen, читать нечего
        ORDER BY ts DESC LIMIT 30
        """, {'t': tenant, 'c': cuid, 's': scid})[1]] if (cuid or scid) else []

    # Поведение из сниппета v2: время в продукте, источник прихода, фрустрация.
    # Всё лежит в meta-JSON событий - агрегируем на лету, витрин не плодим.
    behavior = None
    if cuid:
        # События ДО ra.identify() уходят без client_user_id (session_start и
        # первый page_view почти всегда раньше логина). Пришиваем их через
        # сессию: события той же session_id, где человек позже опознался, - его.
        # окно 30д на подзапрос сессий (аудит r3 2026-08-26): карточка
        # показывает поведение за 14 дней, а session_id-подзапрос сканировал
        # всю историю партиции тенанта - ограничиваем тем же горизонтом
        own = ("(client_user_id = {c:String} OR (session_id != '' AND session_id IN ("
               "SELECT DISTINCT session_id FROM saas_events "
               "WHERE tenant_id = {t:String} AND client_user_id = {c:String} "
               "AND session_id != '' AND ts >= now() - INTERVAL 30 DAY)))")
        agg = q(
            f"""
            SELECT
              sumIf(JSONExtractInt(meta, 'seconds'), event_type = 'page_leave'),
              countIf(event_type = 'heartbeat') * 2,
              countIf(event_type = 'page_view'),
              countIf(event_type = 'rage_click'),
              countIf(event_type = 'js_error')
            FROM saas_events
            WHERE tenant_id = {{t:String}} AND {own}
              AND ts > now() - INTERVAL 14 DAY
            """, {'t': tenant, 'c': cuid})[1][0]
        import math as _math
        active_min = _math.ceil(_flt(agg[0]) / 60) + int(_flt(agg[1]))
        # источник: первый session_start с контекстом = как человек пришёл
        src = q(
            f"""
            SELECT JSONExtractString(meta, 'utm_source'),
                   JSONExtractString(meta, 'ref'),
                   JSONExtractString(meta, 'platform'),
                   JSONExtractInt(meta, 'mobile'),
                   JSONExtractString(meta, 'lang'),
                   JSONExtractString(meta, 'tz'),
                   JSONExtractString(JSONExtractRaw(meta, 'first'), 'utm_source'),
                   JSONExtractString(JSONExtractRaw(meta, 'first'), 'ref')
            FROM saas_events
            WHERE tenant_id = {{t:String}} AND {own}
              AND event_type = 'session_start' AND meta != ''
            ORDER BY ts DESC LIMIT 1
            """, {'t': tenant, 'c': cuid})[1]
        top_pages = [{'page': p[0], 'views': int(p[1])} for p in q(
            f"""
            SELECT page, count() FROM saas_events
            WHERE tenant_id = {{t:String}} AND {own}
              AND event_type = 'page_view' AND page != ''
              AND ts > now() - INTERVAL 14 DAY
            GROUP BY page ORDER BY count() DESC LIMIT 5
            """, {'t': tenant, 'c': cuid})[1]]
        s0 = src[0] if src else ('', '', '', 0, '', '', '', '')
        # Устройство/гео/RFM/vitals - из готовой витрины фич (та же, что кормит
        # скоринг: одни данные - одни цифры на всех экранах).
        feat = q(
            """
            SELECT geo_country, os_family, device_type, gpu, device_model,
                   toInt32(pricing_visits), toInt32(visit_count),
                   toInt32(inp_ms), toInt32(lcp_ms), toInt32(datacenter)
            FROM user_event_features
            WHERE tenant_id = {t:String} AND identity_id = {i:String}
            """, {'t': tenant, 'i': identity})[1]
        fx = feat[0] if feat else ('', '', '', '', '', 0, 0, 0, 0, 0)
        behavior = {
            'active_min_14d': active_min,
            'pages_14d': int(agg[2] or 0),
            'rage_14d': int(agg[3] or 0),
            'errors_14d': int(agg[4] or 0),
            'utm_source': str(s0[6] or s0[0] or ''),
            'ref': str(s0[7] or s0[1] or ''),
            'platform': str(s0[2] or ''), 'mobile': int(s0[3] or 0),
            'lang': str(s0[4] or ''), 'tz': str(s0[5] or ''),
            'top_pages': top_pages,
            'country': str(fx[0] or ''), 'os': str(fx[1] or ''),
            'device_type': str(fx[2] or ''),
            'gpu': str(fx[3] or ''), 'device_model': str(fx[4] or ''),
            'pricing_visits': int(fx[5] or 0), 'visits': int(fx[6] or 0),
            'inp_ms': int(fx[7] or 0), 'lcp_ms': int(fx[8] or 0),
            'datacenter': int(fx[9] or 0),
        }
        if not (active_min or behavior['pages_14d'] or src or behavior['country']):
            behavior = None      # сниппет-данных нет - блок не показываем

    # личный WhatsApp: если адрес контакта совпадает с тредом инбокса,
    # карточка даёт прямой переход в переписку
    wa_chat = ''
    wa_addr = next((c['address'] for c in contacts if c['channel'] == 'whatsapp'), '')
    if wa_addr:
        # точное совпадение: префикс однажды свёл бы короткий номер
        # с чужим тредом, у которого номер длиннее
        hit = q(
            "SELECT chat_id FROM retention.wa_messages "
            "WHERE tenant_id = {t:String} "
            "AND chat_id IN ({c:String}, {l:String}) LIMIT 1",
            {'t': tenant, 'c': f'{wa_addr}@c.us', 'l': f'{wa_addr}@lid'})[1]
        wa_chat = str(hit[0][0]) if hit else ''

    # Голос человека: его тикеты и отзывы - обязательный контекст перед
    # ручным касанием («вы нам писали про баг - починили»)
    voice = []
    try:
        voice = [{'ts': str(r[0])[:16], 'kind': r[1], 'category': r[2],
                  'text': r[3]} for r in q("""
            SELECT ts, event_type, JSONExtractString(meta, 'category'),
                   JSONExtractString(meta, 'message')
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND identity_id = {i:String}
              AND event_type IN ('feedback', 'support_ticket')
            ORDER BY ts DESC LIMIT 5
            """, {'t': tenant, 'i': identity})[1]]
    except Exception:  # noqa: BLE001
        pass

    from flask import g
    role = str((getattr(g, 'api_user', None) or {}).get('role') or '')
    return api_json({
        'tenant': tenant, 'user': user, 'contacts': contacts,
        'email_suppressed': email_suppressed, 'enrollments': enrollments,
        'touches': touches, 'offers': offers, 'events': events,
        'campaigns': _campaign_titles(tenant), 'wa_chat': wa_chat,
        'behavior': behavior, 'card': card, 'voice': voice,
        'autopilot': _autopilot_on(tenant),
        # что может ЭТА роль: support пишет людям, но кампании не трогает
        'can_touch': role in CLIENT_WRITE_ROLES,
        'can_enroll': role in CHANNEL_WRITE_ROLES,
    })


def _now_ch() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


@bp.post('/saas/user/contact')
@require_auth(roles=CLIENT_WRITE_ROLES)
def saas_user_contact():
    """Завести контакт руками. Галочка согласия в форме - утверждение
    владельца, что канал дал согласие; без неё касания не пойдут (no_consent),
    но адрес сохранится."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    ident = str(body.get('identity') or '').strip()
    if not ident:
        return _bad('identity_required')
    r = _user_row(tenant, ident)
    if not r:
        return _bad('user_not_found', 404)
    from stripe_sync.manual_touch import validate_contact
    address, err = validate_contact(str(body.get('channel') or ''),
                                    str(body.get('address') or ''))
    if err:
        return _bad(err)
    channel = str(body.get('channel')).strip().lower()
    consent = 1 if body.get('consent') else 0
    # ключ контакта: client_user_id, у Stripe-only юзера - identity_id
    key = str(r[2]) or str(r[0])
    now = _now_ch()
    _ch_direct().insert(
        'retention.contacts',
        [[tenant, key, channel, address, consent, now, now]],
        column_names=['tenant_id', 'client_user_id', 'channel', 'address',
                      'consent', 'consent_ts', 'updated_at'])
    print(f'[user_card] {tenant}: contact {channel}={address} '
          f'consent={consent} for {key}', flush=True)
    return api_json({'ok': True, 'channel': channel, 'address': address,
                     'consent': consent})


@bp.post('/saas/user/touch')
@require_auth(roles=CLIENT_WRITE_ROLES)
def saas_user_touch():
    """Ручное касание одному человеку. Решение живого человека, поэтому
    выключенный автопилот его не глушит; согласие и супрессии - обязательны."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    ident = str(body.get('identity') or '').strip()
    channel = str(body.get('channel') or '').strip().lower()
    subject = str(body.get('subject') or '').strip()
    text = str(body.get('body') or '').strip()
    if not ident or not channel:
        return _bad('identity_and_channel_required')
    r = _user_row(tenant, ident)
    if not r:
        return _bad('user_not_found', 404)
    identity, email, cuid, stage = str(r[0]), str(r[1]), str(r[2]), str(r[7])
    if not text:
        return _bad('empty')
    if channel not in ('inapp', 'whatsapp', 'email', 'sms', 'viber', 'telegram'):
        return _bad('unknown_channel')

    from stripe_sync.manual_touch import (SEND_LOG_COLUMNS, manual_send,
                                          send_log_row)
    ch = _ch_direct()
    now = _now_ch()

    def _log(status, reason='', pid=''):
        ch.insert('retention.campaign_send_log',
                  [send_log_row(tenant, identity, channel, subject, text,
                                status, reason, now, pid)],
                  column_names=SEND_LOG_COLUMNS)

    if channel == 'inapp':
        if not cuid:
            return _bad('no_client_user_id')
        cta = str(body.get('cta_url') or '').strip()
        # expires_at - plain DateTime: клиенту CH нужен datetime-объект,
        # строка здесь падает ('str' has no timestamp)
        exp = _dt.datetime.now(tz=_dt.timezone.utc) + _dt.timedelta(days=7)
        ch.insert(
            'retention.inapp_inbox',
            [[tenant, f'manual:{identity}:{now}', cuid, identity, 'manual', -1,
              subject, text, str(body.get('cta_label') or '').strip(),
              cta, stage, exp, now]],
            column_names=['tenant_id', 'message_id', 'client_user_id',
                          'identity_id', 'campaign_id', 'step_idx', 'title',
                          'body', 'cta_label', 'cta_url', 'entry_stage',
                          'expires_at', 'created_at'])
        _log('queued')
        return api_json({'ok': True, 'status': 'queued'})

    if channel == 'whatsapp':
        # свободный текст - только личный номер, тем же единственным ручным
        # путём, что и инбокс
        contact = q(
            "SELECT address, consent FROM contacts_current "
            "WHERE tenant_id = {t:String} "
            "AND client_user_id IN {k:Array(String)} AND channel = 'whatsapp'",
            {'t': tenant, 'k': [k for k in (cuid, identity) if k]})[1]
        if not contact:
            return _bad('no_contact')
        if not int(contact[0][1]):
            # UI канал без согласия не показывает, но API - тоже граница
            _log('rejected', 'no_consent')
            return _bad('no_consent')
        from stripe_sync import wa_personal as wap
        # у нового тенанта личный номер может быть не подключён вовсе -
        # честный отказ «канал не подключён», а не «номера нет в WhatsApp»
        _ok, wa_status, _num = wap.get_status(tenant)
        if not _ok or wa_status != 'WORKING':
            return _bad('wa_not_connected', 502)
        exists, chat_id = wap.check_number(tenant, str(contact[0][0]))
        if not exists:
            return _bad('number_not_on_whatsapp')
        ok, detail = wap.reply_as_human(tenant, chat_id, text)
        _log('sent' if ok else 'rejected', '' if ok else detail)
        if not ok:
            return _bad(f'send_failed:{detail}', 502)
        return api_json({'ok': True, 'status': 'sent', 'chat_id': chat_id})

    # email / sms / viber / telegram - общий транспорт кампаний
    if channel == 'email':
        if not email:
            return _bad('no_contact')
        if bool(q("SELECT count() FROM email_suppressions_current "
                  "WHERE tenant_id = {t:String} AND address = {a:String}",
                  {'t': tenant, 'a': email.lower()})[1][0][0]):
            _log('rejected', 'suppressed')
            return _bad('suppressed')
        address = email
    else:
        row = q(
            "SELECT address, consent FROM contacts_current "
            "WHERE tenant_id = {t:String} "
            "AND client_user_id IN {k:Array(String)} AND channel = {c:String}",
            {'t': tenant, 'k': [k for k in (cuid, identity) if k],
             'c': channel})[1]
        if not row:
            return _bad('no_contact')
        if not int(row[0][1]):
            _log('rejected', 'no_consent')
            return _bad('no_consent')
        address = str(row[0][0])

    from stripe_sync.saas_senders import (EmailConfig, MessagingConfig,
                                          tenant_configs)
    email_cfg, msg_cfg = tenant_configs(tenant, EmailConfig.from_env(),
                                        MessagingConfig.from_env())
    ok, detail = manual_send(channel, address, subject, text, email_cfg, msg_cfg)
    if not ok:
        _log('rejected', detail)
        return _bad(f'send_failed:{detail}', 502)
    pid = detail if detail != 'dry_run' else ''
    _log('dry_run' if detail == 'dry_run' else 'sent', '', pid)
    return api_json({'ok': True,
                     'status': 'dry_run' if detail == 'dry_run' else 'sent'})


@bp.post('/saas/user/enroll')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_user_enroll():
    """Зачислить в кампанию руками / снять с кампании. Ручное зачисление
    всегда target (control=0): владелец сознательно хочет касаний, молчащий
    холдаут его бы обманул."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    ident = str(body.get('identity') or '').strip()
    cid = str(body.get('campaign_id') or '').strip()
    action = str(body.get('action') or 'enroll').strip()
    if not ident or not cid:
        return _bad('identity_and_campaign_required')
    if cid not in {c['id'] for c in _campaign_titles(tenant)}:
        return _bad('unknown_campaign')
    r = _user_row(tenant, ident)
    if not r:
        return _bad('user_not_found', 404)
    identity, stage = str(r[0]), str(r[7])

    cur = q(
        "SELECT status, control, step_idx, enrolled_at "
        "FROM campaign_enrollments_current WHERE tenant_id = {t:String} "
        "AND campaign_id = {c:String} AND identity_id = {i:String}",
        {'t': tenant, 'c': cid, 'i': identity})[1]
    now = _now_ch()
    ch = _ch_direct()
    cols = ['tenant_id', 'campaign_id', 'identity_id', 'control',
            'entry_stage', 'step_idx', 'next_step_at', 'status',
            'enrolled_at', 'updated_at']

    if action == 'exit':
        if not cur or str(cur[0][0]) != 'active':
            return _bad('not_active')
        ch.insert('retention.campaign_enrollments',
                  [[tenant, cid, identity, int(cur[0][1]), stage,
                    int(cur[0][2]), now, 'exited', cur[0][3], now]],
                  column_names=cols)
        print(f'[user_card] {tenant}: {identity} exited {cid}', flush=True)
        return api_json({'ok': True, 'status': 'exited'})

    if cur and str(cur[0][0]) == 'active':
        return _bad('already_enrolled')
    # ЧИСТОТА ЗАМЕРА (аудит r2 2026-08-26): человек, однажды попавший в holdout
    # (control=1), обязан ОСТАТЬСЯ в контроле навсегда - иначе ручной
    # перезаход владельца молча переносил бы отобранных им риск-юзеров из
    # контроля в target, ровно тот selection-bias, ради устранения которого
    # holdout и существует. Прежний control сохраняем.
    prior_control = int(cur[0][1]) if cur else 0
    ch.insert('retention.campaign_enrollments',
              [[tenant, cid, identity, prior_control, stage, 0, now, 'active', now, now]],
              column_names=cols)
    print(f'[user_card] {tenant}: {identity} enrolled into {cid} manually'
          f'{" (holdout preserved)" if prior_control else ""}', flush=True)
    return api_json({'ok': True, 'status': 'active'})


# ── Здоровье конвейера: дирижёр сверху видим владельцу ───────────────────────
# Каждая стадия (сбор->ститч->фичи->скоринг->офферы/кампании->замер) пишет в
# pipeline_runs. Здесь - последний прогон каждой + свежесть, чтобы было видно,
# считаются ли цифры на актуальных данных или контур где-то встал.

# Ожидаемый порядок стадий + человеко-понятные имена (i18n на фронте по ключу).
_PIPELINE_STAGES = [
    ('stitch', 'identity'), ('plans', 'plans'), ('contacts', 'contacts'),
    ('users_sync', 'users'), ('product_sync', 'product'),
    ('cancel_reasons', 'reasons'),
    ('scoring', 'scoring'), ('campaign_tick', 'campaigns'),
    ('triggers', 'triggers'),
    ('uplift_report', 'uplift'), ('ai_analyst', 'analyst'),
    ('product_insights', 'productai'),
    ('ops_guard', 'guard'),
]

# Окно свежести выхода стадии (часы) - зеркало ops_loop.STAGES.fresh_h.
_STAGE_FRESH_H = {
    'stitch': 2, 'plans': 26, 'contacts': 26, 'users_sync': 26,
    'product_sync': 26, 'cancel_reasons': 26, 'scoring': 26, 'campaign_tick': 26,
    'triggers': 1, 'ops_guard': 1, 'product_insights': 24 * 8,
    'uplift_report': 24, 'ai_analyst': 24,
}


@bp.get('/saas/pipeline')
@require_auth(roles=LEAK_ROLES)
def saas_pipeline():
    """Здоровье конвейера: последний прогон каждой стадии + свежесть."""
    tenant = _tenant_arg()
    rows = {r[0]: r for r in q(
        """
        SELECT stage, status, detail, input_fresh, skipped_reason,
               rows, duration_s, toString(last_run), age_min,
               toString(last_ok), ok_age_min
        FROM pipeline_health WHERE tenant_id = {t:String}
        """, {'t': tenant})[1]}

    stages = []
    for stage, label in _PIPELINE_STAGES:
        r = rows.get(stage)
        if not r:
            stages.append({'stage': stage, 'label': label, 'status': 'never',
                           'fresh': False})
            continue
        ok_age_min = int(_flt(r[10]))
        fresh_h = _STAGE_FRESH_H.get(stage, 26)
        # свежесть = последний УСПЕХ в окне (стадия могла упасть последней, но
        # её выход ещё годен с прошлого успеха)
        fresh = bool(r[9]) and ok_age_min <= fresh_h * 60
        stages.append({
            'stage': stage, 'label': label, 'status': str(r[1]),
            'detail': str(r[2]), 'skipped_reason': str(r[4]),
            'rows': int(_flt(r[5])), 'duration_s': round(_flt(r[6]), 1),
            'last_run': str(r[7]), 'age_min': int(_flt(r[8])),
            'last_ok': str(r[9]), 'ok_age_min': ok_age_min,
            'fresh_h': fresh_h, 'fresh': fresh,
        })
    # общий вердикт: контур здоров, если КАЖДАЯ стадия свежа (или ещё не
    # наступало её расписание - тогда 'never' не роняет вердикт до первого прогона)
    ran = [s for s in stages if s['status'] != 'never']
    healthy = bool(ran) and all(s['fresh'] for s in ran)
    return api_json({'tenant': tenant, 'stages': stages, 'healthy': healthy,
                     'ran': len(ran), 'total': len(stages),
                     'data': _data_quality(tenant),
                     'llm': _llm_runs(tenant)})


def _data_quality(tenant: str) -> dict:
    """Качество ПРИЁМА данных: полнота склейки, достижимость, доля анонимов,
    лаг источников, богатство меты. Здоровье стадий говорит «джобы бегут»,
    этот блок - «данные, которые они переносят, полноценны»."""
    out: dict = {}
    try:
        r = q("""
            SELECT count(), countIf(email_norm != ''),
                   countIf(stripe_customer_id != ''),
                   countIf(notEmpty(client_user_ids))
            FROM identities_current WHERE tenant_id = {t:String}
            """, {'t': tenant})[1][0]
        out['identities'] = {'total': int(r[0]), 'with_email': int(r[1]),
                             'with_stripe': int(r[2]), 'with_product_id': int(r[3])}
        unmatched = int(q(
            "SELECT count() FROM identity_unmatched WHERE tenant_id = {t:String}",
            {'t': tenant})[1][0][0])
        out['identities']['unmatched'] = unmatched

        r = q("""
            SELECT count(),
                   countIf(client_user_id != '' OR email_hash != ''),
                   countIf(JSONHas(meta, 'visits') OR JSONHas(meta, 'inp')
                           OR JSONHas(meta, 'seconds'))
            FROM saas_events
            WHERE tenant_id = {t:String} AND source = 'snippet'
              AND ts >= now() - INTERVAL 1 DAY
            """, {'t': tenant})[1][0]
        total = int(r[0])
        out['snippet_24h'] = {'events': total, 'identified': int(r[1]),
                              'rich_meta': int(r[2])}

        # лаг источников: насколько отстаёт самое свежее событие каждого
        lags = q("""
            SELECT source, dateDiff('minute', max(ts), now())
            FROM saas_events WHERE tenant_id = {t:String}
              AND source IN ('snippet', 'stripe', 'product')
            GROUP BY source
            """, {'t': tenant})[1]
        out['source_lag_min'] = {str(r0): int(r1) for r0, r1 in lags}

        out['dead_letters_24h'] = int(q(
            "SELECT count() FROM saas_events_dead "
            "WHERE received_at >= now() - INTERVAL 1 DAY")[1][0][0])
    except Exception as exc:  # noqa: BLE001 - блок наблюдаемости не роняет экран
        print(f'[pipeline] {tenant}: data quality failed: {exc}', flush=True)
        return {}
    return out


def _llm_runs(tenant: str) -> list:
    """Последние обращения к LLM: сколько принято/отбраковано валидацией."""
    try:
        return [{'stage': r[0], 'status': r[1], 'kept': int(r[2]),
                 'rejected': int(r[3]), 'ts': str(r[4])} for r in q(
            """
            SELECT stage, status, kept, rejected, toString(ts)
            FROM llm_runs WHERE tenant_id = {t:String}
            ORDER BY ts DESC LIMIT 8
            """, {'t': tenant})[1]]
    except Exception:  # noqa: BLE001
        return []


@bp.get('/saas/launches')
@require_auth(roles=LEAK_ROLES)
def saas_launches():
    """Экран «Запуски»: когорты по дням + сегменты застревания с кнопкой
    «кампания на них» (audience уходит в конструктор как есть)."""
    from stripe_sync import launches_payload as lp
    tenant = _tenant_arg()
    return api_json({
        'tenant': tenant,
        'cohorts': lp.cohorts(q, tenant, days=21),
        'segments': lp.stuck_segments(q, tenant),
    })


@bp.get('/saas/retention')
@require_auth(roles=LEAK_ROLES)
def saas_retention():
    """«Удержание»: риск-лист с причинами + недельный возврат + спасённое."""
    from stripe_sync import retention_payload as rp
    tenant = _tenant_arg()
    return api_json({
        'tenant': tenant,
        'risk': rp.risk_list(q, tenant),
        'weekly': rp.weekly_return(q, tenant),
        'saved': rp.saved(q, tenant),
    })


@bp.get('/saas/money')
@require_auth(roles=LEAK_ROLES)
def saas_money():
    """«Деньги»: разложение изменения выручки + отмены с причинами."""
    from stripe_sync import money_payload as mp
    from stripe_sync import analytics_payload as ap
    tenant = _tenant_arg()
    return api_json({
        'tenant': tenant,
        'decomposition': mp.decomposition(q, tenant),
        'cancel_reasons': mp.cancel_reasons(q, tenant),
        'cash': ap._cash(q, {'t': tenant}),
        'revenue': ap._revenue(q, {'t': tenant}),
    })


# ── Вкладка «Аналитика» + внешний шаринг ─────────────────────────────────────
# Профессиональный дашборд «что происходит»: рост, гео, воронка, деньги,
# устройства. Один вызов - весь экран. Плюс read-only внешняя ссылка (без PII),
# которую владелец даёт инвестору/партнёру, не открывая им кабинет.

def _analytics_write_client():
    import clickhouse_connect as _cc
    import os as _os5
    return _cc.get_client(host=_os5.environ.get('CH_HOST', 'clickhouse'),
                          port=int(_os5.environ.get('CH_PORT', '8123')),
                          username=_os5.environ.get('CH_USER', 'default'),
                          password=_os5.environ.get('CH_PASSWORD', ''),
                          database=_os5.environ.get('CH_DB', 'retention'))


def _share_state(tenant: str) -> dict:
    """Текущее состояние внешней ссылки тенанта: {enabled, token}."""
    try:
        r = q("SELECT token, enabled FROM analytics_shares_current "
              "WHERE tenant_id = {t:String}", {'t': tenant})[1]
        if r and int(r[0][1]) == 1 and str(r[0][0]):
            return {'enabled': True, 'token': str(r[0][0])}
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] share_state {tenant}: {exc}', flush=True)
    return {'enabled': False, 'token': ''}


def _share_url(token: str) -> str:
    host = _host()
    base = host if host.startswith('http') else (f'https://{host}' if host else '')
    return f'{base}/a/{token}' if token else ''


@bp.get('/saas/analytics')
@require_auth(roles=LEAK_ROLES)
def saas_analytics():
    """Весь дашборд аналитики + состояние внешней ссылки."""
    from stripe_sync import analytics_payload as ap
    tenant = _tenant_arg()
    data = ap.build(q, tenant, public=False)
    st = _share_state(tenant)
    data['share'] = {'enabled': st['enabled'], 'url': _share_url(st['token'])}
    return api_json(data)


@bp.post('/saas/analytics/share')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def saas_analytics_share():
    """Управление внешней ссылкой: enable | rotate | disable.
    enable - создаёт токен, если ссылки ещё нет (иначе отдаёт текущую);
    rotate - выдаёт новый токен (старая ссылка мгновенно битая);
    disable - гасит (enabled=0), не удаляя историю."""
    tenant, _err = _tenant_arg_write()
    if _err:
        return _err
    body = request.get_json(silent=True) or {}
    action = str(body.get('action') or 'enable').strip()
    if action not in ('enable', 'rotate', 'disable'):
        return _bad(f'bad_action:{action}')

    cur = _share_state(tenant)
    if action == 'enable' and cur['enabled']:
        token, enabled = cur['token'], 1
    elif action == 'disable':
        token, enabled = cur['token'] or _secrets.token_urlsafe(16), 0
    else:  # enable-без-ссылки или rotate
        token, enabled = _secrets.token_urlsafe(16), 1

    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(tz=_tz.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    cl = _analytics_write_client()
    cl.insert('retention.analytics_shares',
              [[tenant, token, enabled, now, now]],
              column_names=['tenant_id', 'token', 'enabled', 'created_at', 'updated_at'])
    print(f'[analytics] {tenant}: share {action} -> enabled={enabled}', flush=True)
    return api_json({'enabled': bool(enabled),
                     'url': _share_url(token) if enabled else ''})


def _mask_email(e: str) -> str:
    """a***@domain: наружу по ссылке личные адреса целиком не отдаём."""
    e = str(e or '')
    if '@' not in e:
        return e[:2] + '***' if e else ''
    name, dom = e.split('@', 1)
    return (name[:2] or '*') + '***@' + dom


def _share_tenant(token: str) -> str:
    row = q("SELECT tenant_id FROM analytics_shares_current "
            "WHERE token = {tok:String} AND enabled = 1 LIMIT 1",
            {'tok': (token or '').strip()})[1]
    return str(row[0][0]) if row else ''


@bp.get('/public/report/<token>/<section>')
def public_report(token: str, section: str):
    """Публичный полный отчёт по ссылке: analytics | money | launches |
    retention. Без авторизации, БЕЗ PII: email в риск-листе маскируются,
    identity наружу не уходит, кнопок действий нет."""
    tenant = _share_tenant(token)
    if not tenant:
        return api_json(error='link not found', code=404)
    tch = ca.load_tenants().get(tenant, {}) or {}
    brand = {'company': str(tch.get('company') or tch.get('name') or 'Revenue Autopilot')}

    if section == 'analytics':
        from stripe_sync import analytics_payload as ap
        data = ap.build(q, tenant, public=True)
        data.pop('tenant', None)
    elif section == 'money':
        from stripe_sync import analytics_payload as ap
        from stripe_sync import money_payload as mp
        data = {'decomposition': mp.decomposition(q, tenant),
                'cancel_reasons': mp.cancel_reasons(q, tenant),
                'cash': ap._cash(q, {'t': tenant}),
                'revenue': ap._revenue(q, {'t': tenant})}
    elif section == 'launches':
        from stripe_sync import launches_payload as lp
        segs = [{k: v for k, v in s0.items() if k != 'audience'}
                for s0 in (lp.stuck_segments(q, tenant) or [])]
        data = {'cohorts': lp.cohorts(q, tenant, days=21), 'segments': segs}
    elif section == 'retention':
        from stripe_sync import retention_payload as rp
        risk = [{'email': _mask_email(r0['email']), 'mrr': r0['mrr'],
                 'p_churn': r0['p_churn'], 'stage': r0['stage'],
                 'reasons': r0['reasons']}
                for r0 in (rp.risk_list(q, tenant) or [])]
        data = {'risk': risk, 'weekly': rp.weekly_return(q, tenant),
                'saved': rp.saved(q, tenant)}
    else:
        return api_json(error='unknown section', code=404)
    data['brand'] = brand
    return api_json(data)


@bp.get('/public/analytics/<token>')
def public_analytics(token: str):
    """Публичный read-only дашборд по токену. БЕЗ авторизации - но без PII:
    только агрегаты (гео/воронка/деньги в сумме), ни одного email/имени."""
    from stripe_sync import analytics_payload as ap
    token = (token or '').strip()
    row = q("SELECT tenant_id FROM analytics_shares_current "
            "WHERE token = {tok:String} AND enabled = 1 LIMIT 1",
            {'tok': token})[1]
    if not row:
        return api_json(error='link not found', code=404)
    tenant = str(row[0][0])
    data = ap.build(q, tenant, public=True)
    # наружу не отдаём даже tenant_id (внутренний идентификатор)
    data.pop('tenant', None)
    tch = ca.load_tenants().get(tenant, {}) or {}
    data['brand'] = {'company': str(tch.get('company') or tch.get('name') or 'Revenue Autopilot')}
    return api_json(data)
