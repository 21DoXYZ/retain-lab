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


@bp.get('/saas/uplift')
@require_auth(roles=LEAK_ROLES)
def uplift():
    """Последний uplift-отчёт по каждой кампании (uplift_reports пишет
    stripe_sync/uplift_report.py, расписание - Пн 08:00). Инкремент = 
    (conv_target - conv_control) x N_target x средний чек; n_control=0 -> n/a."""
    tenant = request.args.get('tenant') or DEFAULT_TENANT

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
    tenant = request.args.get('tenant') or DEFAULT_TENANT

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
    touches_7d = int(q(
        "SELECT count() FROM campaign_send_log "
        "WHERE tenant_id = {t:String} AND ts >= now() - INTERVAL 7 DAY",
        {'t': tenant})[1][0][0])

    # Онбординг: демо-данные или живой Stripe; сниппет уже шлёт события?
    live_customers = int(q(
        "SELECT count() FROM stripe_customers WHERE tenant_id = {t:String} "
        "AND customer_id NOT LIKE 'cus_mock%' AND customer_id NOT LIKE 'cus_demo%'",
        {'t': tenant})[1][0][0])
    snippet_events = int(q(
        "SELECT count() FROM saas_events WHERE tenant_id = {t:String} AND source = 'snippet'",
        {'t': tenant})[1][0][0])

    return api_json({
        'tenant': tenant,
        'mrr': round(mrr, 2),
        'users_total': sum(stages.values()),
        'stages': stages,
        'at_risk_now': stages.get('DUNNING', 0) + stages.get('SAVE', 0),
        'dunning_mrr': round(dunning_mrr, 2),
        'campaigns': {'active_enrollments': int(camp[0] or 0),
                      'holdout': int(camp[1] or 0),
                      'touches_7d': touches_7d},
        'setup': {'stripe_connected': live_customers > 0,
                  'snippet_connected': snippet_events > 0},
    })


