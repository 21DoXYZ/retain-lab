"""api/affiliates.py — JSON-домен C5: аффилиаты (обзор + детальная сверка) и выгрузки.

Headless-обёртка над готовыми запросами player_board.py. Логика/формулы НЕ
переписаны — берём константы и функции из `player_board` (одни данные — одни
цифры, паритет с HTML-страницами /affiliates, /affiliate/<code>, /exports):

  • комиссия — pb.aff_commission_row(net, code) = max(net,0) × ставку ЭТОГО
    аффилиата (НЕ глобально); ставка — pb.aff_rate(code);
  • NGR — pb.calc_ngr; provider cost — pb.provider_cost_total;
  • GGR-сплит по аффилиатам — pb.aff_ggr_split (кэш);
  • успешные операции / типы — pb.DEP_OK / WD_OK / BONUS_OK / SUCCESS /
    GSUCCESS / BET_T / WIN_T; выгрузки — pb._DEP_COND / _BON_COND / _WD_COND;
  • дата-срез датасета — pb.data_asof(); чистка кода — pb._aff_clean().

SQL-тексты повторяют роуты affiliates()/affiliate(code)/exports_view() один в
один (те же условия через общие константы) — расхождение с бордом невозможно
по построению.

Эндпоинты (все под /api/v1):
  GET /api/v1/affiliates            — обзор: качество/окупаемость/комиссия
  GET /api/v1/affiliates/<code>     — детальная сверка с партнёркой + воронка
  GET /api/v1/exports               — журнал выгрузок кол-центра
  GET /api/v1/exports/detail?exp&seg — результаты одного списка после передачи

Роли (раздел 1 SPA_BUILD_PLAN.md, совпадают с nav.ts):
  • аффилиаты — affiliate_manager/finance/director/head_retention/analyst/super_admin;
  • выгрузки  — super_admin/head_retention/head_department/affiliate_manager.
"""
from __future__ import annotations

from flask import Blueprint, request

from .core import require_auth, api_json
import player_board as pb  # готовые helper-функции и константы борда

bp = Blueprint('api_affiliates', __name__, url_prefix='/api/v1')

# ── матрица ролей (внутренние админ-виды трафика; внешний кабинет /affiliate — B4) ──
AFF_ROLES = ['affiliate_manager', 'finance', 'director',
             'head_retention', 'analyst', 'super_admin']
EXPORT_ROLES = ['super_admin', 'head_retention', 'head_department', 'affiliate_manager']


