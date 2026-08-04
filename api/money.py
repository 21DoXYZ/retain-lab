"""api/money.py — JSON-домен «Деньги и доход» (агент C1).

Экраны SPA: /overview, /ggr (8 табов + фильтры + дельты), /analytics (#cash), /audit.

Принцип C-агента (SPA_BUILD_PLAN.md, Волна 2C): данные экрана выносятся в JSON,
переиспользуя СУЩЕСТВУЮЩИЕ SQL/формулы player_board.py. Финансовые формулы НЕ
переписываются — импортируются helper-функции и константы борда
(q, _ggr_kpis, provider_cost_total, affiliate_commission_total, calc_ngr, GGR_TABS,
DEP_OK/WD_OK/BONUS_OK/BET_T/WIN_T/GSUCCESS/NRM, CAT, GN, …). Каждый эндпоинт
выполняет ТОТ ЖЕ запрос, что и HTML-роут борда, — значит цифры 1-в-1 (паритет V5).

Регистрация: пакет `api/` (ядро A3) авто-подхватывает модуль по переменной `bp`.
Ядро (api/core.py) и player_board.py править НЕ нужно.

── NAV-декларация (nav.ts принадлежит A2/B1, здесь только фиксируем связь экран→роут) ──
  overview  → /overview            → GET /api/v1/money/overview
  ggr       → /ggr                 → GET /api/v1/ggr
  cash      → /analytics#cash      → GET /api/v1/money/cash
  risk      → /audit               → GET /api/v1/audit
Пункты меню уже объявлены в crm-spa/components/ui/nav.ts (группа «Деньги и риск» +
«Аналитика»); ролевые списки там совпадают с require_auth ниже.
"""
from __future__ import annotations

import re
import datetime as _dt
from datetime import date as _date, timedelta

from flask import Blueprint, request

from .core import require_auth, api_json, req_locale
from .i18n_catalog import loc, loc_deep   # перевод каталога по X-Locale

# ── helper-функции и константы борда (единый источник формул) ────────────────────
from player_board import (
    q, GN, escape, CH_DB,
    GSUCCESS, BET_T, WIN_T, DEP_OK, WD_OK, BONUS_OK, SUCCESS, NRM,
    provider_cost_total, affiliate_commission_total, calc_ngr,
    _ggr_kpis, GGR_TABS, data_asof, CAT,
)

bp = Blueprint('api_money', __name__, url_prefix='/api/v1')

# ── ролевые матрицы (SPA_BUILD_PLAN.md §1) ───────────────────────────────────────
# «Деньги казино» (обзор + GGR/NGR) — БЕЗ marketing_manager: маркетингу положена
# бонус-экономика/LTV/сегментация, но НЕ казино-GGR (матрица §1, роль 8).
CASINO_MONEY_ROLES = ['director', 'finance', 'analyst', 'head_retention', 'super_admin']
# Аналитика денежных потоков (#cash: удержание/RFM/cashflow) — маркетингу нужна.
MONEY_ROLES = ['director', 'finance', 'analyst', 'marketing_manager',
               'head_retention', 'super_admin']
AUDIT_ROLES = ['director', 'finance', 'risk_officer', 'head_retention', 'super_admin']


def _flt(x) -> float:
    """None/NaN-safe float (как round(...) в борде отдаёт 0 при пусто)."""
    try:
        v = float(x or 0)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


def _delta(cur, prev):
    """Дельта к прошлому периоду — 1-в-1 с dlt() борда: (cur-prev)/|prev|*100, 1dp.
    Возвращает {pct, tone} либо None (когда prev == 0/None — как ''-ветка в борде)."""
    if not prev:
        return None
    pct = round((cur - prev) / abs(prev) * 100, 1)
    return {'pct': pct, 'tone': 'pos' if pct >= 0 else 'neg'}