@bp.get('/saas/users')
@require_auth(roles=LEAK_ROLES)
def saas_users():
    """Список юзеров SaaS-контура: identity + стадия + действие + скоры.
    ?stage=DUNNING - фильтр; сортировка: ценность на кону, затем MRR."""
    tenant = request.args.get('tenant') or DEFAULT_TENANT
    stage = (request.args.get('stage') or '').upper()

    where = "tenant_id = {t:String}"
    params = {'t': tenant}
    if stage:
        where += " AND stage = {s:String}"
        params['s'] = stage

    rows = q(
        f"""
        SELECT identity_id, email_norm, client_user_id, stripe_customer_id,
               sub_status, plan_id, toFloat64(mrr), stage, recommended_action,
               value_at_stake, coalesce(p_convert, 0), coalesce(p_churn, 0),
               coalesce(ltv_estimate, 0),
               if(toUnixTimestamp(last_seen) = 0, '', toString(last_seen))
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
    } for r in rows]

    stages = {r[0]: int(r[1]) for r in q(
        "SELECT stage, count() FROM user_actions WHERE tenant_id = {t:String} GROUP BY stage",
        {'t': tenant})[1]}

    return api_json({'tenant': tenant, 'stages': stages, 'users': users})


@bp.get('/saas/offers')
@require_auth(roles=LEAK_ROLES)
def saas_offers():
    """Каталог офферов тенанта (stripe_sync/offers_catalog.json - есть в образе
    борда: COPY . .) + статистика выдач из offers_issued."""
    import json as _json
    import os as _os

    tenant = request.args.get('tenant') or DEFAULT_TENANT
    path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         'stripe_sync', 'offers_catalog.json')
    catalog = _json.load(open(path)).get(tenant, {})

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
        'stats': stats.get(o['offer_id'],
                           {'issued': 0, 'dry_run': 0, 'holdout': 0, 'rejected': 0}),
    } for o in catalog.get('offers', [])]

    return api_json({'tenant': tenant, 'control_pct': catalog.get('control_pct', 10),
                     'offers': offers})


# ── Каналы: клиентский флоу подключения (Phase 4) ────────────────────────────
# Партнёрская модель: аккаунты провайдеров наши, клиент подключает только
# идентичность бренда (поддомен, альфа-имя, свой бот). Состояние - в
# secrets/tenants.json (том rw у board), пишет его stripe_sync.channels_admin.

import os as _os
import secrets as _secrets

from stripe_sync import channels_admin as ca

CHANNEL_WRITE_ROLES = ('super_admin', 'director', 'head_retention')


def _platform(name: str) -> bool:
    return bool(_os.environ.get(name, '').strip())


def _tenant_arg() -> str:
    return (request.args.get('tenant') or (request.get_json(silent=True) or {}).get('tenant')
            or DEFAULT_TENANT)


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
    resend_key = _platform('RESEND_API_KEY')
    dt_key = _platform('DECISION_API_KEY')
    bot_user = str(tch.get('telegram_bot_username', ''))

    channels = [
        {'channel': 'email', 'provider': 'Resend', 'state': ca.email_state(tch, resend_key),
         'detail': tch.get('email_from') or tch.get('email_domain', ''),
         'contacts': email_users, 'consented': email_users,
         'email': {'domain': tch.get('email_domain', ''),
                   'from': tch.get('email_from', ''),
                   'dns_records': tch.get('email_dns_records', [])}},
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
        {'channel': 'whatsapp', 'provider': 'DecisionTelecom', 'state': 'coming_soon',
         'detail': '', **cov.get('whatsapp', {'contacts': 0, 'consented': 0})},
    ]
    return {'tenant': tenant, 'channels': channels}


@bp.get('/saas/channels')
@require_auth(roles=LEAK_ROLES)
def channels():
    return api_json(_channels_payload(_tenant_arg()))


def _bad(reason: str, code: int = 400):
    return api_json(None, code, reason)


@bp.post('/saas/channels/email/domain')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_email_domain():
    """Клиент вводит свой поддомен отправки (mail.клиент.com). С ключом Resend
    сразу создаём домен и возвращаем DNS-записи; без ключа фиксируем запрос
    (awaiting_provider) - создание догонит /verify, когда ключ появится."""
    tenant = _tenant_arg()
    domain = str((request.get_json(silent=True) or {}).get('domain', '')).strip().lower()
    if not ca.DOMAIN_RE.match(domain):
        return _bad('invalid_domain')

    key = _os.environ.get('RESEND_API_KEY', '').strip()
    if not key:
        ca.update_tenant(tenant, {'email_domain': domain,
                                  'email_domain_status': 'awaiting_provider',
                                  'email_domain_id': None, 'email_dns_records': None})
        print(f'[channels] {tenant}: email domain {domain} запрошен (ключа Resend ещё нет)',
              flush=True)
        return api_json(_channels_payload(tenant))

    ok, status, data = ca.resend_create_domain(domain, key)
    if not ok:
        return _bad(f'resend_{status}', 502)
    ca.update_tenant(tenant, {'email_domain': domain,
                              'email_domain_id': str(data.get('id', '')),
                              'email_domain_status': 'pending_dns',
                              'email_dns_records': ca.dns_rows(data)})
    print(f'[channels] {tenant}: email domain {domain} создан в Resend', flush=True)
    return api_json(_channels_payload(tenant))


@bp.post('/saas/channels/email/verify')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_email_verify():
    """Кнопка «Проверить DNS»: дергаем верификацию и перечитываем статус."""
    tenant = _tenant_arg()
    tch = ca.load_tenants().get(tenant, {}) or {}
    domain = str(tch.get('email_domain', ''))
    if not domain:
        return _bad('no_domain')
    key = _os.environ.get('RESEND_API_KEY', '').strip()
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
    tenant = _tenant_arg()
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


@bp.post('/saas/channels/messaging')
@require_auth(roles=CHANNEL_WRITE_ROLES)
def channels_messaging():
    """Заявка на альфа-имя SMS/Viber. Регистрацию у DecisionTelecom ведёт
    платформа (менеджер DT), активация = перенос requested_* -> *_sender."""
    tenant = _tenant_arg()
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
    tenant = _tenant_arg()
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