def _status(players_win: bool, cash_drain: bool) -> str:
    """Вердикт аффилиата (как бейджи борда): и игра, и касса в минусе → loss;
    только игра в минусе → risk; только касса → cash_drain; иначе → profit."""
    if players_win and cash_drain:
        return 'loss'
    if players_win:
        return 'risk'
    if cash_drain:
        return 'cash_drain'
    return 'profit'


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/affiliates — обзор (реплика роута affiliates())
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/affiliates')
@require_auth(roles=AFF_ROLES)
def affiliates_list():
    """Список аффилиатов: игроки/FTD/касса/GGR/NGR/комиссия/hold + вердикт.
    Деньги — по определениям партнёрки (auto, completed). Комиссия — по ставке
    каждого аффилиата (pb.aff_commission_row). Цифры 1-в-1 с /affiliates.

    Окно дат ?from&to (как в деталке): БЕЗ окна — вся история (быстрые витрины и
    кэш GGR, поведение прежнее); С окном — пересчёт из raw за период: игроки =
    регистрации периода, FTD/деньги/игра — по своим датам в окне (Стамбул)."""
    _aof = pb.data_asof()
    DMIN = '2025-12-01'
    DMAX = _aof.strftime('%Y-%m-%d') if _aof else '2026-06-04'
    frm = _valid_date(request.args.get('from'), DMIN)
    to = _valid_date(request.args.get('to'), DMAX)
    if frm > to:
        frm, to = DMIN, DMAX
    filtered = (frm != DMIN) or (to != DMAX)

    if not filtered:
        # 1) витрина: игроки, FTD, оборот (та же выборка, что в борде)
        _, pf = pb.q("""SELECT affiliate_code, count() players, countIf(ftd_amount>0) ftd,
            round(sumIf(ftd_amount, ftd_amount>0)) ftd_sum, round(sum(turnover)) turn
          FROM player_features WHERE account_type='normal' AND affiliate_code!='' GROUP BY affiliate_code""")
        # 2) деньги: Deposits / Withdrawals ABS / Bonus cost
        _, mny = pb.q(f"""SELECT u.affiliate_code,
            round(sumIf(m.amount, m.{pb.DEP_OK}),2) dep,
            round(sumIf(abs(m.amount), m.{pb.WD_OK}),2) wd,
            round(sumIf(abs(m.amount), m.{pb.BONUS_OK}),2) bonus
          FROM money_transactions m
          INNER JOIN (SELECT casino_player_id, affiliate_code FROM users
                      WHERE account_type='normal' AND affiliate_code!='') u USING(casino_player_id)
          GROUP BY u.affiliate_code""")
        G4 = pb.aff_ggr_split()
        G = {c: v + (None,) for c, v in G4.items()}   # (+turn=None → возьмём из витрины)
    else:
        TZ = "'Europe/Istanbul'"
        DREG = f"toDate(toTimeZone(reg_date,{TZ})) BETWEEN '{frm}' AND '{to}'"
        DFTD = f"toDate(toTimeZone(ftd_date,{TZ})) BETWEEN '{frm}' AND '{to}'"
        DMT_M = f"toDate(toTimeZone(m.created_at,{TZ})) BETWEEN '{frm}' AND '{to}'"
        DMT_G = f"toDate(toTimeZone(g.created_at,{TZ})) BETWEEN '{frm}' AND '{to}'"
        _, pf = pb.q(f"""SELECT affiliate_code, countIf({DREG}) players,
            countIf(ftd_date IS NOT NULL AND {DFTD}) ftd,
            round(sumIf(ftd_amount, ftd_amount>0 AND {DFTD})) ftd_sum, 0 turn
          FROM users WHERE account_type='normal' AND affiliate_code!='' GROUP BY affiliate_code""")
        _, mny = pb.q(f"""SELECT u.affiliate_code,
            round(sumIf(m.amount, m.{pb.DEP_OK} AND {DMT_M}),2) dep,
            round(sumIf(abs(m.amount), m.{pb.WD_OK} AND {DMT_M}),2) wd,
            round(sumIf(abs(m.amount), m.{pb.BONUS_OK} AND {DMT_M}),2) bonus
          FROM money_transactions m
          INNER JOIN (SELECT casino_player_id, affiliate_code FROM users
                      WHERE account_type='normal' AND affiliate_code!='') u USING(casino_player_id)
          GROUP BY u.affiliate_code""")
        _, gg = pb.q(f"""SELECT u.affiliate_code,
            sumIf(g.bet_amount, g.transaction_type='bet' AND g.status='completed' AND {DMT_G}),
            sumIf(g.win_amount, g.transaction_type='win' AND g.status='completed' AND {DMT_G}),
            sumIf(g.bet_amount, g.transaction_type='freespins_bet' AND g.status='completed' AND {DMT_G}),
            sumIf(g.win_amount, g.transaction_type='freespins_win' AND g.status='completed' AND {DMT_G})
          FROM game_transactions g
          INNER JOIN (SELECT casino_player_id, affiliate_code FROM users
                      WHERE account_type='normal' AND affiliate_code!='') u USING(casino_player_id)
          GROUP BY u.affiliate_code""")
        G = {r[0]: (float(r[1] or 0), float(r[2] or 0), float(r[3] or 0), float(r[4] or 0),
                    float(r[1] or 0) + float(r[3] or 0)) for r in gg}

    M = {r[0]: r for r in mny}
    # период может дать деньги/игру у аффилиатов без регистраций в окне — объединяем коды
    PF = {r[0]: r for r in pf}
    codes = set(PF) | set(M) | set(G)
    data = []
    for code in codes:
        players, ftd, ftd_sum, turn = (PF[code][1], PF[code][2], PF[code][3], PF[code][4]) \
            if code in PF else (0, 0, 0, 0)
        mr = M.get(code)
        dep = float(mr[1] or 0) if mr else 0.0
        wd = float(mr[2] or 0) if mr else 0.0
        bonus = float(mr[3] or 0) if mr else 0.0
        rb, rw, fb, fw, gturn = G.get(code, (0.0, 0.0, 0.0, 0.0, None))
        if gturn is not None:
            turn = gturn                      # оборот периода — из game_transactions
        ggr = (rb + fb) - (rw + fw)
        ggr_real = rb - rw
        net_profit = dep - wd
        ngr = pb.calc_ngr(ggr, bonus, 0.0, pb.aff_commission_row(net_profit, code))
        turn_f = float(turn or 0)
        pw = ggr_real < 0
        cd = net_profit < 0
        data.append({
            'code': code, 'players': players, 'ftd': ftd, 'ftd_sum': float(ftd_sum or 0),
            'dep': dep, 'wd': wd, 'net_profit': net_profit, 'turn': turn_f,
            'ggr': ggr, 'ggr_real': ggr_real, 'ngr': ngr,
            'hold': round(100 * ggr / turn_f, 1) if turn_f else 0.0,
            'commission': round(pb.aff_commission_row(net_profit, code), 2),
            'rate': pb.aff_rate(code),
            'players_win': pw, 'cash_drain': cd, 'status': _status(pw, cd),
        })
    # сортировка (None-safe, как в борде) — по желанию клиента
    sort = request.args.get('sort', 'players')
    sort = sort if sort in pb.AFF_OV_SORTS else 'players'
    asc = request.args.get('dir') == 'asc'
    data.sort(key=lambda d: (d[sort] is None, d[sort]), reverse=not asc)

    n_pwin = sum(1 for d in data if d['players_win'])
    n_cash = sum(1 for d in data if d['cash_drain'])
    n_risk = sum(1 for d in data if d['players_win'] or d['cash_drain'])
    totals = {
        'affiliates': len(data),
        'players': sum(d['players'] for d in data),
        'ftd': sum(d['ftd'] for d in data),
        'players_win': n_pwin, 'cash_drain': n_cash, 'risk': n_risk,
    }
    return api_json({'rows': data, 'totals': totals,
                     'sort': sort, 'dir': 'asc' if asc else 'desc',
                     'window': {'from': frm, 'to': to, 'filtered': filtered,
                                'dmin': DMIN, 'dmax': DMAX},
                     'asof': pb.data_asof()})


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/affiliates/<code> — детальная сверка (реплика роута affiliate(code))
# ════════════════════════════════════════════════════════════════════════════
_P_SORTS = {'casino_player_id', 'reg_date', 'ftd_amount', 'dep_cnt', 'dep', 'wd_cnt',
            'wd', 'net_cash', 'turnover', 'net', 'recency_days'}