# ════════════════════════════════════════════════════════════════════════════════
# GET /api/v1/money/overview — экран «Обзор» (роут overview() борда)
# ════════════════════════════════════════════════════════════════════════════════
@bp.get('/money/overview')
@require_auth(roles=CASINO_MONEY_ROLES)
def money_overview():
    """KPI обзора за ВЫБРАННЫЙ период (?from&to, дефолт 30 дней — как GGR).

    Деньги/игра/NGR считаются тем же _ggr_kpis, что и страница GGR → цифры
    совпадают 1-в-1 (раньше Обзор был за всё время, а GGR за период — отсюда
    расхождение NGR). Счётчики игроков (всего/активные/VIP-риск) — снимок
    ТЕКУЩЕГО состояния из витрины: их нельзя пересчитать «на прошлую дату», и
    в ответе помечены as-of, чтобы не путать с деньгами за период.
    """
    # окно дат (валидируется _vd, дефолт последние 30 дней) — как в _ggr_filters
    dmax = data_asof()
    if isinstance(dmax, _dt.datetime):
        dmax = dmax.date()
    elif isinstance(dmax, str):
        dmax = _dt.date.fromisoformat(dmax[:10])
    frm = _vd(request.args.get('from'), str(dmax - timedelta(days=29)))
    to = _vd(request.args.get('to'), str(dmax))

    def dwin(fr, t):
        return f"toDate(toTimezone(created_at,'Europe/Istanbul')) BETWEEN '{fr}' AND '{t}'"

    def _period_money(fr, t):
        """Все денежные/игровые KPI за окно [fr..t]. Вынесено, чтобы посчитать и
        основной период, и период сравнения одной и той же логикой (0.2)."""
        dwl = dwin(fr, t)
        gwl = f"{GSUCCESS} AND currency='TRY' AND {NRM} AND {dwl}"
        mwl = f"{NRM} AND {dwl}"
        kk = _ggr_kpis(gwl, mwl, dwl, NRM, dwl)   # игра + NGR + издержки (как GGR-страница)
        d, w, mw_, _dm, drej = (_flt(x) for x in q(f"""SELECT
           round(sumIf(amount, {DEP_OK} AND {dwl})),
           round(sumIf(abs(amount), {WD_OK} AND {dwl})),
           round(sumIf(amount, type='manual_withdrawal' AND {SUCCESS} AND {dwl})),
           round(sumIf(amount, type='manual_deposit' AND {SUCCESS} AND {dwl})),
           round(sumIf(amount, type='deposit' AND status IN ('rejected','failed') AND {dwl}))
           FROM money_transactions WHERE {NRM}""")[1][0])
        nc = d - w
        return {
            'cash': {'deposits': d, 'withdrawals': w, 'net_cash': nc,
                     'margin': round(nc / d * 100, 1) if d else 0,
                     # ratio выводы/депозиты (Д3, «ключевая метрика здоровья по гео»):
                     # сколько % внесённого утекает обратно. >~67% — тревожно, у Tier-3
                     # ~70%, при выше — гео убыточно (порог Василия).
                     'wd_dep_ratio': round(w / d * 100, 1) if d else 0,
                     'bonus_cost': kk['bonus'], 'bonus_ratio': kk['bratio']},
            'game': {'ggr': kk['ggr'], 'rtp': kk['rtp'], 'bets': kk['bet'], 'wins': kk['win'],
                     'hold': round(kk['ggr'] / kk['bet'] * 100, 2) if kk['bet'] else 0},
            'ngr': {'ngr': kk['ngr'], 'provider_cost': kk['pcost'],
                    'affiliate_commission': kk['affc'], 'bonus_usage': kk['bonus'],
                    'provider_resolved': bool(kk['pcost'])},
            '_manual_withdrawals': mw_, '_dep_rejected': drej, '_k': kk,
        }

    dw = dwin(frm, to)
    m = _period_money(frm, to)
    k = m['_k']
    dep = m['cash']['deposits']; wd = m['cash']['withdrawals']
    mwd = m['_manual_withdrawals']; dep_rej = m['_dep_rejected']
    net_cash = m['cash']['net_cash']; margin = m['cash']['margin']

    # ── сравнение с другим периодом (0.2, главная просьба Василия) ──────────────
    # compare=1 → предыдущий период РАВНОЙ длины вплотную к выбранному; либо явные
    # cfrom/cto. Дельты считаем здесь, чтобы формат был один на всех экранах.
    compare = None
    want_cmp = request.args.get('compare') in ('1', 'true') or request.args.get('cfrom')
    if want_cmp:
        span = (_dt.date.fromisoformat(to) - _dt.date.fromisoformat(frm)).days
        cto_def = str(_dt.date.fromisoformat(frm) - timedelta(days=1))
        cfrm_def = str(_dt.date.fromisoformat(cto_def) - timedelta(days=span))
        cfrm = _vd(request.args.get('cfrom'), cfrm_def)
        cto = _vd(request.args.get('cto'), cto_def)
        pm = _period_money(cfrm, cto)

        def _delta(cur, prev):
            """Дельты по числовым метрикам: абсолют + % (None, если базы нет)."""
            out = {}
            for key, v in cur.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    p = prev.get(key)
                    if isinstance(p, (int, float)) and not isinstance(p, bool):
                        out[key] = {'abs': round(v - p, 2),
                                    'pct': round((v - p) / abs(p) * 100, 1) if p else None}
            return out
        compare = {
            'period': {'from': cfrm, 'to': cto},
            'cash': pm['cash'], 'game': pm['game'], 'ngr': pm['ngr'],
            'delta': {'cash': _delta(m['cash'], pm['cash']),
                      'game': _delta(m['game'], pm['game']),
                      'ngr':  _delta(m['ngr'],  pm['ngr'])},
        }

    # игроки — СНИМОК текущего состояния (не пересчитывается по периоду), кроме
    # «новых», которых честно считаем зарегистрированными в окне
    players, new_period = q(f"""SELECT count(),
       countIf(toDate(reg_date) BETWEEN '{frm}' AND '{to}')
       FROM users WHERE account_type='normal'""")[1][0]
    played, depositors, active30, active7, vip = q("""SELECT countIf(ever_played), countIf(dep_count>0),
       countIf(recency_days<=30), countIf(recency_days<=7),
       countIf(dep_count>0 AND avg_bet>=200 AND recency_days BETWEEN 14 AND 90)
       FROM player_features WHERE account_type='normal'""")[1][0]
    winners = q("SELECT countIf(net>0) FROM player_features WHERE account_type='normal'")[1][0][0]

    # тренд по месяцам — за всё время (это график динамики, окно к нему не применяем)
    def mser(sql):
        return [_flt(r[1]) for r in q(sql)[1]]
    dep_m = mser(f"SELECT toStartOfMonth(created_at) m, round(sumIf(amount, {DEP_OK})) FROM money_transactions WHERE {NRM} GROUP BY m ORDER BY m")
    wd_m = mser(f"SELECT toStartOfMonth(created_at) m, round(sumIf(abs(amount), {WD_OK})) FROM money_transactions WHERE {NRM} GROUP BY m ORDER BY m")
    ggr_m = mser(f"SELECT toStartOfMonth(toTimezone(created_at,'Europe/Istanbul')) m, round(sumIf(bet_amount, {BET_T} AND {GSUCCESS})-sumIf(win_amount, {WIN_T} AND {GSUCCESS})) FROM game_transactions WHERE currency='TRY' AND {NRM} GROUP BY m ORDER BY m")
    mau_m = mser(f"SELECT toStartOfMonth(toTimezone(created_at,'Europe/Istanbul')) m, uniqExact(casino_player_id) FROM game_transactions WHERE {BET_T} AND {NRM} GROUP BY m ORDER BY m")

    # ── разбивка по гео (Д3): депозиты/выводы/ratio по стране за период ─────────
    # Джойн игрока к его стране: у денежных транзакций страны нет, берём из users.
    # На моно-гео казино (сейчас всё TR) это одна строка; на мульти-гео — по строке
    # на страну, чтобы видеть, где ratio уходит в убыток.
    geo_rows = q(f"""SELECT u.country_iso_estimated AS geo,
       round(sumIf(m.amount, {DEP_OK} AND {dw}))            AS dep,
       round(sumIf(abs(m.amount), {WD_OK} AND {dw}))        AS wd,
       count(DISTINCT if({DEP_OK} AND {dw}, m.casino_player_id, NULL)) AS depositors
       FROM money_transactions m INNER JOIN users u USING (casino_player_id)
       WHERE u.account_type='normal'
       GROUP BY geo HAVING dep > 0 OR wd > 0 ORDER BY dep DESC LIMIT 30""")[1]
    geo = [{'country': (r[0] or '—'), 'deposits': _flt(r[1]), 'withdrawals': _flt(r[2]),
            'net_cash': _flt(r[1]) - _flt(r[2]),
            'wd_dep_ratio': round(_flt(r[2]) / _flt(r[1]) * 100, 1) if _flt(r[1]) else 0,
            'depositors': int(r[3] or 0)} for r in geo_rows]

    players = int(players or 0)
    return api_json({
        'period': {'from': frm, 'to': to},
        'geo': geo,
        'players': {
            'total': players, 'played': int(played or 0), 'depositors': int(depositors or 0),
            'active30': int(active30 or 0), 'active7': int(active7 or 0),
            'active_period': int(k['active']), 'new30': int(new_period or 0),
            'played_pct': round(played / players * 100) if players else 0,
            'depositors_pct': round(100 * depositors / players, 1) if players else 0,
            'snapshot': True,   # total/active/vip — текущее состояние, не за период
        },
        'cash': {
            'deposits': dep, 'withdrawals': wd, 'net_cash': net_cash, 'margin': margin,
            'wd_dep_ratio': round(wd / dep * 100, 1) if dep else 0,   # Д3
            'bonus_cost': k['bonus'], 'bonus_ratio': k['bratio'],
        },
        'game': {'ggr': k['ggr'], 'rtp': k['rtp'], 'bets': k['bet'], 'wins': k['win'],
                 'hold': round(k['ggr'] / k['bet'] * 100, 2) if k['bet'] else 0},
        'ngr': {
            'ngr': k['ngr'], 'provider_cost': k['pcost'], 'affiliate_commission': k['affc'],
            'bonus_usage': k['bonus'], 'provider_resolved': bool(k['pcost']),
        },
        'risk': {
            'manual_withdrawals': mwd, 'vip_at_risk': int(vip or 0),
            'dep_rejected': dep_rej, 'winners': int(winners or 0),
        },
        'series': {'dep': dep_m, 'wd': wd_m, 'ggr': ggr_m, 'mau': mau_m},
        'compare': compare,   # None, если сравнение не запрошено
        'asof': str(data_asof())[:10] if data_asof() else None,
    })


