"""api/monitor.py — JSON-API домена «Монитор и справочники» (агент C6).

Экраны SPA, которые обслуживает этот blueprint (1-в-1 с HTML-страницами борда):
  GET  /api/v1/desk            — ретеншн-пульт (рабочая очередь по задаче/окну)
  GET  /api/v1/live            — «играют сейчас» (текущая сессия; фронт опрашивает polling'ом)
  GET  /api/v1/report          — отчёт отдела (что в работе + приоритеты + офферы)
  GET  /api/v1/signals         — выход модели (топ-200 по приоритету)
  GET  /api/v1/signals/online  — id, активные в потоке сейчас (polling-оверлей вместо SSE)
  GET  /api/v1/schema          — схема данных (4 таблицы ClickHouse)
  GET  /api/v1/formulas        — формулы расчётов (справочная, статич.)
  GET  /api/v1/glossary        — словарь терминов (справочная, статич.)
  GET  /api/v1/keys            — метаданные ключей интеграции + IP-allowlist (super_admin)
  POST /api/v1/keys/regenerate — пересоздать токен (super_admin; новый токен отдаётся 1 раз)
  POST /api/v1/keys/ip/add     — добавить IP/CIDR в allowlist (super_admin)
  POST /api/v1/keys/ip/remove  — убрать IP из allowlist (super_admin)

Принцип волны 2C: НИКАКИХ переписанных SQL/формул — весь расчёт берётся из
`player_board` (тот же SQL, что в HTML-роутах desk()/live()/report()/signals()/
schema()). Здесь только выборка полей и упаковка в JSON (одни данные — одни цифры).

Безопасность:
  • каждый эндпоинт закрыт @require_auth([...]) по матрице ролей (раздел 1 плана);
  • /keys — только super_admin; в списке отдаём МЕТАДАННЫЕ токенов (маска + длина),
    сырой секрет виден только один раз — в ответе на regenerate (момент выдачи).
"""
from __future__ import annotations

import ipaddress
import secrets as _secrets

from flask import Blueprint, request

from .core import require_auth, api_json, current_role, req_locale

import player_board as pb   # готовые helper-функции и SQL борда (q, offer_for, WMAP, ...)

bp = Blueprint('api_monitor', __name__, url_prefix='/api/v1')

# ── роли по разделу 1 плана (согласованы с nav.ts, декларированным B1) ──────────
# desk/report — управление ретеншн-очередью; live — надзор «в моменте»;
# signals — потребители выхода модели; keys — только платформа (мы).
DESK_ROLES = ['super_admin', 'head_retention', 'head_department', 'director']
LIVE_ROLES = ['super_admin', 'head_retention', 'director', 'analyst', 'marketing_manager']
SIGNALS_ROLES = ['super_admin', 'head_retention', 'director', 'risk_officer',
                 'marketing_manager', 'analyst']
KEYS_ROLES = ['super_admin']
# schema/formulas/glossary — справочные: любой аутентифицированный (require_auth()).


# ════════════════════════════════════════════════════════════════════════════
# helpers
# ════════════════════════════════════════════════════════════════════════════
def _offer(p: dict, locale: str = 'ru') -> dict:
    """Реальная акция каталога под игрока (та же pb.offer_for, что в HTML-ячейке).
    locale — язык оператора (X-Locale): каталог акций живёт на бэкенде, поэтому
    название/условия/причину локализует Flask."""
    try:
        name, terms, why = pb.offer_for(p, locale)
    except Exception:
        name, terms, why = ('—', '', '')
    return {'name': name, 'terms': terms, 'why': why}


def _offer_status(code) -> dict | None:
    """Статус оформленного оффера → {code,label,bg,fg} (pb.OFFER_STATUS) или None."""
    meta = pb.OFFER_STATUS.get(code)
    if not meta:
        return None
    label, bg, fg = meta
    return {'code': code, 'label': label, 'bg': bg, 'fg': fg}