def _valid_date(s, default):
    s = (s or '').strip()
    ok = (len(s) == 10 and s[4] == '-' and s[7] == '-'
          and s[:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit())
    return s if ok else default


@bp.get('/affiliates/<code>')
@require_auth(roles=AFF_ROLES)
def affiliate_detail(code):
    """Детальная карточка источника: сверка с партнёркой (Registrations/FTD/
    Deposits/Withdrawals/Net Profit/Commission по ставке аффилиата), игровая
    аналитика (GGR/NGR/оборот), вердикт, воронка, графики и список игроков.
    Все метрики по окну дат (?from&to) и статусу игроков (?st=normal|all)."""
    code = pb._aff_clean(code)
    P = {'code': code}
    st = request.args.get('st', 'normal')
    st = st if st in ('normal', 'all') else 'normal'
    AW = "affiliate_code={code:String}" + ('' if st == 'all' else " AND account_type='normal'")

    _bk = pb.q("SELECT countIf(account_type='normal'), countIf(account_type='blocked'), count() "
               "FROM users WHERE affiliate_code={code:String}", P)[1][0]
    bk_norm, bk_block, bk_all = int(_bk[0]), int(_bk[1]), int(_bk[2])
    bk_test = bk_all - bk_norm - bk_block

    _aof = pb.data_asof()
    DMIN, DMAX = '2025-12-01', (_aof.strftime('%Y-%m-%d') if _aof else '2026-06-04')
    frm = _valid_date(request.args.get('from'), DMIN)
    to = _valid_date(request.args.get('to'), DMAX)
    if frm > to:
        frm, to = DMIN, DMAX
    filtered = (frm != DMIN) or (to != DMAX)
    TZ = "'Europe/Istanbul'"
    DREG = f"toDate(toTimeZone(reg_date,{TZ})) BETWEEN '{frm}' AND '{to}'"
    DFTD = f"toDate(toTimeZone(ftd_date,{TZ})) BETWEEN '{frm}' AND '{to}'"
    DMT = f"toDate(toTimeZone(created_at,{TZ})) BETWEEN '{frm}' AND '{to}'"
    PSET = f"casino_player_id IN (SELECT casino_player_id FROM player_features WHERE {AW})"

    tot_all = pb.q(f"SELECT count() FROM users WHERE {AW}", P)[1][0][0]
    if not tot_all:
        return api_json(error='no players for this affiliate code', code=404)
    atype = pb.q(f"SELECT any(affiliate_type) FROM player_features WHERE {AW}", P)[1][0][0]

    # регистрации и FTD В ОКНЕ (по своей дате события)
    players = pb.q(f"SELECT count() FROM users WHERE {AW} AND {DREG}", P)[1][0][0]
    fr = pb.q(f"""SELECT countIf(ftd_amount>0), round(sumIf(ftd_amount,ftd_amount>0)),
        max(ftd_date), round(avgIf(ftd_amount,ftd_amount>0))
      FROM users WHERE {AW} AND {DFTD}""", P)[1][0]
    ftd = fr[0]
    ftd_sum = float(fr[1] or 0)
    last_ftd = fr[2]
    avg_ftd = float(fr[3] or 0)

    # деньги В ОКНЕ — определения партнёрки (auto, completed)
    m = pb.q(f"""SELECT
        round(sumIf(amount, {pb.DEP_OK}),2),
        countIf({pb.DEP_OK}),
        round(sumIf(amount, type='manual_deposit' AND {pb.SUCCESS}),2),
        round(sumIf(abs(amount), {pb.WD_OK}),2),
        countIf({pb.WD_OK}),
        round(sumIf(amount, type='manual_withdrawal' AND {pb.SUCCESS}),2),
        countIf(type='withdrawal' AND status IN ('rejected','failed')),
        round(sumIf(abs(amount), {pb.BONUS_OK}),2)
      FROM money_transactions WHERE {PSET} AND {DMT}""", P)[1][0]
    (dep_appr, dep_cnt, dep_man, wd_appr, wd_cnt, wd_man, wd_rej, bonus_cost) = [float(x or 0) for x in m]
    dep_cnt, wd_cnt, wd_rej = int(dep_cnt), int(wd_cnt), int(wd_rej)

    # игра В ОКНЕ (только completed)
    gg = pb.q(f"""SELECT round(sumIf(bet_amount, transaction_type='bet' AND {pb.GSUCCESS}),2),
        round(sumIf(win_amount, transaction_type='win' AND {pb.GSUCCESS}),2),
        round(sumIf(bet_amount, transaction_type='freespins_bet' AND {pb.GSUCCESS}),2),
        round(sumIf(win_amount, transaction_type='freespins_win' AND {pb.GSUCCESS}),2)
      FROM game_transactions WHERE {PSET} AND {DMT}""", P)[1][0]
    (real_bets, real_wins, fs_bets, fs_wins) = [float(x or 0) for x in gg]
    ggr_real = real_bets - real_wins
    ggr_fs = fs_bets - fs_wins
    ggr_game = ggr_real + ggr_fs
    turn = real_bets + fs_bets
    active = pb.q(f"SELECT uniqExact(casino_player_id) FROM game_transactions "
                  f"WHERE {PSET} AND {DMT} AND {pb.BET_T} AND {pb.GSUCCESS}", P)[1][0][0]

    # производные (спека казино) — формулы борда
    conv = round(100 * ftd / players, 1) if players else 0.0
    dep_ratio = round(100 * bonus_cost / dep_appr, 1) if dep_appr else 0.0
    net_profit = dep_appr - wd_appr                                    # Affiliate net = Deposits − Withdrawals
    commission = round(pb.aff_commission_row(net_profit, code), 2)     # max(net,0) × ставку ЭТОГО аффилиата
    hold = round(100 * ggr_game / turn, 1) if turn else 0.0
    hold_real = round(100 * ggr_real / real_bets, 1) if real_bets else 0.0
    ngr = pb.calc_ngr(ggr_game, bonus_cost, pb.provider_cost_total(PSET), commission)

    pw_d = ggr_real < 0
    cd_d = net_profit < 0

    # ── графики (те же выборки, что в борде) ──
    regs = [[str(r[0])[:7], r[1]] for r in pb.q(
        f"SELECT toStartOfMonth(toTimeZone(reg_date,'Europe/Istanbul')) m, count() "
        f"FROM player_features WHERE {AW} AND reg_date IS NOT NULL AND {DREG} GROUP BY m ORDER BY m", P)[1]]
    money = [[str(r[0])[:7], float(r[1] or 0), float(r[2] or 0)] for r in pb.q(
        f"""SELECT toStartOfMonth(toTimeZone(created_at,'Europe/Istanbul')) m,
            sumIf(amount, type='deposit' AND status='completed') dep,
            sumIf(amount, type='withdrawal' AND status='completed') wd
          FROM money_transactions WHERE {PSET} AND {DMT}
          GROUP BY m ORDER BY m""", P)[1]]
    life = [[str(r[0]), r[1]] for r in pb.q(
        f"SELECT lifecycle, count() FROM player_features WHERE {AW} GROUP BY lifecycle ORDER BY 2 DESC", P)[1]]
    prov = [[str(r[0]), r[1]] for r in pb.q(
        f"SELECT primary_provider, count() FROM player_features WHERE {AW} AND primary_provider!='' "
        f"GROUP BY 1 ORDER BY 2 DESC LIMIT 8", P)[1]]
    tg = pb.q(f"""SELECT any(aggregator) prov, {pb.GN()} g, uniqExact(casino_player_id) ppl,
        countIf(transaction_type IN ('bet','freespins_bet')) bets,
        round(sumIf(bet_amount, transaction_type IN ('bet','freespins_bet'))) turn,
        round(sumIf(win_amount, transaction_type IN ('win','freespins_win')) - sumIf(bet_amount, transaction_type IN ('bet','freespins_bet'))) net
      FROM game_transactions WHERE {PSET} AND {DMT} AND game_uuid!='' GROUP BY game_uuid ORDER BY turn DESC LIMIT 15""", P)[1]
    top_games = [{'game': str(g), 'provider': (pv or '—'), 'players': ppl, 'bets': bets,
                  'turnover': float(tn or 0), 'net': float(nt or 0)} for (pv, g, ppl, bets, tn, nt) in tg]
    pays = [[str(r[0]), r[1]] for r in pb.q(
        f"SELECT primary_payment_method, count() FROM player_features WHERE {AW} AND primary_payment_method!='' "
        f"GROUP BY 1 ORDER BY 2 DESC LIMIT 8", P)[1]]

    # ── список игроков (пагинация, реальная касса) ──
    psort = request.args.get('sort', 'dep')
    psort = psort if psort in _P_SORTS else 'dep'
    asc_p = request.args.get('dir') == 'asc'
    page = max(0, int(request.args.get('p', '0') or 0))
    _, prows0 = pb.q(f"""SELECT casino_player_id, lifecycle, country, toDate(reg_date) reg_date, ftd_amount,
        primary_provider, recency_days FROM player_features WHERE {AW}""", P)
    pmoney = {r[0]: r for r in pb.q(f"""SELECT casino_player_id,
        round(sumIf(amount, {pb.DEP_OK}),2),
        countIf({pb.DEP_OK}),
        round(sumIf(abs(amount), {pb.WD_OK}),2),
        countIf({pb.WD_OK})
      FROM money_transactions WHERE {PSET} AND {DMT}
      GROUP BY casino_player_id""", P)[1]}
    pgame = {r[0]: (float(r[1] or 0), float(r[2] or 0)) for r in pb.q(f"""SELECT casino_player_id,
        round(sumIf(bet_amount, {pb.BET_T} AND {pb.GSUCCESS}),2),
        round(sumIf(win_amount, {pb.WIN_T} AND {pb.GSUCCESS}) - sumIf(bet_amount, {pb.BET_T} AND {pb.GSUCCESS}),2)
      FROM game_transactions WHERE {PSET} AND {DMT} GROUP BY casino_player_id""", P)[1]}
    plist = []
    for (pid, lf, ctry, reg, ftd_p, prov_p, rec) in prows0:
        mr = pmoney.get(pid)
        gr = pgame.get(pid)
        dep_p = float(mr[1] or 0) if mr else 0.0
        dcnt = int(mr[2]) if mr else 0
        wd_p = float(mr[3] or 0) if mr else 0.0
        wcnt = int(mr[4]) if mr else 0
        turn_p = gr[0] if gr else 0.0
        net_p = gr[1] if gr else 0.0
        plist.append({
            'casino_player_id': pid, 'lifecycle': lf, 'country': ctry,
            'reg_date': str(reg)[:10] if reg else None, 'ftd_amount': float(ftd_p or 0),
            'dep': dep_p, 'dep_cnt': dcnt, 'wd': wd_p, 'wd_cnt': wcnt, 'net_cash': dep_p - wd_p,
            'turnover': turn_p, 'net': net_p, 'provider': prov_p,
            'recency_days': rec if rec is not None else None,
        })

    def _sort_key(d):
        if psort == 'recency_days':
            v = d['recency_days'] if d['recency_days'] is not None else 10 ** 9  # None → в конец (как борд)
        else:
            v = d[psort]
        return (v is None, v)

    plist.sort(key=_sort_key, reverse=not asc_p)
    total_p = len(plist)
    pview = plist[page * 100:(page + 1) * 100]

    return api_json({
        'code': code,
        'affiliate_type': atype,
        'window': {'from': frm, 'to': to, 'filtered': filtered, 'dmin': DMIN, 'dmax': DMAX},
        'status_filter': st,
        'breakdown': {'normal': bk_norm, 'test': bk_test, 'blocked': bk_block, 'all': bk_all},
        'total_players': total_p,
        # блок 1 — сверка с партнёркой (те же пункты/определения)
        'reconciliation': {
            'registrations': players, 'conversion': conv,
            'ftd': ftd, 'ftd_rate': conv, 'avg_ftd': avg_ftd, 'last_ftd': last_ftd,
            'deposits_approved': dep_appr, 'deposits_count': dep_cnt,
            'withdrawals_approved': wd_appr, 'withdrawals_count': wd_cnt, 'withdrawals_rejected': wd_rej,
            'bonus_cost': bonus_cost, 'bonus_ratio': dep_ratio,
            'net_profit': net_profit,
            'commission': commission, 'commission_rate': pb.aff_rate(code),
            'active_players': active,
        },
        # блок 2 — игровая аналитика (сверх партнёрки)
        'game': {
            'turnover': turn, 'real_bets': real_bets, 'fs_bets': fs_bets,
            'ggr': ggr_game, 'hold': hold, 'ggr_real': ggr_real, 'hold_real': hold_real,
            'ggr_fs': ggr_fs, 'ngr': ngr,
            'manual_withdrawals': wd_man, 'manual_deposits': dep_man, 'ftd_sum': ftd_sum,
        },
        'verdict': _status(pw_d, cd_d),
        # воронка источника: регистрации → FTD → активные
        'funnel': {'registrations': players, 'ftd': ftd, 'active': active},
        'charts': {'regs': regs, 'money': money, 'life': life, 'prov': prov,
                   'top_games': top_games, 'pays': pays},
        'players': {'rows': pview, 'total': total_p, 'page': page, 'page_size': 100,
                    'sort': psort, 'dir': 'asc' if asc_p else 'desc'},
        'asof': _aof,
    })


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/exports — журнал выгрузок (реплика exports_view() список)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/exports')
@require_auth(roles=EXPORT_ROLES)
def exports_journal():
    """Журнал переданных в кол-центр списков и что случилось ПОСЛЕ выгрузки:
    депнули / бонус / вернулись к игре, суммы «внесли/вывели/чистыми»."""
    rows = pb.q("""
    WITH pl AS (SELECT DISTINCT casino_player_id cid FROM segment_exports),
    mp AS (
      SELECT casino_player_id cid, maxIf(created_at,""" + pb._DEP_COND + """) last_dep,
             maxIf(created_at,""" + pb._BON_COND + """) last_bon
      FROM money_transactions WHERE casino_player_id IN (SELECT cid FROM pl) GROUP BY cid),
    gp AS (
      SELECT casino_player_id cid, maxIf(created_at, transaction_type IN ('bet','freespins_bet')) last_bet
      FROM game_transactions WHERE casino_player_id IN (SELECT cid FROM pl) GROUP BY cid)
    , dm AS (
      SELECT e2.export_ts ets2, e2.segment seg2,
             round(sumIf(toFloat64(m2.amount), m2.""" + pb._DEP_COND.replace(" AND ", " AND m2.") + """)) dep_try,
             round(sumIf(toFloat64(m2.amount), m2.""" + pb._WD_COND.replace(" AND ", " AND m2.") + """)) wd_try
      FROM segment_exports e2
      INNER JOIN money_transactions m2 ON m2.casino_player_id = e2.casino_player_id
      WHERE m2.created_at > e2.export_ts
      GROUP BY ets2, seg2)
    SELECT toString(e.export_ts) ets,
      any(formatDateTime(toTimezone(e.export_ts,'Europe/Istanbul'),'%d.%m.%Y %H:%i')) disp,
      e.segment, count() n,
      countIf(mp.last_dep > e.export_ts) deposited,
      countIf(mp.last_bon > e.export_ts) bonus_given,
      countIf(gp.last_bet > e.export_ts) returned,
      countIf(mp.last_dep > e.export_ts AND NOT (gp.last_bet > e.export_ts)) dep_no_play,
      max(e.is_demo) is_demo,
      ifNull(any(dm.dep_try), 0) dep_try,
      ifNull(any(dm.wd_try), 0) wd_try
    FROM segment_exports e LEFT JOIN mp ON mp.cid=e.casino_player_id LEFT JOIN gp ON gp.cid=e.casino_player_id
    LEFT JOIN dm ON dm.ets2=e.export_ts AND dm.seg2=e.segment
    GROUP BY ets, e.segment ORDER BY ets DESC, e.segment
    """)[1]

    result = []
    for ets, disp, segn, n, dep, bon, ret, dnp, is_demo, dtry, wtry in rows:
        net = float(dtry or 0) - float(wtry or 0)
        result.append({
            'ets': ets, 'disp': disp, 'segment': segn, 'players': n,
            'deposited': dep, 'deposited_pct': round(dep / n * 100) if n else 0,
            'bonus_given': bon, 'returned': ret, 'dep_no_play': dnp,
            'is_demo': bool(is_demo),
            'dep_try': float(dtry or 0), 'wd_try': float(wtry or 0), 'net': net,
        })
    n_try = sum(float(r[9] or 0) for r in rows)
    n_wd = sum(float(r[10] or 0) for r in rows)
    totals = {
        'exports': len(rows),
        'players': sum(r[3] for r in rows),
        'deposited': sum(r[4] for r in rows),
        'dep_try': n_try, 'wd_try': n_wd, 'net': n_try - n_wd,
    }
    return api_json({'rows': result, 'totals': totals})


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/exports/detail — результаты одного списка (реплика exports_view() деталь)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/exports/detail')
@require_auth(roles=EXPORT_ROLES)
def exports_detail():
    """Что случилось с игроками одного списка ПОСЛЕ передачи в кол-центр
    (по параметрам ?exp=<export_ts>&seg=<segment>)."""
    exp = request.args.get('exp')
    seg = request.args.get('seg')
    if not exp or not seg:
        return api_json(error='exp and seg are required', code=400)

    rows = pb.q("""
    WITH ex AS (SELECT casino_player_id, rec_bonus FROM segment_exports
                WHERE toString(export_ts)={ts:String} AND segment={seg:String}),
    thr AS (SELECT any(export_ts) t FROM segment_exports
            WHERE toString(export_ts)={ts:String} AND segment={seg:String}),
    mon AS (
      SELECT m.casino_player_id cid,
        countIf(""" + pb._DEP_COND + """) dep_n, round(sumIf(toFloat64(amount), """ + pb._DEP_COND + """)) dep_sum,
        minIf(created_at, """ + pb._DEP_COND + """) dep_first,
        countIf(""" + pb._BON_COND + """) bonus_n, minIf(created_at, """ + pb._BON_COND + """) bonus_first,
        round(sumIf(toFloat64(amount), """ + pb._WD_COND + """)) wd_sum
      FROM money_transactions m INNER JOIN ex ON m.casino_player_id=ex.casino_player_id
      WHERE m.created_at > (SELECT t FROM thr) GROUP BY cid),
    gam AS (
      SELECT g.casino_player_id cid, count() bets_after
      FROM game_transactions g INNER JOIN ex ON g.casino_player_id=ex.casino_player_id
      WHERE g.created_at > (SELECT t FROM thr) AND g.transaction_type IN ('bet','freespins_bet') GROUP BY cid)
    SELECT ex.casino_player_id, ex.rec_bonus,
      ifNull(m.dep_n,0), ifNull(m.dep_sum,0), m.dep_first,
      ifNull(m.bonus_n,0), m.bonus_first, ifNull(g.bets_after,0), ifNull(m.wd_sum,0)
    FROM ex LEFT JOIN mon m ON ex.casino_player_id=m.cid LEFT JOIN gam g ON ex.casino_player_id=g.cid
    ORDER BY (ifNull(m.dep_n,0)>0) DESC, ifNull(m.dep_sum,0) DESC, (ifNull(g.bets_after,0)>0) DESC
    """, {'ts': exp, 'seg': seg})[1]

    total = len(rows)
    dep = sum(1 for r in rows if r[2] > 0)
    bon = sum(1 for r in rows if r[5] > 0)
    ret = sum(1 for r in rows if r[7] > 0)
    dnp = sum(1 for r in rows if r[2] > 0 and r[7] == 0)
    dep_try = sum(float(r[3] or 0) for r in rows)     # внесли после выгрузки
    wd_try = sum(float(r[8] or 0) for r in rows)      # вывели после выгрузки

    players = []
    for cid, recb, dep_n, dep_sum, dep_first, bonus_n, bonus_first, bets, wd_sum in rows:
        if dep_n > 0:
            res_tag = 'deposit'
        elif bets > 0:
            res_tag = 'returned'
        elif bonus_n > 0:
            res_tag = 'bonus'
        else:
            res_tag = 'none'
        pnet = float(dep_sum or 0) - float(wd_sum or 0)
        players.append({
            'player_id': cid, 'rec_bonus': recb,
            'dep_n': dep_n, 'dep_sum': float(dep_sum or 0), 'dep_first': dep_first,
            'bonus_n': bonus_n, 'bonus_first': bonus_first,
            'bets_after': bets, 'wd_sum': float(wd_sum or 0),
            'net': pnet, 'not_played': (dep_n > 0 and bets == 0), 'result': res_tag,
        })

    dsp = pb.q("SELECT formatDateTime(toTimezone(any(export_ts),'Europe/Istanbul'),'%d.%m.%Y %H:%i') "
               "FROM segment_exports WHERE toString(export_ts)={ts:String} AND segment={seg:String}",
               {'ts': exp, 'seg': seg})[1]
    dsp = dsp[0][0] if dsp else exp[:16]

    return api_json({
        'segment': seg, 'disp': dsp, 'exp': exp,
        'summary': {'total': total, 'deposited': dep, 'bonus': bon, 'returned': ret,
                    'dep_no_play': dnp, 'dep_try': dep_try, 'wd_try': wd_try,
                    'net': dep_try - wd_try},
        'rows': players,
    })