# ════════════════════════════════════════════════════════════════════════════════
# GET /api/v1/ggr — экран «GGR и доход» (роут ggr_page() борда), 8 табов + дельты
# ════════════════════════════════════════════════════════════════════════════════
def _vd(s, d):
    """Строгая маска даты YYYY-MM-DD (как _vd в ggr_page)."""
    return s if s and re.fullmatch(r'\d{4}-\d{2}-\d{2}', s) else d


def _ggr_filters():
    """Разбор/санитизация query-параметров — дословно как в ggr_page()."""
    dmax = data_asof()
    if isinstance(dmax, _dt.datetime):
        dmax = dmax.date()
    elif isinstance(dmax, str):
        dmax = _dt.date.fromisoformat(dmax[:10])
    frm = _vd(request.args.get('from'), str(dmax - timedelta(days=29)))
    to = _vd(request.args.get('to'), str(dmax))
    prov = ''.join(c for c in request.args.get('provider', '') if c.isalnum() or c in ' _-&.')[:40]
    country = ''.join(c for c in request.args.get('country', '') if c.isalnum())[:8].upper()
    aff = ''.join(c for c in request.args.get('aff', '') if c.isalnum() or c == '_')[:64]
    lim = min(max(int(request.args.get('limit', '25') or 25), 5), 200)
    tab = request.args.get('tab', 'dashboard')
    tab = tab if tab in dict(GGR_TABS) else 'dashboard'
    return frm, to, prov, country, aff, lim, tab


@bp.get('/ggr')
@require_auth(roles=CASINO_MONEY_ROLES)
def ggr():
    """Данные всех 8 табов + KPI-блок + дельты к прошлому равному периоду.
    Логика (окна, фильтры, дельты, содержимое таба) — 1-в-1 с ggr_page()."""
    frm, to, prov, country, aff, lim, tab = _ggr_filters()

    PROV = f"dictGetOrDefault('{CH_DB}.dict_game_names','provider',tuple(game_uuid),'')"
    GNAME = GN('game_uuid')
    pfilt = ["account_type='normal'"]
    if country:
        pfilt.append(f"country_iso_estimated='{country}'")
    if aff:
        pfilt.append(f"affiliate_code='{aff}'")
    NRMg = f"casino_player_id IN (SELECT casino_player_id FROM users WHERE {' AND '.join(pfilt)})"

    def dwin(fr, t):
        return f"toDate(toTimezone(created_at,'Europe/Istanbul')) BETWEEN '{fr}' AND '{t}'"
    dw = dwin(frm, to)
    gw = f"{GSUCCESS} AND currency='TRY' AND {NRMg} AND {dw}"
    if prov:
        gw += f" AND {PROV}='{escape(prov)}'"
    mw = f"{NRMg} AND {dw}"

    k = _ggr_kpis(gw, mw, dw, NRMg, dw)
    # дельта к предыдущему равному периоду
    d0 = _date.fromisoformat(frm)
    d1 = _date.fromisoformat(to)
    span = (d1 - d0).days + 1
    pf, pt = str(d0 - timedelta(days=span)), str(d0 - timedelta(days=1))
    pgw = f"{GSUCCESS} AND currency='TRY' AND {NRMg} AND {dwin(pf,pt)}" + (f" AND {PROV}='{escape(prov)}'" if prov else '')
    pmw = f"{NRMg} AND {dwin(pf,pt)}"
    pk = _ggr_kpis(pgw, pmw, dwin(pf, pt), NRMg, dwin(pf, pt))

    deltas = {key: _delta(k[key], pk[key]) for key in
              ('bet', 'win', 'ggr', 'rtp', 'ngr', 'bonus', 'pcost', 'affc', 'active', 'avg_bet')}

    # ── фильтр-панель (опции провайдера/страны) ──
    provs = [r[0] for r in q(f"SELECT DISTINCT {PROV} p FROM game_transactions WHERE {gw} AND {PROV}!='' ORDER BY p")[1]]
    countries = [r[0] for r in q("SELECT DISTINCT country_iso_estimated c FROM users WHERE account_type='normal' AND country_iso_estimated!='' ORDER BY c")[1]]

    lc = req_locale()
    tab_data = _ggr_tab(tab, gw, mw, dw, NRMg, lim, k, PROV, GNAME, frm, to, lc)

    return api_json(loc_deep({
        'filters': {'from': frm, 'to': to, 'provider': prov, 'country': country,
                    'aff': aff, 'limit': lim, 'tab': tab},
        'tabs': [{'key': t, 'label': lbl} for t, lbl in GGR_TABS],
        'kpi': k, 'kpi_prev': pk, 'deltas': deltas,
        'provider_options': provs, 'country_options': countries,
        'tab_data': tab_data,
    }, lc))


