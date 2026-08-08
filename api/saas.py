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
                  'snippet_connected': snippet_events > 0,
                  'channels_connected': _any_channel_active(tenant),
                  'offers_ready': _offers_step_done(tenant),
                  'autopilot': _autopilot_resolved(_campaigns_conf(tenant), tenant)},
    })


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

    snippet_html = (
        f'<script src="https://{host}/snippet/ra.js"\n'
        f'        data-endpoint="https://{host}/ingest/saas/events"\n'
        f'        data-token="{token}" data-tenant="{tenant}"></script>'
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

    ch = _ch_direct()
    prev = kb.load(ch, tenant, 'brief')
    prev_snapshot = {**(prev.get('analysis') or {}),
                     'plans': (prev.get('facts') or {}).get('plans') or []}
    now_snapshot = {**brief, 'plans': facts.get('plans') or []}
    changes = diff_briefs(prev_snapshot, now_snapshot) if prev else []

    answers = tc.get('onboarding_answers') or {}
    prefill = answers_from_brief(brief, facts)
    econ = build_economics(facts.get('plans') or [], {**prefill, **answers})

    if facts or brief:
        # ЗНАНИЕ - в своё хранилище с версиями (секреты туда не попадают),
        # факты дополнительно в конфиг: их читают промпты офферов и текстов.
        kb.save(ch, tenant, 'brief',
                {'version': BRIEF_VERSION, 'site_url': url,
                 'facts': facts, 'analysis': brief, 'pages': visited}, url)
        kb.save(ch, tenant, 'economics', econ, url)
        ca.update_tenant(tenant, {'site_profile': facts,
                                  'site_scanned_pages': visited})
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

    avg_price = _avg_plan_price(tenant) or float(answers.get('avg_plan_price') or 0)
    base = compose_offers(answers, avg_price)

    # контекст с сайта клиента (аудитория, момент ценности, тарифы) - в промпты
    site = (ca.load_tenants().get(tenant, {}) or {}).get('site_profile') or {}
    if site:
        answers = {**answers, 'site_profile': site}

    ai_note = 'ai_not_configured'
    ai_offers = []
    if _ai_enabled():
        from stripe_sync.ai_compose import ai_compose
        ai_offers, ai_note = ai_compose(answers, avg_price)

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
        ai_map, note = ai_compose_copy(answers)
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
@require_auth(roles=LEAK_ROLES)
def saas_users():
    """Список юзеров SaaS-контура: identity + стадия + действие + скоры.
    ?stage=DUNNING - фильтр; сортировка: ценность на кону, затем MRR."""
    tenant = _tenant_arg()
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
               if(toUnixTimestamp(last_seen) = 0, '', toString(last_seen)),
               stage_note
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
    } for r in rows]

    stages = {r[0]: int(r[1]) for r in q(
        "SELECT stage, count() FROM user_actions WHERE tenant_id = {t:String} GROUP BY stage",
        {'t': tenant})[1]}

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
                     'demo': demo})


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
                         'number': str(tch.get('wa_personal_number') or '')},
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

    return api_json({'tenant': tenant, 'insights': insights,
                     'cancel_reasons': reasons})


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
    return ovr.merge_campaign_conf(conf, ovr.load_tenant(tenant))


def _autopilot_resolved(conf: dict, tenant: str) -> bool:
    tc = ca.load_tenants().get(tenant, {}) or {}
    if 'autopilot' in tc:
        return bool(tc['autopilot'])
    return bool(conf.get('autopilot'))


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
    } for c in conf.get('campaigns', [])]

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
    return api_json(_campaigns_payload(tenant))


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
    if kind in ('supabase', 'json') and not cfg['url']:
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
    composed = compose_offers(answers, avg_price) if answers else []

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
@require_auth(roles=LEAK_ROLES)
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
@require_auth(roles=LEAK_ROLES)
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
@require_auth(roles=CHANNEL_WRITE_ROLES)
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