def _fnum(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ════════════════════════════════════════════════════════════════════════════
# /desk — ретеншн-пульт (рабочая очередь)
# ════════════════════════════════════════════════════════════════════════════
# фильтры задач по префиксу action (как в desk()); ключи совпадают с pb.ACT_FILTERS
_ACT_WHERE = {
    'SAVE': "startsWith(action,'SAVE')",
    'WINBACK': "startsWith(action,'WINBACK')",
    'NUDGE': "startsWith(action,'NUDGE')",
    'CONVERT': "startsWith(action,'CONVERT')",
    'NURTURE': "startsWith(action,'NURTURE')",
    'all': "action!='наблюдать'",
}


@bp.get('/desk')
@require_auth(DESK_ROLES)
def desk():
    """Рабочая очередь отдела: строки задач по фильтру задачи (act) и окну (w).
    Полный паритет с HTML /desk — тот же SQL, те же приоритеты/офферы."""
    act = request.args.get('act', 'SAVE')
    act = act if act in dict(pb.ACT_FILTERS) else 'SAVE'
    w = request.args.get('w', '14')
    w = w if w in pb.WMAP else '14'
    wd = pb.WMAP[w]
    wlbl = pb.WLBL[w]
    where = _ACT_WHERE[act]
    # VIP-пресет очереди (W2-T4): tier=cd → только «киты» тира C/D
    # (whitelist — иное значение игнорируется). early_tier есть в player_actions
    # (marts.sql:78) и уже отдаётся в каждой строке (early_tier ниже).
    # NB: имя tier_flt, а не tier — ниже tier занят под per-row early_tier в цикле.
    tier_flt = 'cd' if request.args.get('tier') == 'cd' else ''
    if tier_flt == 'cd':
        where += " AND early_tier IN ('C','D')"

    dmax = pb.q("SELECT toDate(max(created_at)) FROM game_transactions")[1][0][0]
    rows = pb.q(f"""SELECT pa.casino_player_id, pa.lifecycle, pa.action, pa.bonus, pa.when_to,
        round(pa.value_try), pa.p_churn, pa.p_2nd_deposit, round(pa.pred_ltv_d90), pa.dep_count, nd.p_next_deposit,
        pa.early_tier, toFloat64(ifNull(pf.net,0))
        FROM player_actions pa LEFT JOIN player_next_deposit_ml nd USING (casino_player_id)
        LEFT JOIN player_features pf USING (casino_player_id)
        WHERE {where} ORDER BY pa.priority DESC, pa.value_try DESC LIMIT 60""")[1]

    ids = [int(r[0]) for r in rows]
    pulse = {}
    if ids:
        idl = ','.join(str(i) for i in ids)
        for cid, rec, rnet, rsp in pb.q(f"""SELECT casino_player_id,
            dateDiff('day', max(toDate(created_at)), toDate('{dmax}')) AS rec,
            round(sumIf(toFloat64(win_amount)-toFloat64(bet_amount), toDate(created_at) > toDate('{dmax}')-{wd})) AS rnet,
            countIf(toDate(created_at) > toDate('{dmax}')-{wd} AND transaction_type IN ('bet','freespins_bet')) AS rsp
            FROM game_transactions WHERE casino_player_id IN ({idl})
              AND transaction_type IN ('bet','freespins_bet','win','freespins_win')
            GROUP BY casino_player_id""")[1]:
            pulse[cid] = (rec, rnet, rsp)
    offst = {r[0]: r[1] for r in pb.q(
        "SELECT casino_player_id, argMax(status,ts) FROM player_offers GROUP BY casino_player_id")[1] if r[1]}
    nq, vq = pb.q(f"SELECT count(), round(sum(value_try)) FROM player_actions WHERE {where}")[1][0]
    nall = pb.q("SELECT countIf(action!='наблюдать'), count() FROM player_actions")[1][0]

    loc = req_locale()
    items = []
    for (pid, lf, a, bonus, when, val, pch, p2, ltv, dc, pnd, tier, pnet) in rows:
        rec, rnet, rsp = pulse.get(pid, (None, 0, 0))
        items.append({
            'player_id': pid, 'lifecycle': lf, 'action': a,
            'when_to': pb.when_to_label(when, loc),   # витрина отдаёт по-русски
            'value_try': val, 'p_churn': pch, 'p_2nd_deposit': p2, 'pred_ltv_d90': ltv,
            'dep_count': dc, 'p_next_deposit': pnd, 'early_tier': tier, 'net': pnet,
            'recency_days': rec, 'recent_net': rnet, 'recent_spins': rsp,
            'offer_status': _offer_status(offst.get(pid)),
            'offer': _offer({'lifecycle': lf, 'dep_count': dc, 'early_tier': tier,
                             'pred_ltv_d90': ltv, 'p_churn': pch, 'net': pnet}, loc),
        })

    return api_json({
        'meta': {'asof': str(dmax), 'act': act, 'w': w, 'window_label': wlbl},
        'filters': {'act': [{'key': k, 'label': lab} for k, lab in pb.ACT_FILTERS],
                    'w': [{'key': k, 'label': lab} for k, lab in pb.WLBL.items()],
                    'tier': tier_flt},
        'kpi': {'n_filter': nq or 0, 'value_filter': vq or 0,
                'n_queue': nall[0] or 0, 'n_total': nall[1] or 0},
        'rows': items,
    })


# ════════════════════════════════════════════════════════════════════════════
# /live — играют сейчас (polling-обновление на фронте)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/live')
@require_auth(LIVE_ROLES)
def live():
    """Текущая сессия каждого активного игрока (окно w минут). Паритет с HTML /live.
    Реалтайм на фронте — polling этого эндпоинта (по умолчанию раз в 20 сек), без SSE."""
    dmaxts = pb.q("SELECT max(created_at) FROM game_transactions")[1][0][0]
    LIVE_WIN = request.args.get('w')
    try:
        LIVE_WIN = int(LIVE_WIN) if LIVE_WIN else 30
    except (TypeError, ValueError):
        LIVE_WIN = 30
    LIVE_WIN = LIVE_WIN if LIVE_WIN in (15, 30, 60, 180) else 30

    n_now = pb.q(f"""SELECT uniqExact(casino_player_id) FROM game_transactions
        WHERE created_at > (SELECT max(created_at) FROM game_transactions) - INTERVAL {LIVE_WIN} MINUTE
          AND transaction_type IN ('bet','freespins_bet')
          AND casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')""")[1][0][0]
    rows = pb.q(f"""SELECT casino_player_id,
        max(send)                       AS last_bet,
        argMax(net, send)               AS cur_net,
        argMax(spins, send)             AS cur_spins,
        argMax(dur, send)               AS cur_dur,
        {pb.GN('argMax(gid, send)')}    AS cur_game
      FROM (
        SELECT casino_player_id, session_id,
          max(created_at) AS send,
          round(dateDiff('second', min(created_at), max(created_at))/60) AS dur,
          countIf(transaction_type IN ('bet','freespins_bet')) AS spins,
          round(sumIf(toFloat64(win_amount)-toFloat64(bet_amount), 1)) AS net,
          argMax(game_uuid, created_at) AS gid
        FROM game_transactions
        WHERE created_at > (SELECT max(created_at) FROM game_transactions) - INTERVAL {LIVE_WIN} MINUTE
          AND transaction_type IN ('bet','freespins_bet','win','freespins_win')
          AND casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')
        GROUP BY casino_player_id, session_id HAVING spins > 0
      )
      GROUP BY casino_player_id ORDER BY last_bet DESC LIMIT 200""")[1]

    ids = [int(r[0]) for r in rows]
    eng = {}
    if ids:
        idl = ','.join(map(str, ids))
        for cid, lf, a, bonus, pch, ltv, dc, pnd in pb.q(f"""SELECT pa.casino_player_id, pa.lifecycle, pa.action, pa.bonus,
            pa.p_churn, round(pa.pred_ltv_d90), pa.dep_count, nd.p_next_deposit
            FROM player_actions pa LEFT JOIN player_next_deposit_ml nd USING (casino_player_id)
            WHERE pa.casino_player_id IN ({idl})""")[1]:
            eng[cid] = (lf, a, bonus, pch, ltv, dc, pnd)

    loc = req_locale()
    items = []
    for cid, last_bet, cur_net, cur_spins, cur_dur, cur_game in rows:
        lf, a, bonus, pch, ltv, dc, pnd = eng.get(cid, (None, None, '—', None, 0, 0, None))
        ltv = ltv or 0
        alert = (cur_net < 0 and ltv >= 10000)              # ценный + проигрывает сейчас
        ago_seconds = (dmaxts - last_bet).total_seconds()
        items.append({
            'alert': bool(alert), 'player_id': cid, 'last_bet': last_bet,
            'ago_seconds': ago_seconds, 'cur_net': cur_net, 'cur_spins': cur_spins,
            'cur_dur': cur_dur, 'cur_game': cur_game, 'lifecycle': lf, 'action': a,
            'p_churn': pch, 'pred_ltv_d90': ltv, 'dep_count': dc, 'p_next_deposit': pnd,
            'offer': _offer({'lifecycle': lf, 'dep_count': dc, 'pred_ltv_d90': ltv,
                             'p_churn': pch, 'net': cur_net}, loc),
        })
    # алерты наверх, далее самые свежие (как в HTML)
    items.sort(key=lambda x: (0 if x['alert'] else 1, -x['last_bet'].timestamp()))
    n_alert = sum(1 for x in items if x['alert'])

    return api_json({
        'meta': {'window_min': LIVE_WIN, 'poll_seconds': 20, 'asof': str(dmaxts)},
        'kpi': {'n_alert': n_alert, 'n_now': n_now or 0, 'shown': len(items)},
        'rows': items,
    })


# ════════════════════════════════════════════════════════════════════════════
# /report — отчёт отдела
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/report')
@require_auth(DESK_ROLES)
def report():
    """Что отдел должен делать (движок) и что уже сделал (офферы). Паритет с HTML /report."""
    qn, qv, qhead = pb.q("SELECT count(), round(sum(value_try)), round(sum(ltv_headroom)) "
                         "FROM player_actions WHERE action!='наблюдать'")[1][0]
    dist = pb.q("SELECT action, count(), round(sum(value_try)), round(avg(priority)) "
                "FROM player_actions WHERE action!='наблюдать' GROUP BY action ORDER BY sum(value_try) DESC")[1]
    topp = pb.q("SELECT pa.casino_player_id, pa.lifecycle, pa.action, round(pa.value_try), pa.p_churn, pa.bonus, "
                "pa.dep_count, pa.early_tier, pa.pred_ltv_d90, toFloat64(ifNull(pf.net,0)) "
                "FROM player_actions pa LEFT JOIN player_features pf USING (casino_player_id) "
                "WHERE pa.action!='наблюдать' ORDER BY pa.priority DESC, pa.value_try DESC LIMIT 12")[1]

    loc = req_locale()
    _bd = pb._bonus_distribution()          # кэш локаль-независим: имена берём из каталога
    bdist = sorted(((pb.bonus_name_for(bid, loc), n, _bd['values'].get(bid, 0))
                    for bid, n in _bd['counts'].items() if _bd['values'].get(bid, 0) > 0),
                   key=lambda x: -x[1])
    sc = pb.q("SELECT s, count() FROM (SELECT casino_player_id, argMax(status,ts) s "
              "FROM player_offers GROUP BY casino_player_id) GROUP BY s")[1]
    by = {s: n for s, n in sc}
    total = sum(by.values())
    log = pb.q("SELECT casino_player_id, argMax(status,ts), argMax(offer_text,ts), argMax(operator,ts), "
               "toString(max(ts)) FROM player_offers GROUP BY casino_player_id ORDER BY max(ts) DESC LIMIT 20")[1]

    task_dist = [{'action': a, 'players': n, 'value': v, 'avg_priority': pr} for a, n, v, pr in dist]
    top_priorities = [{
        'player_id': pid, 'lifecycle': lf, 'action': a, 'value_try': val, 'p_churn': pch,
        'offer': _offer({'lifecycle': lf, 'dep_count': dc, 'early_tier': tier,
                         'pred_ltv_d90': ltv, 'p_churn': pch, 'net': pnet}, loc),
    } for pid, lf, a, val, pch, bonus, dc, tier, ltv, pnet in topp]
    bonus_dist = [{'bonus': str(b), 'players': n, 'value': v} for b, n, v in bdist]
    offer_log = [{'player_id': pid, 'status': st, 'offer_text': txt, 'operator': op, 'ts': ts}
                 for pid, st, txt, op, ts in log]

    return api_json({
        'kpi': {'in_work': qn or 0, 'value_at_risk': qv or 0, 'headroom': qhead or 0,
                'offers_total': total, 'offers_sent': by.get('sent', 0),
                'offers_rejected': by.get('rejected', 0)},
        'task_dist': task_dist,
        'top_priorities': top_priorities,
        'bonus_dist': bonus_dist,
        'offer_log': offer_log,
    })


# ════════════════════════════════════════════════════════════════════════════
# /signals — выход модели (то, что уходит казино)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/signals')
@require_auth(SIGNALS_ROLES)
def signals():
    """Топ-200 по приоритету: LTV/риск/P(деп)/тир/действие/бонус. Паритет с HTML /signals
    (тот же pb._SIG_SQL). Онлайн-оверлей — отдельным эндпоинтом /signals/online (polling)."""
    rows = pb.q(pb._SIG_SQL)[1]
    tot, whales, avgp = pb.q(
        "SELECT count(), countIf(early_tier='D'), toInt64(round(avg(priority))) "
        "FROM player_actions WHERE pred_ltv_d90>0 OR p_churn IS NOT NULL")[1][0]
    acts = pb.q("SELECT action, count() c FROM player_actions WHERE (pred_ltv_d90>0 OR p_churn IS NOT NULL) "
                "AND action!='' GROUP BY action ORDER BY c DESC LIMIT 1")[1]
    top_action = acts[0][0] if acts else '—'

    loc = req_locale()   # bonus витрина отдаёт по-русски → переводим
    items = [{
        'player_id': pid, 'pred_ltv_d90': ltv, 'p_churn': pch, 'p_2nd_deposit': p2,
        'early_tier': tier, 'action': action, 'bonus': pb.bonus_label(bonus, loc),
        'priority': prio,
    } for pid, ltv, pch, p2, tier, action, bonus, prio in rows]

    return api_json({
        'kpi': {'total': tot or 0, 'whales': whales or 0, 'avg_priority': avgp or 0,
                'top_action': top_action},
        'rows': items,
    })


@bp.get('/signals/online')
@require_auth(SIGNALS_ROLES)
def signals_online():
    """id игроков, активных в потоке за последние 3 минуты (polling-замена SSE /signals/stream)."""
    try:
        ids = [int(r[0]) for r in pb.q(
            "SELECT DISTINCT casino_player_id FROM live_events "
            "WHERE ts > now64(3) - toIntervalMinute(3) LIMIT 5000")[1]]
    except Exception:
        ids = []
    return api_json({'online': ids})


# ════════════════════════════════════════════════════════════════════════════
# /schema — схема данных (4 таблицы)
# ════════════════════════════════════════════════════════════════════════════
_SCHEMA_TABS = [('users', 'справочник игроков · 1 строка = игрок'),
                ('money_transactions', 'депозиты, выводы, бонусы'),
                ('game_sessions', 'игровые сессии'),
                ('game_transactions', 'каждая ставка и выигрыш')]
_SCHEMA_PK = {('users', 'casino_player_id'), ('game_sessions', 'session_id')}
_SCHEMA_FK = {('game_sessions', 'casino_player_id'), ('money_transactions', 'casino_player_id'),
              ('game_transactions', 'casino_player_id'), ('game_transactions', 'session_id')}


@bp.get('/schema')
@require_auth()
def schema():
    """Структура и связи 4 таблиц ClickHouse (live-счётчики строк). Паритет с HTML /schema."""
    tables = []
    for t, role in _SCHEMA_TABS:
        n = pb.q(f"SELECT sum(rows) FROM system.parts WHERE database='retention' AND table='{t}' AND active")[1][0][0] or 0
        cols = [r[0] for r in pb.q(
            f"SELECT name FROM system.columns WHERE database='retention' AND table='{t}' ORDER BY position")[1]]
        columns = [{'name': c,
                    'kind': 'pk' if (t, c) in _SCHEMA_PK else ('fk' if (t, c) in _SCHEMA_FK else 'col')}
                   for c in cols]
        # cols_count — счётчик колонок для подписи «{role} · N колонок» (борд player_board.py:3090)
        tables.append({'name': t, 'role': role, 'rows': int(n),
                       'cols_count': len(cols), 'columns': columns})
    relations = ("Все таблицы связаны через casino_player_id (users → события, связь 1:N · "
                 "синим PK, индиго FK). Дополнительно session_id сшивает game_transactions "
                 "с game_sessions.")
    return api_json({'tables': tables, 'relations': relations})


# ════════════════════════════════════════════════════════════════════════════
# /formulas — формулы расчётов (справочная, статич.; текст 1-в-1 с HTML /formulas)
# ════════════════════════════════════════════════════════════════════════════
def _T(v):    # текстовая ячейка
    return {'code': False, 'text': v}


def _C(v):    # ячейка-формула (моноширинный «код»)
    return {'code': True, 'text': v}


_FORMULA_SECTIONS = [
    {'title': '1. Базовые агрегаты игрока (player_features)', 'cols': ['Метрика', 'Формула', 'Смысл'], 'rows': [
        [_T('turnover (оборот)'), _C('Σ bet_amount'), _T('сколько поставил')],
        [_T('net'), _C('wins_sum − turnover'), _T('+ в плюсе / − слил (со стороны игрока)')],
        [_T('recency_days'), _C("dateDiff('day', last_bet, today())"), _T('дней с последней ставки')],
        [_T('freespin_ratio'), _C('freespins_bets / bets'), _T('доля фриспин-ставок')],
        [_T('night_share'), _C('night_bets / bets'), _T('доля ночной игры (час<6)')],
        [_T('bets_per_active_day'), _C('bets / active_days'), _T('интенсивность')],
        [_T('lifecycle'), _C('recency: ≤7 active · ≤30 cooling · ≤60 at_risk · ≤90 dormant · >90 churned'), _T('стадия')],
        [_T('is_depositor (борд)'), _C('dep_count > 0'), _T('реальный депозитор')],
    ]},
    {'title': '2. Экономика / KPI (/overview)', 'cols': ['Метрика', 'Формула'], 'rows': [
        [_T('GGR (доход казино)'), _C('Σ bet − Σ win')],
        [_T('RTP'), _C('Σ win / Σ bet × 100%')],
        [_T('Hold'), _C('GGR / Σ bet × 100%')],
        [_T('Кэш-нетто'), _C('депозиты(авто) − выводы(авто)')],
    ]},
    {'title': '3. LTV (ценность игрока)', 'cols': ['Что', 'Формула'], 'rows': [
        [_T('Кривая (реализ.)'), _C('avg(Σ dep в [0,H] дн от FTD) по дозревшим (age ≥ H)')],
        [_T('LTV ML (таргет)'), _C('Σ dep в [0,90] от FTD; обучение на log1p, фичи только 1-й недели')],
        [_T('Квантили'), _C('******** Quantile(α=0.1/0.5/0.9) → P10/P50/P90')],
        [_T('Headroom'), _C('max(pred_ltv_d90 − dep_to_date, 0)')],
    ]},
    {'title': '4. Депозиты и churn', 'cols': ['Что', 'Формула'], 'rows': [
        [_T('Конверсия #N→#N+1'), _C('count(n≥N+1) / count(n≥N)')],
        [_T('P(2-й деп, 30д) ML'), _C('таргет: ≥2 деп в 30 дн от FTD; фичи только FTD-дня (без утечки)')],
        [_T('P(следующий деп)'), _C('таргет: депозит #k+1 в 30 дн; фичи на момент депозита #k')],
        [_T('Churn (риск ухода)'), _C('срез T → нет ставки в (T, T+30]; фичи строго created_at < T')],
        [_T('Личный ритм'), _C('expected_gap = span/(active_days−1), просрочка = recency/expected_gap')],
    ]},
    {'title': '5. Движок офферов (player_actions)', 'cols': ['Что', 'Формула'], 'rows': [
        [_T('value_try (ценность)'), _C('депозитор ? max(pred_ltv_d90, dep_sum) : 0')],
        [_T('save_weight (вес стадии)'), _C('active .30 · cooling .70 · at_risk 1.0 · dormant .55 · churned .35')],
        [_T('priority (приоритет)'), _C('round( value_try × coalesce(p_churn, save_weight) )')],
        [_T('action'), _C('CONVERT · NUDGE · SAVE · WINBACK · NURTURE по lifecycle/депозитам')],
        [_T('bonus'), _C('freespin>0.4→фриспины · тир C/D или avg_bet≥200→VIP · ≤1 деп→релоад')],
    ]},
    {'title': '6. Сессии (реконструкция)', 'cols': ['Метрика', 'Формула'], 'rows': [
        [_T('Длительность'), _C("round( dateDiff('second', min, max) / 60 ) мин")],
        [_T('Net сессии'), _C('Σ win − Σ bet → 🟢/🔴')],
        [_T('Моментум'), _C('recent_net = Σ net за окно (7/14/30/90/всё)')],
        [_T('Live-алерт'), _C('pred_ltv_d90 ≥ 10000 AND net_сессии < 0')],
    ]},
    {'title': '7. Распределения / бонусы / RFM', 'cols': ['Что', 'Формула'], 'rows': [
        [_T('Дециль LTV'), _C('11 − ntile(10) OVER (ORDER BY pred_ltv_d90) (D1 = топ-10%)')],
        [_T('Доля ценности'), _C('Σ LTV(дециль) / Σ LTV(все) × 100%')],
        [_T('Перцентиль деп.'), _C('quantile(p)(dep_sum)')],
        [_T('Бонус: отклик'), _C('% событий с депозитом в (бонус, +14д]')],
        [_T('Uplift ATT'), _C('mean(retained_treated − retained_control) по propensity-парам, CI бутстрэп')],
        [_T('RFM'), _C('R = 6−ntile(5)(recency) · F = ntile(5)(active_days) · M = ntile(5)(turnover)')],
    ]},
]

_FORMULA_NOTE = ('⚠️ модели калиброваны на ранжирование, не на абсолютную вероятность — для '
                 'приоритизации. Поля от today() (recency/lifecycle) замораживаются на дату сборки витрины.')


@bp.get('/formulas')
@require_auth()
def formulas():
    """Все вычисления системы по слоям (справочная страница). Паритет с HTML /formulas."""
    return api_json({
        'lead': ('все вычисления системы по слоям · условные: bet=ставка, dep=завершённый депозит, '
                 'FTD=первый депозит, всё по account_type=normal'),
        'sections': _FORMULA_SECTIONS,
        'note': _FORMULA_NOTE,
    })


# ════════════════════════════════════════════════════════════════════════════
# /glossary — словарь терминов (справочная, статич.; текст 1-в-1 с HTML /glossary)
# ════════════════════════════════════════════════════════════════════════════
_GLOSSARY_SECTIONS = [
    {'title': '💰 Экономика / деньги', 'rows': [
        ('Ставка (bet)', 'оборот / turnover', 'сколько игрок поставил В ИГРЕ (за спин/кон). Сумма всех ставок = оборот'),
        ('Выигрыш (win)', '', 'сколько игра ВЕРНУЛА игроку на игровой баланс (можно снова ставить)'),
        ('GGR', 'Gross Gaming Revenue', 'доход казино от игры = все ставки − все выигрыши'),
        ('RTP', 'Return To Player', 'какой % ставок вернулся игрокам выигрышами'),
        ('Hold', 'удержание', 'доля оборота, осевшая у казино (100% − RTP)'),
        ('Депозит', '', 'игрок занёс деньги НА СЧЁТ (вход денег — другая таблица, не ставка!)'),
        ('Вывод', '', 'игрок снял деньги СО СЧЁТА (выход денег)'),
        ('Кэш-нетто', '', 'реальные деньги: депозиты − выводы'),
        ('FTD', 'First Time Deposit', 'самый первый депозит игрока'),
        ('Депозитор', '', 'игрок, сделавший хотя бы один депозит'),
        ('NGR', 'Net Gaming Revenue', 'GGR минус расходы: бонусы, провайдеры, комиссия аффилиатов'),
        ('Net Profit', 'касса', 'депозиты − выводы. Это движение реальных денег, а не игровая маржа'),
        ('Депозиты (кэш)', '', 'только реальные пополнения игроком, без ручных начислений'),
        ('Депозиты (вкл. ручные)', '', 'кэш плюс ручные начисления оператора (по сути бонус) — поведенческий показатель'),
        ('Ручные списания', 'manual', 'отмена бонусных выигрышей и сгоревшие бонусы. Это НЕ выплата игроку, в выводы не входит'),
        ('Платёжное трение', '', 'насколько тяжело игроку пополнить счёт: были ли отказы платёжек и сколько'),
    ], 'banner': ('⚠️ Не путать! Ставка / выигрыш — это про ИГРУ (сколько поставил и сколько игра вернула). '
                  'Депозит / вывод — про ДЕНЬГИ НА СЧЁТЕ (занёс / снял). Один депозит можно проставить много раз → '
                  'оборот в разы больше депозитов (у нас ставки 343 млн против депозитов 30 млн — деньги крутятся по кругу).')},
    {'title': '🎯 Игрок и ценность', 'rows': [
        ('LTV', 'Lifetime Value', 'прогноз: сколько игрок принесёт депозитами (у нас — за 90 дней)'),
        ('Net', 'чистый результат', 'выигрыши − ставки игрока (+ в плюсе / − слил казино)'),
        ('Recency', 'давность', 'сколько дней прошло с последней ставки'),
        ('Headroom / «ещё ожидаем»', '', 'сколько игрок ещё внесёт сверх уже внесённого'),
        ('Churn', 'отток', 'уход игрока — перестал играть'),
        ('Lifecycle', 'жизненный цикл', 'стадия по дням с последней ставки: активен ≤7 дн · остывает 8–30 · под риском 31–60 · спящий 61–90 · отток 90+ · не играл — ставок не было'),
        ('VIP', '', 'самые ценные / крупные игроки'),
        ('Активация, дн', '', 'сколько дней прошло от регистрации до первой ставки. Чем меньше, тем лучше зашёл трафик'),
        ('Импульс', '', 'как игрок идёт прямо сейчас: выиграл или проиграл и сколько спинов сделал за выбранный период'),
        ('Тир A/B/C/D', 'tier', 'группа по депозиту 1-й недели: A <1k · B 1–3k · C 3–10k · D 10k+ (кит)'),
    ]},
    {'title': '🧩 Сегменты (RFM)', 'rows': [
        ('RFM', 'Recency · Frequency · Monetary', 'сегментация по 3 осям: давность · частота · деньги'),
        ('R / F / M', '', 'баллы 1–5 по каждой оси (квинтили). У Recency: недавно = 5'),
        ('Champions', '', 'недавно + часто + много → беречь, VIP'),
        ('Loyal', '', 'стабильное ядро'),
        ('Cant-Lose-Them', '', 'ценные, но пропали → срочно вернуть'),
        ('At-Risk / Hibernating', '', 'уходят / давно не играли'),
    ]},
    {'title': '📈 Прогнозы и горизонты', 'rows': [
        ('D1 / D7 / D30 / D90 / D120', '', 'день 1 / 7 / 30 / 90 / 120 от первого депозита'),
        ('P(2-й деп, 30д)', 'probability', 'вероятность, что игрок сделает 2-й депозит за 30 дней'),
        ('P(след. деп)', '', 'вероятность дойти до следующего депозита'),
        ('Риск ухода (30д)', 'p_churn', 'вероятность, что игрок уйдёт в ближайшие 30 дней'),
        ('P10 / P50 / P90', 'перцентили', 'P50 = медиана (типичный). P90 = только 10% выше этого'),
        ('Дециль', '', 'база делится на 10 равных групп; D1 = топ-10%'),
    ]},
    {'title': '🤖 Модели и качество', 'rows': [
        ('ML', 'Machine Learning', 'модель учится на данных и предсказывает'),
        ('********', '', 'алгоритм ML, который мы используем (для таблиц лучший)'),
        ('AUC', 'площадь под ROC', 'качество «да/нет»: 0.5 угадайка · 0.7–0.8 хорошо · 0.9+ супер'),
        ('Spearman', 'ранговая корреляция', 'насколько верно модель СОРТИРУЕТ (0 случайно, 1 идеал)'),
        ('Калибровка', '', 'насколько «70%» реально означает 70%'),
        ('Point-in-time', 'срез на дату', 'фичи «как было на дату T» — чтобы не подсмотреть будущее (без утечки)'),
    ]},
    {'title': '🧪 Статистика (эффект бонуса)', 'rows': [
        ('Uplift', 'добавка', 'сколько действие (бонус) реально ДОБАВИЛО сверх «и так бы было»'),
        ('ATT', 'средний эффект на получивших', 'честная добавка после поправки на отбор'),
        ('CI', 'доверительный интервал', 'диапазон, где истинное значение с вероятностью 95%'),
        ('Propensity-matching', 'подбор похожих', 'сравниваем похожих игроков с бонусом и без — для честного эффекта'),
        ('п.п.', 'процентных пункта', 'разница в процентах (с 60% до 63% = +3 п.п.)'),
    ]},
]


@bp.get('/glossary')
@require_auth()
def glossary():
    """Что значит каждое сокращение на дашборде — простыми словами. Паритет с HTML /glossary."""
    sections = [{'title': s['title'],
                 'rows': [{'term': t, 'full': full, 'plain': plain} for t, full, plain in s['rows']],
                 'banner': s.get('banner')}
                for s in _GLOSSARY_SECTIONS]
    return api_json({'sections': sections})


# ════════════════════════════════════════════════════════════════════════════
# /keys — ключи интеграции (super_admin). Секреты НЕ отдаём в открытую.
# ════════════════════════════════════════════════════════════════════════════
_INGEST_URL = 'https://cas.21do.xyz/ingest/events'
_CURL_EXAMPLE = (
    'curl -X POST https://cas.21do.xyz/ingest/events \\\n'
    '  -H "Authorization: Bearer <токен>" -H "Content-Type: application/json" \\\n'
    '  -d \'{"event_id":"...","event_type":"bet","casino_player_id":40,"ts":"...","bet_amount":5,"currency":"TRY"}\''
)
_KAFKA_NOTE = ('⚠️ Kafka-креды (SASL) меняются скриптом create_producer.sh на сервере — не из UI.')


def _mask_token(val: str) -> str:
    """Маска секрета для списка: показываем только хвост (4 символа)."""
    if not val:
        return ''
    s = str(val)
    return f"••••{s[-4:]}" if len(s) >= 4 else '••••'


def _keys_payload() -> dict:
    toks = pb._load_tokens()
    tokens = []
    for k, label in pb.TOKEN_LABELS.items():
        val = toks.get(k, '') or ''
        tokens.append({'key': k, 'label': label, 'is_set': bool(val),
                       'masked': _mask_token(val), 'length': len(val)})
    return {
        'tokens': tokens,
        'ips': pb._load_ips(),
        'ingest': {'url': _INGEST_URL, 'example_curl': _CURL_EXAMPLE},
        'kafka_note': _KAFKA_NOTE,
    }


@bp.get('/keys')
@require_auth(KEYS_ROLES)
def keys():
    """МЕТАДАННЫЕ HTTP-токенов (маска + длина, без сырого секрета) + IP-allowlist."""
    return api_json(_keys_payload())


@bp.post('/keys/regenerate')
@require_auth(KEYS_ROLES)
def keys_regenerate():
    """Пересоздать токен. Новый секрет отдаётся ОДИН раз (момент выдачи), далее — только маска.
    Тело: {"which": "ingest_prod"|"ingest_test"}."""
    body = request.get_json(silent=True) or {}
    which = str(body.get('which', ''))
    if which not in pb.TOKEN_LABELS:
        return api_json(error='unknown token key', code=400)
    toks = pb._load_tokens()
    new_token = _secrets.token_urlsafe(24)
    toks[which] = new_token
    try:
        pb._save_tokens(toks)
    except Exception as e:
        return api_json(error=f'не удалось сохранить токен: {e}', code=503)
    return api_json({'key': which, 'label': pb.TOKEN_LABELS[which],
                     'token': new_token, 'masked': _mask_token(new_token)})


@bp.post('/keys/ip/add')
@require_auth(KEYS_ROLES)
def keys_ip_add():
    """Добавить IP/CIDR в allowlist приёма событий. Тело: {"ip": "57.129.125.90"|"10.0.0.0/24"}."""
    body = request.get_json(silent=True) or {}
    ip = str(body.get('ip', '') or '').strip()
    try:
        ipaddress.ip_network(ip, strict=False)
    except Exception:
        return api_json(error='некорректный IP или CIDR', code=400)
    ips = pb._load_ips()
    if ip not in ips:
        ips.append(ip)
        try:
            pb._save_ips(ips)
        except Exception as e:
            return api_json(error=f'не удалось сохранить список: {e}', code=503)
    return api_json({'ips': pb._load_ips()})


@bp.post('/keys/ip/remove')
@require_auth(KEYS_ROLES)
def keys_ip_remove():
    """Убрать IP из allowlist. Тело: {"ip": "..."}."""
    body = request.get_json(silent=True) or {}
    ip = str(body.get('ip', '') or '').strip()
    ips = [x for x in pb._load_ips() if x != ip]
    try:
        pb._save_ips(ips)
    except Exception as e:
        return api_json(error=f'не удалось сохранить список: {e}', code=503)
    return api_json({'ips': pb._load_ips()})


# ════════════════════════════════════════════════════════════════════════════
# VIP-риск: очередь «риск × перспективность» (инхаус vip-intelligence)
# ════════════════════════════════════════════════════════════════════════════
_TIER = {0: 'Regular', 1: 'Silver', 2: 'Gold', 3: 'Platinum', 4: 'Diamond', 5: 'Royal'}
# p_non_promising ≤ 0.9 — «перспективный» (нижние децили растут в тире ×8.4 чаще базы)
_GROWTH_PROMISING = 0.90


@bp.get('/vip-risk')
@require_auth(DESK_ROLES)
def vip_risk():
    """Очередь VIP-риска (use case «удержание с приоритизацией», sellrise_docs):
    активные VIP по убыванию риска депозитного оттока (30д, vip_churn). Матрица:
    высокий риск + перспективный (или Platinum+ — расти некуда, ценность высокая)
    → менеджер; высокий риск + бесперспективный (non_promising) → автокампания.
    LEFT JOIN в ClickHouse заполняет пропуски нулями, поэтому «нет скора роста»
    детектится по np-ключу, а не по значению."""
    rows = pb.q(
        "WITH lv AS ("
        "  SELECT casino_player_id,"
        "    round(sumIf(amount, type='deposit' AND status IN ('completed','approved','success')"
        "          AND currency='TRY'), 0) AS cum_try,"
        "    round(maxIf(amount, type='deposit' AND status IN ('completed','approved','success')"
        "          AND currency='TRY'), 0) AS max_try,"
        "    dateDiff('day', maxIf(toDate(created_at), type IN ('deposit','manual_deposit')"
        "          AND status='completed'), today()) AS dep_recency"
        "  FROM money_transactions"
        "  WHERE casino_player_id IN (SELECT casino_player_id FROM player_vip_churn_ml)"
        "  GROUP BY casino_player_id)"
        " SELECT vc.casino_player_id, round(vc.p_vip_churn, 3) AS risk,"
        "  if(np.casino_player_id = 0, NULL, round(np.p_non_promising, 3)) AS npv,"
        "  lv.cum_try, lv.dep_recency,"
        "  multiIf(lv.max_try < 100 OR lv.cum_try < 100, 0, lv.cum_try >= 1000000, 5,"
        "          lv.cum_try >= 500000, 4, lv.cum_try >= 150000, 3, lv.cum_try >= 50000, 2, 1) AS lvl,"
        "  f.recency_days, f.dep_count"
        " FROM player_vip_churn_ml vc"
        " LEFT JOIN player_non_promising_vip_ml np ON np.casino_player_id = vc.casino_player_id"
        " LEFT JOIN lv ON lv.casino_player_id = vc.casino_player_id"
        " LEFT JOIN player_features f ON f.casino_player_id = vc.casino_player_id"
        " ORDER BY vc.p_vip_churn DESC")[1]

    # Бакетируем по ВСЕЙ популяции (1.3k строк — дёшево): глобальный топ по риску
    # забит мелкими бесперспективными Silver, и менеджерская очередь была бы пустой.
    items = []
    counts = {'manager': 0, 'auto': 0}
    for pid, risk, npv, cum, dep_rec, lvl, rec_days, dep_count in rows:
        promising = None if npv is None else float(npv) <= _GROWTH_PROMISING
        reco = 'manager' if promising in (None, True) else 'auto'
        counts[reco] += 1
        items.append({
            'player_id': int(pid),
            'risk': float(risk),
            'growth': round(1 - float(npv), 3) if npv is not None else None,
            'promising': promising,          # None = Platinum+ (модель роста не про них)
            'vip_level': int(lvl),
            'tier': _TIER.get(int(lvl), '—'),
            'cum_try': float(cum or 0),
            'dep_recency': int(dep_rec) if dep_rec is not None else None,
            'recency_days': int(rec_days) if rec_days is not None else None,
            'dep_count': int(dep_count or 0),
            'reco': reco,
        })
    # два бакета, каждый — свой топ по риску (вторично — по накопленному: при
    # равном риске сначала более ценный)
    key = lambda r: (-r['risk'], -r['cum_try'])   # noqa: E731
    manager = sorted((r for r in items if r['reco'] == 'manager'), key=key)[:100]
    auto = sorted((r for r in items if r['reco'] == 'auto'), key=key)[:100]
    return api_json({'manager': manager, 'auto': auto,
                     'total_scored': len(items),
                     'manager_count': counts['manager'], 'auto_count': counts['auto']})


# ════════════════════════════════════════════════════════════════════════════
# Свежесть данных (бейдж в шапке SPA): дыру потока не путать с «игрок молчит»
# ════════════════════════════════════════════════════════════════════════════
_FRESHNESS_CACHE: dict = {'ts': 0.0, 'data': None}
_FRESHNESS_TTL = 300   # сек; max() по 60M строк дёшев, но дёргается каждым экраном


@bp.get('/meta/freshness')
@require_auth()
def meta_freshness():
    """До какого момента дозагружены деньги/игра (Стамбул, +3 к UTC-хранению —
    тот же принцип, что в карточных эндпоинтах). Любая аутентифицированная роль."""
    import datetime as _dt
    import time as _time
    now = _time.monotonic()
    if _FRESHNESS_CACHE['data'] and now - _FRESHNESS_CACHE['ts'] < _FRESHNESS_TTL:
        return api_json(_FRESHNESS_CACHE['data'])

    def _ist(s):
        try:
            return (_dt.datetime.fromisoformat(str(s).split('.')[0])
                    + _dt.timedelta(hours=3)).strftime('%d.%m.%Y %H:%M')
        except Exception:
            return None

    money, game = pb.q(
        "SELECT toString(max(created_at)), "
        "(SELECT toString(max(created_at)) FROM game_transactions) "
        "FROM money_transactions")[1][0]
    data = {'money_until': _ist(money), 'game_until': _ist(game)}
    _FRESHNESS_CACHE.update(ts=now, data=data)
    return api_json(data)