def _ggr_tab(tab, gw, mw, dw, NRMg, lim, k, PROV, GNAME, frm, to, lc='ru'):
    """Содержимое активного таба — те же запросы, что в ggr_page() (без HTML).
    Статические метки переводит loc_deep в ggr(); динамические тексты сигналов —
    здесь через loc(шаблон).format() (иначе плейсхолдеры с числами не сматчатся)."""
    if tab == 'dashboard':
        daily = q(f"SELECT toString(toDate(toTimezone(created_at,'Europe/Istanbul'))) d, round(sumIf(bet_amount,{BET_T})-sumIf(win_amount,{WIN_T})) g FROM game_transactions WHERE {gw} GROUP BY d ORDER BY d")[1]
        neg_days = sum(1 for _, g in daily if (g or 0) < 0)
        hrtp = q(f"SELECT {PROV} p, round(sumIf(win_amount,{WIN_T})*100/nullIf(sumIf(bet_amount,{BET_T}),0),1) rtp FROM game_transactions WHERE {gw} AND {PROV}!='' GROUP BY p HAVING rtp>85 ORDER BY rtp DESC LIMIT 30")[1]
        signals = []
        if neg_days:
            signals.append({'kind': 'neg_days', 'title': '⚠ Отрицательный GGR',
                            'text': loc('{n} дн. с отрицательным GGR в периоде (игроки выиграли больше, чем поставили)', lc).format(n=neg_days)})
        if hrtp:
            signals.append({'kind': 'high_rtp', 'title': '🔺 Провайдеры с высоким RTP',
                            'text': loc('{provs} — возврат игрокам выше 85%', lc).format(provs=", ".join(str(p) for p, _ in hrtp))})
        if k['bratio'] > 12:
            signals.append({'kind': 'bonus', 'title': '🎁 Доля бонусов выше нормы',
                            'text': loc('Расход на бонусы = {bratio}% от GGR (норма ≤ 12%)', lc).format(bratio=k["bratio"])})
        return {
            'daily': [{'d': x[0], 'label': x[0][5:], 'g': _flt(x[1])} for x in daily],
            'neg_days': neg_days,
            'high_rtp': [{'provider': p, 'rtp': _flt(r)} for p, r in hrtp],
            'signals': signals,
            'bratio': k['bratio'],
        }
    if tab in ('provider', 'game'):
        gb = PROV if tab == 'provider' else 'game_uuid'
        nm = PROV if tab == 'provider' else GNAME
        rows = q(f"SELECT {nm} name, round(sumIf(bet_amount,{BET_T})) bet, round(sumIf(win_amount,{WIN_T})) win, "
                 f"round(sumIf(bet_amount,{BET_T})-sumIf(win_amount,{WIN_T})) ggr, "
                 f"round(sumIf(win_amount,{WIN_T})*100/nullIf(sumIf(bet_amount,{BET_T}),0),1) rtp, "
                 f"uniqExactIf(casino_player_id,{BET_T}) players, countIf({BET_T}) rounds "
                 f"FROM game_transactions WHERE {gw}" + (f" AND {PROV}!=''" if tab == 'provider' else '')
                 + f" GROUP BY {gb}, name ORDER BY bet DESC LIMIT {lim}")[1]
        return {'rows': [{'name': str(nme), 'bet': _flt(b), 'win': _flt(w), 'ggr': _flt(gg),
                          'rtp': _flt(rt), 'players': int(pl or 0), 'rounds': int(rn or 0)}
                         for nme, b, w, gg, rt, pl, rn in rows]}
    if tab == 'rates':
        rows = q(f"SELECT provider, engr_percent, infra_percent, revshare_percent, fixed_fee, minimum_guarantee, period FROM provider_rates ORDER BY provider LIMIT {lim}")[1]
        return {'rows': [{'provider': str(p), 'engr': _flt(e), 'infra': _flt(i),
                          'revshare': _flt(r), 'fixed_fee': _flt(ff), 'min_guarantee': _flt(mg),
                          'period': str(pe)} for p, e, i, r, ff, mg, pe in rows]}
    if tab == 'segments':
        VIPN = {5: '👑 Royal · ≥1M', 4: '💎 Diamond · ≥500k', 3: '💠 Platinum · ≥150k',
                2: '🥇 Gold · ≥50k', 1: '🥈 Silver · ≥100', 0: '⚪ Regular · <100'}
        vrows = q(f"""WITH
          vip AS (
            SELECT cid, dep, multiIf(mx<100 OR dep<100,0,dep>=1000000,5,dep>=500000,4,
              dep>=150000,3,dep>=50000,2,1) lvl
            FROM (SELECT m.casino_player_id cid, sumIf(m.amount,{DEP_OK}) dep, maxIf(m.amount,{DEP_OK}) mx
                  FROM money_transactions m INNER JOIN users u USING(casino_player_id)
                  WHERE u.account_type='normal' AND m.currency='TRY' GROUP BY m.casino_player_id)),
          per AS (SELECT casino_player_id cid, sumIf(bet_amount,{BET_T}) bet, sumIf(win_amount,{WIN_T}) win
                  FROM game_transactions WHERE {gw} GROUP BY casino_player_id)
        SELECT vip.lvl, count() players, round(sum(vip.dep)) deposits, countIf(per.bet>0) active,
          round(sum(ifNull(per.bet,0))) bet, round(sum(ifNull(per.bet,0))-sum(ifNull(per.win,0))) ggr
        FROM vip LEFT JOIN per ON vip.cid=per.cid GROUP BY vip.lvl ORDER BY vip.lvl DESC""")[1]
        b = q(f"""SELECT count(),
          countIf(isvip), round(sumIf(bet,isvip)), round(sumIf(bet-win,isvip)),
          countIf(bet-win>0), round(sumIf(bet,bet-win>0)), round(sumIf(bet-win,bet-win>0)),
          countIf(win-bet>0), round(sumIf(bet,win-bet>0)), round(sumIf(bet-win,win-bet>0)),
          countIf(bcost>0 OR bbet>0), round(sumIf(bet,bcost>0 OR bbet>0)), round(sumIf(bet-win,bcost>0 OR bbet>0)),
          round(sum(bbet+bcost)*100/nullIf(sum(bet),0),2)
        FROM (
          SELECT per.cid, per.bet bet, per.win win, per.bbet bbet, ifNull(bon.bcost,0) bcost, ifNull(v.isvip,0) isvip
          FROM (SELECT casino_player_id cid, sumIf(bet_amount,{BET_T}) bet, sumIf(win_amount,{WIN_T}) win,
                  sumIf(bet_amount,transaction_type='freespins_bet') bbet
                FROM game_transactions WHERE {gw} GROUP BY casino_player_id) per
          LEFT JOIN (SELECT casino_player_id cid, sumIf(abs(amount),{BONUS_OK}) bcost
                     FROM money_transactions WHERE {mw} GROUP BY casino_player_id) bon ON per.cid=bon.cid
          LEFT JOIN (SELECT casino_player_id cid, toUInt8(maxIf(amount,{DEP_OK})>=100 AND sumIf(amount,{DEP_OK})>=100) isvip
                     FROM money_transactions WHERE currency='TRY' GROUP BY casino_player_id) v ON per.cid=v.cid)""")[1][0]
        behavioral = [
            {'label': '👑 VIP', 'hint': 'vip_level > 0', 'players': int(b[1] or 0), 'bet': _flt(b[2]), 'ggr': _flt(b[3])},
            {'label': '📉 High Loss', 'hint': 'Ставки > Выигрыши', 'players': int(b[4] or 0), 'bet': _flt(b[5]), 'ggr': _flt(b[6])},
            {'label': '📈 Winner', 'hint': 'Выигрыши > Ставки', 'players': int(b[7] or 0), 'bet': _flt(b[8]), 'ggr': _flt(b[9])},
            {'label': '🎁 Bonus User', 'hint': 'есть бонус/бонусные ставки', 'players': int(b[10] or 0), 'bet': _flt(b[11]), 'ggr': _flt(b[12])},
        ]
        return {
            'vip': [{'level': int(lv), 'label': VIPN.get(int(lv), str(lv)), 'players': int(pl or 0),
                     'deposits': _flt(dp), 'active': int(ac or 0), 'bet': _flt(bt), 'ggr': _flt(gg)}
                    for lv, pl, dp, ac, bt, gg in vrows],
            'behavioral': behavioral,
            'risk_abuse': _flt(b[13]),
        }
    if tab == 'bonus':
        BT = ("multiIf(type='freespin','🎰 Фриспины',description ILIKE '%deneme%','🎁 Бездепозитный',"
              "description ILIKE '%kay%p%','💸 Кэшбэк',description ILIKE '%dsc%' OR description ILIKE '%yat%','💰 На депозит',"
              "type='manual_bonus','✋ Ручной бонус','Прочие')")
        rows = q(f"SELECT {BT} bt, count() events, uniqExact(casino_player_id) players, round(sum(abs(amount))) cost "
                 f"FROM money_transactions WHERE {BONUS_OK} AND {mw} GROUP BY bt ORDER BY cost DESC")[1]
        totc = sum(r[3] or 0 for r in rows) or 1
        return {
            'rows': [{'type': str(bt), 'events': int(ev or 0), 'players': int(pl or 0),
                      'cost': _flt(c), 'pct': round((c or 0) / totc * 100, 1)} for bt, ev, pl, c in rows],
            'total_cost': _flt(totc), 'bratio': k['bratio'],
        }
    if tab == 'settle':
        g = k['ggr'] or 0
        pct = lambda v: round(v / g * 100, 1) if g else 0
        waterfall = [
            {'label': 'GGR — валовый доход', 'value': g, 'pct': 100.0, 'note': 'Ставки − Выигрыши'},
            {'label': '− Расход на бонусы', 'value': -k['bonus'], 'pct': pct(k['bonus']), 'note': 'начислено игрокам'},
            {'label': '− Расход на провайдеров', 'value': -k['pcost'], 'pct': pct(k['pcost']), 'note': 'ENGR + Infra + RevShare'},
            {'label': '− Расход на аффилиатов', 'value': -k['affc'], 'pct': pct(k['affc']), 'note': 'CPA + RevShare'},
            {'label': '= NGR — чистый доход', 'value': k['ngr'], 'pct': pct(k['ngr']), 'note': 'остаётся казино'},
        ]
        arows = q(f"""WITH aff AS (
          SELECT u.affiliate_code code,
            sumIf(m.amount,{DEP_OK} AND {dw})-sumIf(abs(m.amount),{WD_OK} AND {dw}) net
          FROM money_transactions m INNER JOIN users u USING(casino_player_id)
          WHERE u.affiliate_code!='' AND {NRMg} GROUP BY code)
        SELECT aff.code, round(aff.net) net, ar.commission_rate_percent rate,
          round(greatest(aff.net,0)*ar.commission_rate_percent/100) comm
        FROM aff INNER JOIN affiliate_rates ar ON aff.code=ar.affiliate_code
        ORDER BY comm DESC LIMIT {lim}""")[1]
        return {
            'waterfall': waterfall,
            'affiliates': [{'code': str(c), 'net': _flt(nt), 'rate': _flt(rt), 'commission': _flt(cm)}
                           for c, nt, rt, cm in arows],
        }
    if tab == 'reports':
        drows = q(f"""SELECT toString(toDate(toTimezone(created_at,'Europe/Istanbul'))) d,
          round(sumIf(bet_amount,{BET_T})) bet, round(sumIf(win_amount,{WIN_T})) win,
          round(sumIf(bet_amount,{BET_T})-sumIf(win_amount,{WIN_T})) ggr,
          uniqExactIf(casino_player_id,{BET_T}) active, countIf({BET_T}) rounds
          FROM game_transactions WHERE {gw} GROUP BY d ORDER BY d DESC LIMIT 100""")[1]
        tb = sum(r[1] or 0 for r in drows)
        tw = sum(r[2] or 0 for r in drows)
        tg = sum(r[3] or 0 for r in drows)
        trn = sum(r[5] or 0 for r in drows)
        return {
            'rows': [{'d': str(d), 'bet': _flt(b), 'win': _flt(w), 'ggr': _flt(gg),
                      'active': int(ac or 0), 'rounds': int(rn or 0)} for d, b, w, gg, ac, rn in drows],
            'totals': {'bet': _flt(tb), 'win': _flt(tw), 'ggr': _flt(tg), 'rounds': int(trn or 0)},
            'from': frm, 'to': to,
        }
    return {}


# ════════════════════════════════════════════════════════════════════════════════
# GET /api/v1/money/cash — экран «Аналитика» (роут analytics() борда), секция #cash
# ════════════════════════════════════════════════════════════════════════════════
@bp.get('/money/retention-triangle')
@require_auth(roles=MONEY_ROLES)
def retention_triangle():
    """Когортный retention-треугольник (Д2, разбор с Василием): строки — когорты по
    неделе ПЕРВОГО ДЕПОЗИТА, столбцы — недели с той («нулевой») недели, ячейки — %
    когорты, вернувшейся к ИГРЕ на этой неделе. Нулевая неделя = неделя депозита.
    Прежний график был одной усреднённой линией по всем когортам — треугольника не
    было. Треугольная форма естественна: у свежих когорт поздних недель ещё нет.
    """
    N = "casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')"
    RB = "transaction_type IN ('bet','freespins_bet')"
    def _int(v, d):
        try: return max(1, int(v))
        except (TypeError, ValueError): return d
    weeks = min(_int(request.args.get('weeks'), 8), 12)          # ширина: недель после нулевой
    cohorts_n = min(_int(request.args.get('cohorts'), 10), 20)   # сколько последних когорт

    # size колонок: 0..weeks. Считаем uniqExactIf на каждый offset одним проходом.
    cols = ', '.join(
        f"round(100*uniqExactIf(f.pid, dateDiff('week', f.fw, a.aw)={k})/count(DISTINCT f.pid),1) AS w{k}"
        for k in range(weeks + 1))
    rows = q(f"""
      WITH ftd AS (
        SELECT casino_player_id AS pid,
               toMonday(toTimezone(min(created_at),'Europe/Istanbul')) AS fw
        FROM money_transactions
        WHERE type IN ('deposit','manual_deposit') AND status IN ('completed','approved','success') AND {N}
        GROUP BY pid),
      act AS (SELECT DISTINCT casino_player_id AS pid,
                     toMonday(toTimezone(created_at,'Europe/Istanbul')) AS aw
              FROM game_transactions WHERE {RB} AND {N}),
      f AS (SELECT ftd.pid, ftd.fw FROM ftd)
      SELECT toString(f.fw) AS cohort, count(DISTINCT f.pid) AS size, {cols}
      FROM f LEFT JOIN act a ON f.pid = a.pid
      GROUP BY f.fw ORDER BY f.fw DESC LIMIT {cohorts_n}""")[1]

    triangle = []
    for r in rows:
        cohort, size = r[0][:10], int(r[1] or 0)
        # w0..wN; None там, где неделя ещё «в будущем» относительно данных — фронт красит пусто
        cells = [(_flt(r[2 + k]) if r[2 + k] is not None else None) for k in range(weeks + 1)]
        triangle.append({'cohort': cohort, 'size': size, 'cells': cells})
    triangle.reverse()   # старые когорты сверху — как читается треугольник
    return api_json({'weeks': weeks, 'rows': triangle,
                     'note': loc('W0 = неделя первого депозита; далее — недели после неё', req_locale())})


@bp.get('/money/cash')
@require_auth(roles=MONEY_ROLES)
def money_cash():
    """Данные аналитических графиков: удержание, жизненный цикл, RFM, денежный поток
    (#cash), дни активности. Запросы дословно как в analytics()."""
    from player_board import LIFE
    N = "casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')"
    RB = "transaction_type IN ('bet','freespins_bet')"
    life = [{'label': LIFE.get(r[0], ('', '', r[0]))[2], 'value': int(r[1] or 0)} for r in q(f"""
      WITH pp AS (SELECT casino_player_id, multiIf(recency_days IS NULL,'never',recency_days<=7,'active',recency_days<=30,'cooling',recency_days<=60,'at_risk',recency_days<=90,'dormant','churned') s FROM player_features WHERE account_type='normal')
      SELECT s, count() FROM pp GROUP BY s ORDER BY multiIf(s='active',1,s='cooling',2,s='at_risk',3,s='dormant',4,s='churned',5,6)""")[1]]
    rc = q(f"""WITH act AS (SELECT DISTINCT casino_player_id, toMonday(toTimezone(created_at,'Europe/Istanbul')) aw FROM game_transactions WHERE {RB} AND {N}),
      first AS (SELECT casino_player_id, min(aw) fw FROM act GROUP BY casino_player_id)
      SELECT round(100*uniqExactIf(f.casino_player_id,dateDiff('week',f.fw,a.aw)=1)/uniqExact(f.casino_player_id),1),
       round(100*uniqExactIf(f.casino_player_id,dateDiff('week',f.fw,a.aw)=2)/uniqExact(f.casino_player_id),1),
       round(100*uniqExactIf(f.casino_player_id,dateDiff('week',f.fw,a.aw)=4)/uniqExact(f.casino_player_id),1),
       round(100*uniqExactIf(f.casino_player_id,dateDiff('week',f.fw,a.aw)=8)/uniqExact(f.casino_player_id),1)
      FROM first f LEFT JOIN act a ON f.casino_player_id=a.casino_player_id WHERE f.fw>='2025-12-01' AND f.fw<'2026-03-01'""")[1][0]
    ret = [{'w': 'W1', 'v': _flt(rc[0])}, {'w': 'W2', 'v': _flt(rc[1])},
           {'w': 'W4', 'v': _flt(rc[2])}, {'w': 'W8', 'v': _flt(rc[3])}]
    rfm = [{'seg': r[0], 'players': int(r[1] or 0)} for r in q(f"""
      WITH pp AS (SELECT casino_player_id, dateDiff('day',toDate(max(created_at)),today()) rc, uniqExact(toDate(created_at)) fr, sumIf(bet_amount,{RB}) mo FROM game_transactions WHERE {N} GROUP BY casino_player_id),
      s AS (SELECT *, 6-ntile(5) OVER (ORDER BY rc) R, ntile(5) OVER (ORDER BY fr) F, ntile(5) OVER (ORDER BY mo) M FROM pp)
      SELECT multiIf(R>=4 AND F>=4 AND M>=4,'Champions',R>=3 AND F>=3,'Loyal',R>=4 AND F<=2,'New',R<=2 AND F>=4 AND M>=4,'Cant-Lose',R<=2 AND F>=3,'At-Risk',R<=2,'Hibernating','Need-Att') seg, count() FROM s GROUP BY seg ORDER BY 2 DESC""")[1]]
    cf = [{'m': str(r[0])[:7], 'dep': _flt(r[1]), 'wd': _flt(r[2])} for r in q("""
      SELECT toStartOfMonth(created_at) m, round(sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed')),
       round(sumIf(amount,type IN ('withdrawal','manual_withdrawal') AND status='completed')) FROM money_transactions GROUP BY m ORDER BY m""")[1]]
    days = [{'label': r[0], 'value': int(r[1] or 0)} for r in q(f"""WITH pp AS (SELECT casino_player_id, uniqExact(toDate(created_at)) d FROM game_transactions WHERE {RB} AND {N} GROUP BY casino_player_id)
      SELECT multiIf(d=1,'1 день',d<=3,'2-3',d<=7,'4-7',d<=30,'8-30','30+') s, count() FROM pp GROUP BY s ORDER BY min(d)""")[1]]
    return api_json(loc_deep({'life': life, 'ret': ret, 'rfm': rfm, 'cf': cf, 'days': days}, req_locale()))


# ════════════════════════════════════════════════════════════════════════════════
# GET /api/v1/audit — экран «Аудит выводов» (роут audit() борда)
# ════════════════════════════════════════════════════════════════════════════════
@bp.get('/audit')
@require_auth(roles=AUDIT_ROLES)
def audit():
    """Аудит ручных списаний (manual_withdrawal): KPI, разбивка по notes, динамика,
    кто проводил, топ-25, крупные без депозита, тест-операции. Запросы как в audit()."""
    admins = {r[0] for r in q("SELECT toString(casino_player_id) FROM users WHERE role IN ('admin','support') OR account_type='service'")[1]}
    tot, cnt, napp, biggest = q("SELECT round(sum(amount)), count(), uniqExact(reviewed_by), round(max(amount)) FROM money_transactions WHERE type='manual_withdrawal' AND status='completed'")[1][0]
    apprs = q(f"SELECT reviewed_by, count(), round(sum(amount)), round(100*sumIf(amount, {CAT} IN ('🧪 тест-операции','прочее','(без пометки)'))/sum(amount)) FROM money_transactions WHERE type='manual_withdrawal' AND status='completed' GROUP BY reviewed_by ORDER BY 3 DESC LIMIT 15")[1]
    cats = q(f"SELECT {CAT} cat, round(sum(amount)) FROM money_transactions WHERE type='manual_withdrawal' AND status='completed' GROUP BY cat ORDER BY 2 DESC")[1]
    tops = q("""WITH dep AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') d FROM money_transactions GROUP BY casino_player_id)
      SELECT m.casino_player_id, u.account_type, round(m.amount), toDate(toTimezone(m.created_at,'Europe/Istanbul')), m.reviewed_by, round(dep.d)
      FROM money_transactions m LEFT JOIN users u USING(casino_player_id) LEFT JOIN dep ON dep.casino_player_id=m.casino_player_id
      WHERE m.type='manual_withdrawal' AND m.status='completed' ORDER BY m.amount DESC LIMIT 25""")[1]
    mon = q("SELECT toStartOfMonth(created_at) m, round(sum(amount)) FROM money_transactions WHERE type='manual_withdrawal' AND status='completed' GROUP BY m ORDER BY m")[1]
    zd = q("""WITH mw AS (SELECT casino_player_id, sum(amount) wd, count() n FROM money_transactions WHERE type='manual_withdrawal' AND status='completed' GROUP BY casino_player_id),
      dp AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') dep FROM money_transactions GROUP BY casino_player_id)
      SELECT mw.casino_player_id, u.account_type, round(mw.wd), round(coalesce(dp.dep,0)), mw.n
      FROM mw LEFT JOIN dp ON dp.casino_player_id=mw.casino_player_id LEFT JOIN users u ON u.casino_player_id=mw.casino_player_id
      WHERE mw.wd > 50000 AND toFloat64(coalesce(dp.dep,0)) < toFloat64(mw.wd)*0.1 ORDER BY mw.wd DESC LIMIT 80""")[1]
    tst = q("""SELECT m.casino_player_id, u.account_type, round(sum(m.amount)), count()
      FROM money_transactions m LEFT JOIN users u USING(casino_player_id)
      WHERE m.type='manual_withdrawal' AND m.status='completed' AND positionCaseInsensitive(m.notes,'test')>0
      GROUP BY m.casino_player_id, u.account_type ORDER BY 3 DESC LIMIT 40""")[1]

    zd_total = sum(_flt(r[2]) for r in zd)
    tst_total = sum(_flt(r[2]) for r in tst)

    def is_admin(rb):
        return rb in admins

    return api_json(loc_deep({
        'kpi': {'total': _flt(tot), 'count': int(cnt or 0), 'reviewers': int(napp or 0),
                'biggest': _flt(biggest), 'admin_accounts': len(admins)},
        'reviewers': [{'reviewed_by': rb, 'is_admin': is_admin(rb), 'count': int(c or 0),
                       'sum': _flt(s), 'unclear_pct': _flt(unclear)}
                      for rb, c, s, unclear in apprs],
        'categories': [{'cat': str(c), 'sum': _flt(s)} for c, s in cats],
        'top': [{'player_id': int(pid), 'account_type': atp, 'amount': _flt(amt),
                 'date': str(dt), 'reviewed_by': rb, 'deposited': _flt(depd),
                 'no_deposit_flag': _flt(depd) < _flt(amt) * 0.1}
                for pid, atp, amt, dt, rb, depd in tops],
        'monthly': [{'m': str(m)[:7], 'v': _flt(v)} for m, v in mon],
        'no_deposit': {
            'count': len(zd), 'total': zd_total,
            'rows': [{'player_id': int(zpid), 'account_type': zat, 'withdrawn': _flt(zwd),
                      'deposited': _flt(zdep), 'ops': int(zn or 0)} for zpid, zat, zwd, zdep, zn in zd],
        },
        'test_ops': {
            'count': len(tst), 'total': tst_total,
            'rows': [{'player_id': int(tp), 'account_type': ta, 'sum': _flt(ts), 'ops': int(tn or 0)}
                     for tp, ta, ts, tn in tst],
        },
    }, req_locale()))


# ════════════════════════════════════════════════════════════════════════════════
# GET /api/v1/audit/reviewer/<rid> — «Оператор списаний» (роут reviewer() борда)
# ════════════════════════════════════════════════════════════════════════════════
@bp.get('/audit/reviewer/<rid>')
@require_auth(roles=AUDIT_ROLES)
def audit_reviewer(rid):
    """Контур расследования внутреннего фрода: «кто одобрил эти списания и
    легитимен ли он». KPI по одному reviewed_by, бейдж легитимности
    (админ/служебный vs обычный аккаунт), период, за что списывал (по notes),
    помесячная динамика и топ-40 выводов, которые он одобрил. Запросы 1-в-1 с
    reviewer() борда (player_board.py:3204-3243) — формулы не переписываются."""
    # board :3206 — помечен ли оператор как админ/служебный (центральный смысл экрана)
    isadm = q("SELECT count() FROM users WHERE toString(casino_player_id)={rid:String} AND (role IN ('admin','support') OR account_type='service')", {'rid': rid})[1][0][0]
    # board :3207 — базовый фильтр по одобрившему
    base = "m.type='manual_withdrawal' AND m.status='completed' AND m.reviewed_by={rid:String}"
    # board :3208 — 5 KPI: count / sum / max / uniq игроков / период min-max
    k = q(f"SELECT count(), round(sum(m.amount)), round(max(m.amount)), uniqExact(m.casino_player_id), min(toDate(m.created_at)), max(toDate(m.created_at)) FROM money_transactions m WHERE {base}", {'rid': rid})[1][0]
    if not k[0]:  # board :3209 — abort(404) при отсутствии операций у оператора
        return api_json(error='reviewer not found', code=404)
    # board :3210 — помесячная динамика
    mon = q(f"SELECT toStartOfMonth(m.created_at) mth, round(sum(m.amount)) FROM money_transactions m WHERE {base} GROUP BY mth ORDER BY mth", {'rid': rid})[1]
    # board :3211-3213 — списания у игроков, внёсших <10% суммы вывода (count, сумма)
    zdc = q(f"""WITH dep AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') d FROM money_transactions GROUP BY casino_player_id)
      SELECT countIf(toFloat64(coalesce(dep.d,0)) < toFloat64(m.amount)*0.1), round(sumIf(m.amount, toFloat64(coalesce(dep.d,0)) < toFloat64(m.amount)*0.1))
      FROM money_transactions m LEFT JOIN dep ON dep.casino_player_id=m.casino_player_id WHERE {base}""", {'rid': rid})[1][0]
    # board :3214-3217 — топ-40 списаний оператора
    tops = q(f"""WITH dep AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') d FROM money_transactions GROUP BY casino_player_id)
      SELECT m.casino_player_id, u.account_type, round(m.amount), toDate(toTimezone(m.created_at,'Europe/Istanbul')), round(dep.d)
      FROM money_transactions m LEFT JOIN users u USING(casino_player_id) LEFT JOIN dep ON dep.casino_player_id=m.casino_player_id
      WHERE {base} ORDER BY m.amount DESC LIMIT 40""", {'rid': rid})[1]
    # board :3229 — разбивка по категориям (по полю notes)
    cats = q(f"SELECT {CAT} cat, round(sum(m.amount)) FROM money_transactions m WHERE {base} GROUP BY cat ORDER BY 2 DESC", {'rid': rid})[1]

    return api_json(loc_deep({
        'rid': str(rid),
        'is_admin': bool(isadm),  # board :3218-3219 — зелёный «админ/служебный» vs красный «обычный»
        'kpi': {
            'count': int(k[0] or 0), 'sum': _flt(k[1]), 'biggest': _flt(k[2]),
            'players': int(k[3] or 0),
            'no_deposit_count': int(zdc[0] or 0), 'no_deposit_sum': _flt(zdc[1]),
        },
        'period': {'from': str(k[4]), 'to': str(k[5])},
        'monthly': [{'m': str(m)[:7], 'v': _flt(v)} for m, v in mon],
        'categories': [{'cat': str(c), 'sum': _flt(s)} for c, s in cats],
        # board :3224-3228 — флаг «🚩 без депозита» на каждой строке (dep < amount*0.1)
        'top': [{'player_id': int(pid), 'account_type': atp, 'amount': _flt(amt),
                 'deposited': _flt(depd), 'date': str(dt),
                 'no_deposit_flag': _flt(depd) < _flt(amt) * 0.1}
                for pid, atp, amt, dt, depd in tops],
    }, req_locale()))
