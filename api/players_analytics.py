"""api/players_analytics.py — домен «База игроков» (агент C2).

Список игроков (фильтры/сортировки/пагинация), аналитические СЕКЦИИ карточки
(паттерн, траектория, лог сессий, ритм, LTV/квантили, детали игры) и экспорт
сегмента CSV/XLSX.

Принцип волны 2C: НЕ переписываем SQL/формулы — переиспользуем готовые helper'ы
`player_board` (`_players_filter`, тот же список-запрос из index(), `_export_rows`,
`_EXPORT_COLS`, `_export_name`, `_export_log`, `_rhythm`, `GN`). Одни данные —
одни цифры (паритет с HTML-страницами / и /player/<id>).

Ядро (`api/core.py`, агент A3) уже отдаёт `GET /players/<id>/summary`
(деньги/игра/скоры/оффер) и `/players/search` — секции «Деньги» и «Игра»
переиспользуют summary, а НЕ дублируют его. Здесь только то, чего в summary нет
(паттерн: stuck/oneshot; LTV: квантили + лестница депозитов) + списки/лог/ритм.

Эндпоинты (все под /api/v1):
  GET /players                       — список базы (те же фильтры, что _players_filter)
  GET /players/<id>/pattern          — паттерн: любимая/stuck/oneshot/концентрация
  GET /players/<id>/games            — траектория игр (player_games, названия через GN)
  GET /players/<id>/game/<gid>       — детали одной игры (ритм + по дням)
  GET /players/<id>/sessions         — лог сессий (НАЗВАНИЯ игр, не хеши) + моментум
  GET /players/<id>/rhythm           — ритм ставок (dow/hour/heatmap + статы)
  GET /players/<id>/ltv              — LTV-прогноз, квантили P10/P50/P90, лестница депозитов
  GET /players/<id>/deposits         — список депозитов (+ts_raw для выбора окна макс-баланса)
  GET /players/<id>/bonuses          — сводка по статусам + таблица бонусов + «депозит ≤N дней»
  GET /players/<id>/max-balance      — макс-баланс за период (режим А от депозита / режим Б даты)
  GET /players/export.csv            — экспорт сегмента (те же колонки/строки, что /players.csv)
  GET /players/export.xlsx           — экспорт сегмента XLSX (идентично /players.xlsx)
"""
from __future__ import annotations

import io
import os

from flask import Blueprint, Response, request

from .core import api_json, current_role, require_auth, ensure_player_access
import player_board as pb   # готовые helper-функции борда (НЕ переписываем формулы)

bp = Blueprint('api_players_analytics', __name__, url_prefix='/api/v1')

# ── матрица ролей ─────────────────────────────────────────────────────────────
# СПИСОК всей базы — зеркало пункта nav «Игроки» (SPA_BUILD_PLAN.md §1):
# видят руководящие/аналитические/сервисные роли. НЕ operator / affiliate —
# у них свои изолированные срезы (очередь / кабинет), полная база им закрыта.
LIST_ROLES = frozenset({
    'super_admin', 'head_retention', 'director', 'head_department',
    'analyst', 'finance', 'marketing_manager', 'affiliate_manager',
    'risk_officer', 'support', 'vip_manager', 'viewer',
})

# ЭКСПОРТ сегмента (§1 + ТЗ КЦ): главы отделов/ретеншена, финансист, директор,
# супер-админ. analyst — только если явно включён флагом (открытый вопрос №4
# плана: по умолчанию ВЫКЛ). НЕ operator / affiliate (защита от увода базы).
_EXPORT_BASE = {'super_admin', 'head_retention', 'head_department', 'director', 'finance'}


def _analyst_export_enabled() -> bool:
    return os.environ.get('ANALYST_EXPORT', '').strip().lower() in ('1', 'true', 'yes', 'on')


EXPORT_ROLES = frozenset(_EXPORT_BASE | ({'analyst'} if _analyst_export_enabled() else set()))

# Денежные секции карточки (💳 Депозиты, 🎁 Бонусы и эффект) — казино-деньги по
# конкретному игроку. operator УБРАН обратно (решение клиента 2026-07-29): полную
# карточку операторам откатили — деньги/бонусы/vip-intel в карточке им не отдаём.
# operator/support/affiliate/viewer — карточка без денег.
MONEY_SECTION_ROLES = frozenset({
    'super_admin', 'head_retention', 'director', 'head_department',
    'analyst', 'finance', 'marketing_manager', 'affiliate_manager',
    'risk_officer', 'vip_manager',
})

# Блоки ТЗ «Бонусы + макс-баланс» (new_u/ТЗ_карточка_игрока_бонусы_и_макс_баланс.md):
# бонусы дополнительно видит support (sorry-бонусы, контроль злоупотреблений);
# operator ДОБАВЛЕН (решение клиента 2026-07-29): оператору нужна «реакция на
# бонусы» (статусы выдач + депозит после бонуса) по СВОИМ игрокам (anti-IDOR
# оставляет только назначенных) — при этом остальная денежная секция ему закрыта
# (operator НЕ в MONEY_SECTION_ROLES).
BONUS_BLOCK_ROLES = frozenset(MONEY_SECTION_ROLES | {'support', 'operator'})
# Макс-баланс — инструмент разговора с игроком (саппорт/КЦ/VIP): + support и operator;
# anti-IDOR (ensure_player_access) оставляет оператору только своих игроков.
MAXBAL_ROLES = frozenset(MONEY_SECTION_ROLES | {'support', 'operator'})
# Окно «целевого действия» после бонуса, дней (ТЗ: константа, вынесена в конфиг).
BONUS_REACTION_DAYS = int(os.environ.get('BONUS_REACTION_DAYS', '7') or 7)

# размер страницы списка — как в борде (окно «1–50 из N» для паритета)
PAGE_SIZE = 50


# ── утилиты ───────────────────────────────────────────────────────────────────
def _exists(pid: int) -> bool:
    """Есть ли игрок в витрине (для честного 404 секций)."""
    try:
        return bool(pb.q("SELECT 1 FROM player_features WHERE casino_player_id={pid:UInt32} LIMIT 1",
                         {'pid': pid})[1])
    except Exception:
        return False


def _game_name_map(pid: int) -> dict[str, str]:
    """{game_uuid: человекочитаемое название} по играм игрока — как gmap в борде.
    Названия из справочника (GN); не встреченные в потоке uuid остаются как есть."""
    try:
        rows = pb.q(f"SELECT game_uuid, {pb.GN('game_uuid')} FROM player_games "
                    "WHERE casino_player_id={pid:UInt32}", {'pid': pid})[1]
        return {str(u): str(nm) for u, nm in rows}
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════════════════
# СПИСОК ИГРОКОВ  (переиспользует _players_filter + список-запрос из index())
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/players')
@require_auth(roles=LIST_ROLES)
def players_list():
    """База игроков с фильтрами (seg/life/dep/at/aff/exp/vip/q), сортировкой
    (sort/dir) и пагинацией (p). Те же WHERE и та же выборка колонок, что на
    странице / живого борда → числа 1-в-1."""
    W, params, flt = pb._players_filter(request.args)
    sort = request.args.get('sort', 'turnover')
    sort = sort if sort in pb.SORTS else 'turnover'
    dr = 'ASC' if request.args.get('dir') == 'asc' else 'DESC'
    try:
        page = max(0, int(request.args.get('p', '0') or 0))
    except (TypeError, ValueError):
        page = 0

    total = pb.q(f"SELECT count() FROM player_features WHERE {W}", params)[1][0][0]
    rows = pb.q(
        "SELECT casino_player_id,lifecycle,is_depositor,bets,turnover,net,recency_days,"
        "dep_count,dep_sum,bonus_sum,distinct_games,churned_30d,account_type,net_cash "
        f"FROM player_features WHERE {W} ORDER BY {sort} {dr} NULLS LAST "
        f"LIMIT {PAGE_SIZE} OFFSET {page * PAGE_SIZE}", params)[1]

    # кого уже передавали в кол-центр (пометка 📤) — только по показанным id
    expd: dict[int, str] = {}
    if rows:
        try:
            id_list = ','.join(str(int(r[0])) for r in rows)
            expd = {int(a): b for a, b in pb.q(
                "SELECT casino_player_id, formatDateTime(toTimezone(max(export_ts),"
                "'Europe/Istanbul'),'%d.%m.%Y') "
                f"FROM segment_exports WHERE casino_player_id IN ({id_list}) "
                "GROUP BY casino_player_id")[1]}
        except Exception:
            expd = {}

    items = []
    for r in rows:
        (pid, lf, isd, bets, turn, net, rec, dc, ds, bs, dg, ch30, atp, ncash) = r
        items.append({
            'player_id': pid, 'lifecycle': lf, 'is_depositor': bool(isd),
            'bets': bets, 'turnover': turn, 'net': net, 'recency_days': rec,
            'dep_count': dc, 'dep_sum': ds, 'bonus_sum': bs, 'distinct_games': dg,
            'churned_30d': bool(ch30), 'account_type': atp, 'net_cash': ncash,
            # 🎯 обыгрывает казино: в плюсе по кассе (net_cash<0) и по игре (net>0)
            'beats_casino': (float(ncash or 0) < 0 and float(net or 0) > 0),
            'exported_at': expd.get(pid),   # дата последней выгрузки или None
        })

    # support/viewer видят список, но БЕЗ денег казино — маскируем фин-колонки
    # (net/turnover/касса/депозиты/бонусы). Матрица §1: support — без денег казино,
    # viewer — обезличенные данные.
    if current_role() in ('support', 'viewer'):
        _FIN = ('turnover', 'net', 'net_cash', 'dep_sum', 'bonus_sum', 'beats_casino')
        items = [{**it, **{k: None for k in _FIN}} for it in items]

    return api_json({
        'items': items,
        'total': total,
        'page': page,
        'per_page': PAGE_SIZE,
        'has_next': (page + 1) * PAGE_SIZE < total,
        'sort': sort,
        'dir': dr.lower(),
        'filters': flt,
        'sorts': sorted(pb.SORTS),
    })


# ════════════════════════════════════════════════════════════════════════════
# СЕКЦИИ КАРТОЧКИ (комплементарны summary ядра — только то, чего в summary нет)
# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# ID-шники по текущему фильтру — для «Выбрать всех по фильтру» (массовое
# назначение 100-300 игроков без постраничного тыканья). Только id (без PII, без
# денег) → лёгкий ответ; тот же WHERE, что и список. Роли — LIST_ROLES (оператора
# там нет → защита от увода базы сохраняется). Лимит 2000: хватает под сегмент,
# не даёт выкачать всю базу и не роняет upsert/аудит назначения.
_IDS_CAP = 2000

@bp.get('/players/ids')
@require_auth(roles=LIST_ROLES)
def players_ids():
    W, params, _ = pb._players_filter(request.args)
    sort = request.args.get('sort', 'turnover')
    sort = sort if sort in pb.SORTS else 'turnover'
    dr = 'ASC' if request.args.get('dir') == 'asc' else 'DESC'
    total = pb.q(f"SELECT count() FROM player_features WHERE {W}", params)[1][0][0]
    rows = pb.q(
        "SELECT casino_player_id FROM player_features "
        f"WHERE {W} ORDER BY {sort} {dr} NULLS LAST LIMIT {_IDS_CAP}", params)[1]
    ids = [int(r[0]) for r in rows]
    return api_json({
        'ids': ids,
        'total': int(total),
        'capped': int(total) > _IDS_CAP,   # отдали первые _IDS_CAP по текущей сортировке
        'cap': _IDS_CAP,
    })


@bp.get('/players/<int:pid>/pattern')
@require_auth()
def player_pattern(pid: int):
    """🧭 Паттерн: любимая игра / концентрация / «дольше возвращался» (stuck) /
    «бросил после 1 дня» (oneshot). Названия игр — не хеши (как в борде)."""
    denied = ensure_player_access(pid)   # anti-IDOR
    if denied:
        return denied
    d = pb.q("SELECT favourite_game, favourite_game_bets, game_concentration, "
             "stuck_game, stuck_game_days, oneshot_games "
             "FROM player_features WHERE casino_player_id={pid:UInt32}", {'pid': pid})[1]
    if not d:
        return api_json(error='player not found', code=404)
    fav, favb, conc, stuck, stuckd, oneshot = d[0]
    gmap = _game_name_map(pid)
    fav_u, stuck_u = str(fav or ''), str(stuck or '')
    return api_json({
        'player_id': pid,
        'favourite_game': fav_u or None,
        'favourite_game_name': gmap.get(fav_u, fav_u) or None,
        'favourite_game_bets': favb,
        'game_concentration': conc,
        'stuck_game': stuck_u or None,
        'stuck_game_name': gmap.get(stuck_u, stuck_u) or None,
        'stuck_game_days': stuckd,
        'oneshot_games': oneshot,
    })


@bp.get('/players/<int:pid>/games')
@require_auth()
def player_games(pid: int):
    """🗺 Траектория игр: player_games по порядку знакомства, названия через GN
    (не хеши). Помечает любимую игру (по числу ставок)."""
    denied = ensure_player_access(pid)   # anti-IDOR
    if denied:
        return denied
    if not _exists(pid):
        return api_json(error='player not found', code=404)
    jr = pb.q(f"SELECT toDate(first_played) d, game_uuid, provider, bets, days_played, "
              f"{pb.GN()} gname FROM player_games WHERE casino_player_id={{pid:UInt32}} "
              "ORDER BY first_played LIMIT 60", {'pid': pid})[1]
    fav = pb.q("SELECT favourite_game FROM player_features WHERE casino_player_id={pid:UInt32}",
               {'pid': pid})[1]
    fav_u = str(fav[0][0] or '') if fav else ''
    fav_name = None
    games = []
    for d, g, prov, bets, dys, gname in jr:
        gu = str(g)
        is_fav = gu == fav_u
        if is_fav:
            fav_name = str(gname)
        games.append({'first_played': d, 'game_uuid': gu, 'provider': prov,
                      'bets': bets, 'days_played': dys, 'game_name': str(gname),
                      'is_favourite': is_fav})
    return api_json({'player_id': pid, 'count': len(games),
                     'favourite_game': fav_u or None, 'favourite_game_name': fav_name,
                     'games': games})


@bp.get('/players/<int:pid>/game/<path:gid>')
@require_auth()
def player_game_detail(pid: int, gid: str):
    """Детали одной игры игрока: агрегаты + ритм ставок + разбивка по дням.
    Переиспускает те же запросы, что HTML-роут /player/<id>/game/<gid>."""
    denied = ensure_player_access(pid)   # anti-IDOR
    if denied:
        return denied
    info = pb.q(f"SELECT count(), countIf(transaction_type IN ('bet','freespins_bet')), "
                "round(sumIf(bet_amount,transaction_type IN ('bet','freespins_bet'))), "
                "uniqExact(toDate(toTimezone(created_at,'Europe/Istanbul'))), any(aggregator), "
                f"{pb.GN()} FROM game_transactions "
                "WHERE casino_player_id={pid:UInt32} AND game_uuid={gid:String} "
                "GROUP BY game_uuid", {'pid': pid, 'gid': gid})[1]
    if not info or not info[0][1]:
        return api_json(error='game not found for player', code=404)
    i = info[0]
    rdata, rst = pb._rhythm(
        "casino_player_id={pid:UInt32} AND game_uuid={gid:String} "
        "AND transaction_type IN ('bet','freespins_bet')", {'pid': pid, 'gid': gid})
    dates = pb.q(
        "SELECT toDate(toTimezone(created_at,'Europe/Istanbul')) dt, "
        "countIf(transaction_type IN ('bet','freespins_bet')) b, "
        "round(sumIf(bet_amount,transaction_type IN ('bet','freespins_bet'))) turn "
        "FROM game_transactions WHERE casino_player_id={pid:UInt32} AND game_uuid={gid:String} "
        "GROUP BY dt ORDER BY dt", {'pid': pid, 'gid': gid})[1]
    return api_json({
        'player_id': pid, 'game_uuid': gid, 'game_name': i[5], 'provider': i[4],
        'total_txns': i[0], 'bets': i[1], 'turnover': i[2], 'active_days': i[3],
        'rhythm': {'dow': rdata['dow'], 'hour': rdata['hour'], 'hm': rdata['hm'], 'stats': rst},
        'by_day': [{'date': d, 'bets': b, 'turnover': t} for d, b, t in dates],
    })


@bp.get('/players/<int:pid>/sessions')
@require_auth()
def player_sessions(pid: int):
    """🕐 Лог сессий: длительность, спины, выиграл/проиграл. Игра — НАЗВАНИЕМ
    (any(GN(...))), не хешем. Тот же запрос, что в HTML-карточке (после фикса)."""
    denied = ensure_player_access(pid)   # anti-IDOR
    if denied:
        return denied
    if not _exists(pid):
        return api_json(error='player not found', code=404)
    sess = pb.q("SELECT any(" + pb.GN('game_uuid') + "), "
                "min(toTimezone(created_at,'Europe/Istanbul')), "
                "round(dateDiff('second', min(created_at), max(created_at))/60), "
                "countIf(transaction_type IN ('bet','freespins_bet')), "
                "round(sumIf(bet_amount,transaction_type IN ('bet','freespins_bet'))), "
                "round(sumIf(win_amount,transaction_type IN ('win','freespins_win'))) "
                "FROM game_transactions WHERE casino_player_id={pid:UInt32} AND session_id!='' "
                "GROUP BY session_id "
                "HAVING countIf(transaction_type IN ('bet','freespins_bet'))>0 "
                "ORDER BY min(created_at) DESC LIMIT 40", {'pid': pid})[1]
    srows = []
    for g, st, dur, sp, bet, win in sess:
        b, w = float(bet or 0), float(win or 0)
        srows.append({'game_name': str(g), 'started_at': st, 'duration_min': float(dur or 0),
                      'spins': sp, 'bet': b, 'win': w, 'net': w - b})
    # моментум (последняя форма) — как в борде: недавний net и серия проигрышей
    recent_net, loss_streak = 0.0, 0
    if srows:
        top = srows[0]['started_at']
        recent_net = sum(s['net'] for s in srows if (top - s['started_at']).days <= 14)
        for s in srows:
            if s['net'] < 0:
                loss_streak += 1
            else:
                break
    return api_json({'player_id': pid, 'count': len(srows), 'sessions': srows,
                     'momentum': {'recent_net_14d': recent_net, 'loss_streak': loss_streak}})


@bp.get('/players/<int:pid>/rhythm')
@require_auth()
def player_rhythm(pid: int):
    """🕐 Ритм ставок: распределение по дням недели / часам + тепловая карта
    день×час + статы (активные дни, пик, интервал, серия). Через pb._rhythm."""
    denied = ensure_player_access(pid)   # anti-IDOR
    if denied:
        return denied
    if not _exists(pid):
        return api_json(error='player not found', code=404)
    data, stats = pb._rhythm(
        "casino_player_id={pid:UInt32} AND transaction_type IN ('bet','freespins_bet')",
        {'pid': pid})
    return api_json({'player_id': pid, 'dow': data['dow'], 'hour': data['hour'],
                     'hm': data['hm'], 'stats': stats})


@bp.get('/players/<int:pid>/ltv')
@require_auth()
def player_ltv(pid: int):
    """💎 LTV-прогноз (тир/депозит 1-й недели/D90/headroom) + квантили P10/P50/P90
    + 🪜 лестница депозитов (где на ступени и шанс дойти дальше). Комплемент к
    summary (в summary есть pred_ltv_d90/headroom/early_tier, но нет квантилей и
    лестницы). Те же таблицы/поля, что в HTML-карточке."""
    denied = ensure_player_access(pid)   # anti-IDOR (LTV — денежный прогноз)
    if denied:
        return denied
    pf = pb.q("SELECT dep_count FROM player_features WHERE casino_player_id={pid:UInt32}",
              {'pid': pid})[1]
    if not pf:
        return api_json(error='player not found', code=404)
    dep_count = int(pf[0][0] or 0)

    lv = pb.q("SELECT days_since_ftd,tier_provisional,early_tier,dep_d7,pred_ltv_d30,"
              "pred_ltv_d90,pred_ltv_d120,ltv_headroom,ltv_is_ml "
              "FROM player_ltv WHERE casino_player_id={pid:UInt32}", {'pid': pid})[1]
    ltv = None
    if lv:
        ds, prov, tier, d7, p30, p90, p120, head, isml = lv[0]
        quant = None
        try:
            qn = pb.q("SELECT round(ltv_p10),round(ltv_p50),round(ltv_p90) "
                      "FROM player_ltv_quantiles WHERE casino_player_id={pid:UInt32}",
                      {'pid': pid})[1]
            if qn:
                quant = {'p10': qn[0][0], 'p50': qn[0][1], 'p90': qn[0][2]}
        except Exception:
            quant = None
        ltv = {'days_since_ftd': ds, 'provisional': bool(prov), 'tier': tier,
               'dep_d7': d7, 'pred_ltv_d30': p30, 'pred_ltv_d90': p90,
               'pred_ltv_d120': p120, 'headroom': head, 'is_ml': bool(isml),
               'quantiles': quant}

    ladder = None
    if dep_count >= 1:
        try:
            lad = pb.q("SELECT deposit_no, conv_to_next_pct FROM deposit_ladder "
                       "ORDER BY deposit_no")[1]
            cm = {int(no): cv for no, cv in lad}
            pnext = cm.get(dep_count) if dep_count <= 10 else None
            ppers = None
            try:
                pn = pb.q("SELECT round(p_next_deposit*100) FROM player_next_deposit_ml "
                          "WHERE casino_player_id={pid:UInt32}", {'pid': pid})[1]
                ppers = int(pn[0][0]) if pn else None
            except Exception:
                ppers = None
            ladder = {'current': dep_count, 'target': dep_count + 1,
                      'p_next_personal': ppers, 'p_next_base': pnext,
                      'steps': [{'deposit_no': int(no), 'conv_pct': cv} for no, cv in lad]}
        except Exception:
            ladder = None

    return api_json({'player_id': pid, 'is_depositor': dep_count > 0,
                     'ltv': ltv, 'ladder': ladder})


def _score_with_rank(table: str, col: str, pid: int, higher_is_hot: bool = True) -> dict | None:
    """Скор игрока из ML-витрины + перцентиль по популяции этой витрины.

    Перцентиль честнее абсолюта: у VIP-churn базовая частота ~0.75 и «0.86»
    сам по себе ни о чём — важно, что игрок рискованнее X% остальных VIP.
    higher_is_hot=False инвертирует (non_promising: НИЖЕ скор = перспективнее)."""
    try:
        mine = pb.q(f"SELECT {col} FROM {table} WHERE casino_player_id={{pid:UInt32}}",
                    {'pid': pid})[1]
        if not mine:
            return None
        val = float(mine[0][0])
        cmp_op = '<' if higher_is_hot else '>'
        rank = pb.q(f"SELECT round(100 * countIf({col} {cmp_op} {{v:Float64}}) / count()) "
                    f"FROM {table}", {'v': val})[1]
        return {'score': round(val, 4), 'pct_rank': int(rank[0][0]) if rank else None}
    except Exception:
        return None


@bp.get('/players/<int:pid>/vip-intel')
@require_auth(roles=MONEY_SECTION_ROLES)
def player_vip_intel(pid: int):
    """💠 VIP-скоры (инхаус-линейка): риск депозитного оттока VIP (30д),
    потенциал VIP по первой неделе (достигнет Gold за 90д), перспектива роста
    тира (инверсия non-promising). null = игрок не в населении модели
    (не VIP / не скорился). pct_rank — «горячее, чем N% популяции модели»."""
    denied = ensure_player_access(pid)   # anti-IDOR (денежная секция)
    if denied:
        return denied
    if not _exists(pid):
        return api_json(error='player not found', code=404)
    return api_json({
        'player_id': pid,
        # VIP при риске: выше скор = скорее перестанет депозитить
        'vip_churn': _score_with_rank('player_vip_churn_ml', 'p_vip_churn', pid),
        # будущий VIP по 1-й неделе: выше = вероятнее дойдёт до Gold
        'early_vip': _score_with_rank('player_early_vip_ml', 'p_early_vip', pid),
        # перспектива роста: НИЖЕ p_non_promising = вероятнее вырастет в тире
        'growth': _score_with_rank('player_non_promising_vip_ml', 'p_non_promising',
                                   pid, higher_is_hot=False),
    })


@bp.get('/players/<int:pid>/deposits')
@require_auth(roles=MAXBAL_ROLES)
def player_deposits(pid: int):
    """💳 Депозиты: когда вносил, сколько, как (способ/комментарий), тип, статус.
    Тот же запрос, что HTML-карточка (dep_sec, player_board.py). Ручной=бонус, не кэш.
    Роли = MAXBAL_ROLES: список депозитов — часть инструмента «макс-баланс» (режим А
    «от депозита», ТЗ фича 2), поэтому его видят и support/operator (anti-IDOR оставляет
    оператору только своих игроков)."""
    denied = ensure_player_access(pid)   # anti-IDOR (денежная секция)
    if denied:
        return denied
    if not _exists(pid):
        return api_json(error='player not found', code=404)
    # ?limit= — для селекта макс-баланса (режим А): последних 30 может не хватить,
    # если хвост попал в дыру потока (июль) — окна старше становятся недоступны.
    try:
        limit = min(max(int(request.args.get('limit', '30') or 30), 1), 300)
    except (TypeError, ValueError):
        limit = 30
    rows = pb.q(
        "SELECT formatDateTime(toTimezone(created_at,'Europe/Istanbul'),'%d.%m.%y %H:%i') ts, "
        "round(toFloat64(amount),2) amt, "
        "if(payment_method!='' AND payment_method NOT LIKE 'campaign:%', payment_method, description) how, "
        "type, status, toString(created_at) ts_raw "
        "FROM money_transactions WHERE casino_player_id={pid:UInt32} "
        "AND type IN ('deposit','manual_deposit') ORDER BY created_at DESC LIMIT {lim:UInt32}",
        {'pid': pid, 'lim': limit})[1]
    deposits = [{
        'ts': str(ts), 'amount': float(amt or 0), 'how': str(how or '—')[:28],
        'kind': 'ручной/бонус' if typ == 'manual_deposit' else 'депозит',
        'status': str(st), 'completed': st == 'completed',
        # ts_raw — ключ окна для /max-balance (режим А «от депозита»), сырое время хранения
        'ts_raw': str(raw),
    } for ts, amt, how, typ, st, raw in rows]
    return api_json({'player_id': pid, 'count': len(deposits), 'deposits': deposits})


@bp.get('/players/<int:pid>/bonuses')
@require_auth(roles=BONUS_BLOCK_ROLES)
def player_bonuses(pid: int):
    """🎁 Бонусы (ТЗ фича 1): сводка по статусам + таблица выдач + «депозит ≤N дней
    после» (окно BONUS_REACTION_DAYS). Статусы цикла (активирован/отыгран/сгорел) —
    из bonus_status_current (поток bonus_status); пока казино цикл не шлёт,
    статус = «выдан», остальное честно «нет данных» (lifecycle=false).
    Фильтры таблицы: ?status=a,b&type=x,y&from=YYYY-MM-DD&to=YYYY-MM-DD (даты
    Стамбула, «дата выдачи»). Сводка — всегда по ВСЕМ бонусам игрока, без фильтров."""
    denied = ensure_player_access(pid)   # anti-IDOR (денежная секция)
    if denied:
        return denied
    if not _exists(pid):
        return api_json(error='player not found', code=404)
    bon = pb.q(
        "SELECT b.created_at, toString(b.created_at), "
        "formatDateTime(toTimezone(b.created_at,'Europe/Istanbul'),'%d.%m.%y %H:%i'), "
        "b.type, "
        "multiIf(b.type='freespin','freespins', b.description ILIKE '%deneme%','no-deposit', "
        "b.description ILIKE '%kay%p%','cashback', "
        "b.description ILIKE '%dsc%' OR b.description ILIKE '%yat%','deposit-match','other'), "
        "b.description, round(toFloat64(b.amount),2), b.currency, "
        "s.status, toString(s.last_status_at), "
        "toFloat64(ifNull(s.wager_requirement,0)), toFloat64(ifNull(s.wager_multiplier,0)), "
        "toFloat64(ifNull(s.wagered_amount,0)) "
        "FROM money_transactions b "
        "LEFT JOIN (SELECT * FROM bonus_status_current "
        "           WHERE casino_player_id={pid:UInt32} AND money_transaction_id!='') s "
        "ON s.money_transaction_id = b.transaction_id "
        "WHERE b.casino_player_id={pid:UInt32} AND b.type IN ('freespin','manual_bonus','bonus') "
        "AND b.status='completed' ORDER BY b.created_at DESC LIMIT 1000", {'pid': pid})[1]
    if not bon:
        return api_json({'player_id': pid, 'count': 0, 'bonuses': [],
                         'window_days': BONUS_REACTION_DAYS, 'lifecycle_available': False,
                         'types': [], 'summary': None})
    deps = pb.q(
        "SELECT created_at, toFloat64(amount) FROM money_transactions "
        "WHERE casino_player_id={pid:UInt32} "
        "AND type IN ('deposit','manual_deposit') AND status='completed'", {'pid': pid})[1]

    import datetime as _dt
    win = _dt.timedelta(days=BONUS_REACTION_DAYS)
    ist = _dt.timedelta(hours=3)                      # хранение UTC → дата выдачи Стамбула
    all_rows = []
    for bts, raw, ts_h, tx_type, btype, name, amt, cur, st, st_at, wreq, wmul, wprog in bon:
        after = [(dd, da) for dd, da in deps if bts < dd <= bts + win]
        lifecycle = st is not None and str(st) != ''
        all_rows.append({
            'ts': str(ts_h), 'ts_raw': str(raw),
            'issue_date_ist': (bts + ist).date().isoformat(),
            'type': str(btype), 'tx_type': str(tx_type),
            'name': str(name or '')[:80] or None,
            'amount': float(amt or 0), 'currency': str(cur or 'TRY'),
            'status': str(st) if lifecycle else 'issued',
            'lifecycle': lifecycle,
            'status_at': str(st_at) if lifecycle else None,
            'wager_requirement': float(wreq or 0) or None,
            'wager_multiplier': float(wmul or 0) or None,
            'wagered_amount': float(wprog or 0) if lifecycle else None,
            'dep_after': bool(after),
            'dep_after_count': len(after),
            'dep_after_sum': round(sum(da for _, da in after), 2),
        })

    # сводка — по всем бонусам (не фильтруется): «Выдано · Активировано · …»
    by = lambda s: sum(1 for r in all_rows if r['status'] == s and r['lifecycle'])  # noqa: E731
    dep_hit = {dd for bts, *_ in bon for dd, _ in deps if bts < dd <= bts + win}
    summary = {
        'issued': len(all_rows),
        'activated': by('activated'),
        'wagering_completed': by('wagering_completed'),
        'expired': by('expired'),
        'cancelled': by('cancelled'),
        'bonus_cost': round(sum(r['amount'] for r in all_rows), 2),
        'deps_after_count': len(dep_hit),
        'deps_after_sum': round(sum(da for dd, da in deps if dd in dep_hit), 2),
    }

    # фильтры таблицы (комбинируются; состояние живёт в URL на стороне SPA)
    f_status = {s for s in (request.args.get('status') or '').split(',') if s}
    f_type = {s for s in (request.args.get('type') or '').split(',') if s}
    f_from = (request.args.get('from') or '').strip()
    f_to = (request.args.get('to') or '').strip()
    f_react = (request.args.get('reaction') or '').strip()   # ''|yes|no — был ли депозит в окне
    rows = [r for r in all_rows
            if (not f_status or r['status'] in f_status)
            and (not f_type or r['type'] in f_type)
            and (not f_from or r['issue_date_ist'] >= f_from)
            and (not f_to or r['issue_date_ist'] <= f_to)
            and (not f_react or r['dep_after'] == (f_react == 'yes'))]

    return api_json({
        'player_id': pid, 'count': len(rows), 'bonuses': rows,
        'window_days': BONUS_REACTION_DAYS,
        'lifecycle_available': any(r['lifecycle'] for r in all_rows),
        'types': sorted({r['type'] for r in all_rows}),
        'summary': summary,
    })


@bp.get('/players/<int:pid>/max-balance')
@require_auth(roles=MAXBAL_ROLES)
def player_max_balance(pid: int):
    """💹 Макс-баланс за период (ТЗ фича 2, «закрывает рот»).
    Режим А: ?deposit_ts=<ts_raw из /deposits> — окно [депозит; следующий депозит),
    без следующего — «по текущий момент». Режим Б: ?from=&to= (datetime-local,
    время Стамбула, Istanbul = UTC+3 без DST). Максимум — по РЕАЛЬНОМУ кошельку:
    спины balance_source='money' + балансы после денежных операций (депозит мог
    поднять баланс выше любого «после спина»)."""
    denied = ensure_player_access(pid)   # anti-IDOR (инструмент разговора с игроком)
    if denied:
        return denied
    if not _exists(pid):
        return api_json(error='player not found', code=404)

    import datetime as _dt
    dep_ts = (request.args.get('deposit_ts') or '').strip()
    deposit = None
    open_ended = False
    if dep_ts:                                           # ── режим А «от депозита»
        drow = pb.q(
            "SELECT toString(created_at), round(toFloat64(amount),2) "
            "FROM money_transactions WHERE casino_player_id={pid:UInt32} "
            "AND type IN ('deposit','manual_deposit') AND status='completed' "
            "AND toString(created_at)={dts:String} LIMIT 1",
            {'pid': pid, 'dts': dep_ts})[1]
        if not drow:
            return api_json(error='deposit not found', code=404)
        deposit = {'ts_raw': str(drow[0][0]), 'amount': float(drow[0][1])}
        w_from = dep_ts
        # следующий депозит: minOrNull → None, если депозит был последним (окно «по сейчас»);
        # toString(min(...)) НЕ годится — пустой min рендерится epoch'ом в timezone сервера
        nxt = pb.q(
            "SELECT toString(minOrNull(created_at)) FROM money_transactions "
            "WHERE casino_player_id={pid:UInt32} AND type IN ('deposit','manual_deposit') "
            "AND status='completed' AND created_at > toDateTime64({dts:String},3)",
            {'pid': pid, 'dts': dep_ts})[1]
        w_to = str(nxt[0][0]) if nxt and nxt[0][0] else ''
        if not w_to:
            open_ended = True
            w_to = '2100-01-01 00:00:00'
    else:                                                # ── режим Б «произвольный период»
        f_raw = (request.args.get('from') or '').strip()
        t_raw = (request.args.get('to') or '').strip()
        if not f_raw or not t_raw:
            return api_json(error='need deposit_ts or from+to', code=400)
        try:
            f_dt = _dt.datetime.fromisoformat(f_raw)
            t_dt = _dt.datetime.fromisoformat(t_raw)
        except ValueError:
            return api_json(error='bad datetime format', code=400)
        if f_dt >= t_dt:                                 # ТЗ: «от > до» — валидация, не считать
            return api_json(error='from must be before to', code=400)
        if (t_dt - f_dt).days > 400:                     # защита карточки от бесконечного окна
            return api_json(error='period too long (max 400 days)', code=400)
        # ввод — время Стамбула (UTC+3, DST нет) → базис хранения (UTC), без tz-функций,
        # чтобы не зависеть от server timezone ClickHouse (локально ≠ VPS)
        w_from = (f_dt - _dt.timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
        w_to = (t_dt - _dt.timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')

    # Максимум считается по ОБОИМ срезам каждой операции: balance_after И
    # balance_before (точка «до операции», ts−1мс). Иначе депозит, слитый первой же
    # ставкой целиком, не попадает в пик (кейс игрока #1888: деп 2000 → одна ставка
    # 2000 → «макс 151» выглядел абсурдом). n/bets — только по after-точкам,
    # семантика «сколько операций было» не меняется.
    agg = pb.q(
        "WITH gt AS ("
        "  SELECT created_at, toFloat64(balance_after) AS bal, "
        "         toUInt8(transaction_type IN ('bet','freespins_bet')) AS is_bet, toUInt8(1) AS is_after "
        "  FROM game_transactions "
        "  WHERE casino_player_id={pid:UInt32} AND balance_source='money' "
        "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
        "  UNION ALL "
        "  SELECT created_at - toIntervalMillisecond(1), toFloat64(balance_before), toUInt8(0), toUInt8(0) "
        "  FROM game_transactions "
        "  WHERE casino_player_id={pid:UInt32} AND balance_source='money' AND balance_before IS NOT NULL "
        "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
        "), mt AS ("
        "  SELECT created_at, toFloat64(balance_after) AS bal, toUInt8(0) AS is_bet, toUInt8(1) AS is_after "
        "  FROM money_transactions "
        "  WHERE casino_player_id={pid:UInt32} AND balance_after IS NOT NULL AND status='completed' "
        "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
        "  UNION ALL "
        "  SELECT created_at - toIntervalMillisecond(1), toFloat64(balance_before), toUInt8(0), toUInt8(0) "
        "  FROM money_transactions "
        "  WHERE casino_player_id={pid:UInt32} AND balance_before IS NOT NULL AND status='completed' "
        "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
        "), u AS (SELECT * FROM gt UNION ALL SELECT * FROM mt) "
        "SELECT countIf(is_after), round(max(bal),2), toString(argMax(created_at, bal)), "
        "sum(is_bet), round(argMin(bal, created_at),2), round(argMax(bal, created_at),2), "
        "toString(min(created_at)), toString(max(created_at)) "
        "FROM u", {'pid': pid, 'wf': w_from, 'wt': w_to})[1]
    n, mx, peak_at, bets, start_bal, end_bal, first_ts, last_ts = agg[0]

    # Бонусный кошелёк тем же способом: если реальным кошельком в окне не играли
    # (чисто бонусная игра и/или money-операции без баланса — июльский пробел),
    # честно показываем бонусную траекторию вместо «нет данных».
    bagg = pb.q(
        "WITH gt AS ("
        "  SELECT created_at, toFloat64(balance_after) AS bal "
        "  FROM game_transactions "
        "  WHERE casino_player_id={pid:UInt32} AND balance_source IN ('bonus','freespin') "
        "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
        "  UNION ALL "
        "  SELECT created_at - toIntervalMillisecond(1), toFloat64(balance_before) "
        "  FROM game_transactions "
        "  WHERE casino_player_id={pid:UInt32} AND balance_source IN ('bonus','freespin') AND balance_before IS NOT NULL "
        "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
        "), mt AS ("
        "  SELECT created_at, toFloat64(bonus_balance_after) AS bal "
        "  FROM money_transactions "
        "  WHERE casino_player_id={pid:UInt32} AND bonus_balance_after IS NOT NULL AND status='completed' "
        "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
        "  UNION ALL "
        "  SELECT created_at - toIntervalMillisecond(1), toFloat64(bonus_balance_before) "
        "  FROM money_transactions "
        "  WHERE casino_player_id={pid:UInt32} AND bonus_balance_before IS NOT NULL AND status='completed' "
        "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
        "), u AS (SELECT * FROM gt UNION ALL SELECT * FROM mt) "
        "SELECT count(), round(max(bal),2), toString(argMax(created_at, bal)), "
        "round(argMin(bal, created_at),2), round(argMax(bal, created_at),2), "
        "toString(min(created_at)), toString(max(created_at)) "
        "FROM u", {'pid': pid, 'wf': w_from, 'wt': w_to})[1]
    bn, bmx, bpeak_at, bstart_bal, bend_bal, bfirst_ts, blast_ts = bagg[0]

    # Различаем ДВА случая пустого баланса (иначе подсказка вводит в заблуждение):
    #   — ставок в окне вообще не было → «активности не было» (честно пусто);
    #   — ставки БЫЛИ, но без balance_source/balance_after → казино с 03.07.2026
    #     перестало слать остаток кошелька в спинах (внешний пробел потока, НЕ наш
    #     баг и НЕ «не догружено»: сами ставки пришли, баланс в них — нет).
    spins_no_balance = 0
    if not (n or bn):
        sr = pb.q(
            "SELECT count() FROM game_transactions "
            "WHERE casino_player_id={pid:UInt32} AND status='completed' "
            "AND transaction_type IN ('bet','freespins_bet','win','freespins_win') "
            "AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)",
            {'pid': pid, 'wf': w_from, 'wt': w_to})[1]
        spins_no_balance = int(sr[0][0] or 0) if sr else 0

    # спарклайн «горки» + траектории обоих кошельков (реальный/бонусный):
    # окно режется на ≤120 корзин; в корзине траектория = последний баланс
    # (argMax по времени), горка = максимум. Бонусный кошелёк: спины с
    # balance_source bonus/freespin + bonus_balance_after денежных операций.
    spark: list[float] = []
    series = None
    if n or bn:
        try:
            # окно графика — по объединению обоих кошельков (реальный мог быть пуст)
            _cands_lo = [s for s in (first_ts if n else None, bfirst_ts if bn else None) if s]
            _cands_hi = [s for s in (last_ts if n else None, blast_ts if bn else None) if s]
            t0 = min(_dt.datetime.fromisoformat(str(s).split('.')[0]) for s in _cands_lo)
            t1 = max(_dt.datetime.fromisoformat(str(s).split('.')[0]) for s in _cands_hi)
            bsec = max(60, int((t1 - t0).total_seconds() // 120) or 60)
            # в корзины входят и before-точки (ts−1мс) — иначе горка прячет пик
            # «деньги легли и тут же слиты одной ставкой» (кейс #1888)
            real = pb.q(
                "WITH gt AS ("
                "  SELECT created_at, toFloat64(balance_after) AS bal "
                "  FROM game_transactions "
                "  WHERE casino_player_id={pid:UInt32} AND balance_source='money' "
                "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
                "  UNION ALL "
                "  SELECT created_at - toIntervalMillisecond(1), toFloat64(balance_before) "
                "  FROM game_transactions "
                "  WHERE casino_player_id={pid:UInt32} AND balance_source='money' AND balance_before IS NOT NULL "
                "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
                "), mt AS ("
                "  SELECT created_at, toFloat64(balance_after) AS bal "
                "  FROM money_transactions "
                "  WHERE casino_player_id={pid:UInt32} AND balance_after IS NOT NULL AND status='completed' "
                "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
                "  UNION ALL "
                "  SELECT created_at - toIntervalMillisecond(1), toFloat64(balance_before) "
                "  FROM money_transactions "
                "  WHERE casino_player_id={pid:UInt32} AND balance_before IS NOT NULL AND status='completed' "
                "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
                "), u AS (SELECT * FROM gt UNION ALL SELECT * FROM mt) "
                "SELECT toStartOfInterval(created_at, INTERVAL {bsec:UInt32} SECOND) AS b, "
                "round(argMax(bal, created_at),2) AS traj, round(max(bal),2) AS mx "
                "FROM u GROUP BY b ORDER BY b",
                {'pid': pid, 'wf': w_from, 'wt': w_to, 'bsec': bsec})[1]
            bonus = pb.q(
                "WITH gt AS ("
                "  SELECT created_at, toFloat64(balance_after) AS bal "
                "  FROM game_transactions "
                "  WHERE casino_player_id={pid:UInt32} AND balance_source IN ('bonus','freespin') "
                "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
                "  UNION ALL "
                "  SELECT created_at - toIntervalMillisecond(1), toFloat64(balance_before) "
                "  FROM game_transactions "
                "  WHERE casino_player_id={pid:UInt32} AND balance_source IN ('bonus','freespin') AND balance_before IS NOT NULL "
                "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
                "), mt AS ("
                "  SELECT created_at, toFloat64(bonus_balance_after) AS bal "
                "  FROM money_transactions "
                "  WHERE casino_player_id={pid:UInt32} AND bonus_balance_after IS NOT NULL AND status='completed' "
                "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
                "  UNION ALL "
                "  SELECT created_at - toIntervalMillisecond(1), toFloat64(bonus_balance_before) "
                "  FROM money_transactions "
                "  WHERE casino_player_id={pid:UInt32} AND bonus_balance_before IS NOT NULL AND status='completed' "
                "    AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)"
                "), u AS (SELECT * FROM gt UNION ALL SELECT * FROM mt) "
                "SELECT toStartOfInterval(created_at, INTERVAL {bsec:UInt32} SECOND) AS b, "
                "round(max(bal),2) FROM u GROUP BY b ORDER BY b",
                {'pid': pid, 'wf': w_from, 'wt': w_to, 'bsec': bsec})[1]
            # линии — по МАКСИМУМУ корзины (верхняя огибающая): «последнее значение»
            # прятало бы пик, слитый внутри той же корзины, а вопрос — «сколько было»
            rmap = {b: (float(traj), float(mx)) for b, traj, mx in real}
            bmap = {b: float(v) for b, v in bonus}
            buckets = sorted(set(rmap) | set(bmap))
            ist3 = _dt.timedelta(hours=3)
            series = {
                'labels': [(b + ist3).strftime('%d.%m %H:%M') for b in buckets],
                'real': [rmap[b][1] if b in rmap else None for b in buckets],
                'bonus': [bmap.get(b) for b in buckets],
            }
            spark = [rmap[b][1] for b in buckets if b in rmap]
        except Exception:
            spark, series = [], None

    dw = pb.q(
        "SELECT count(), round(sum(toFloat64(amount)),2) FROM money_transactions "
        "WHERE casino_player_id={pid:UInt32} AND type IN ('deposit','manual_deposit') "
        "AND status='completed' "
        "AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3)",
        {'pid': pid, 'wf': w_from, 'wt': w_to})[1]

    # журнал изменений периода (запрос владельца: «когда и сколько, включая
    # бонусы — текстом, не только графиком»): все денежные операции окна
    ev_rows = pb.q(
        "SELECT toString(created_at), type, round(toFloat64(abs(amount)),2), "
        "toFloat64(balance_after), toFloat64(bonus_balance_after), "
        # тип бонуса — та же типизация, что в блоке «Бонусы» (bonus_sec борда)
        "multiIf(type='freespin','freespins', description ILIKE '%deneme%','no-deposit', "
        "description ILIKE '%kay%p%','cashback', "
        "description ILIKE '%dsc%' OR description ILIKE '%yat%','deposit-match','other'), "
        "description, "
        # платёжка (как в списке депозитов): campaign-теги — не платёжка
        "if(payment_method!='' AND payment_method NOT LIKE 'campaign:%', payment_method, '') "
        "FROM money_transactions "
        "WHERE casino_player_id={pid:UInt32} AND status='completed' "
        "AND type IN ('deposit','manual_deposit','withdrawal','manual_withdrawal',"
        "'bonus','manual_bonus','freespin') "
        "AND created_at >= toDateTime64({wf:String},3) AND created_at < toDateTime64({wt:String},3) "
        "ORDER BY created_at LIMIT 300",
        {'pid': pid, 'wf': w_from, 'wt': w_to})[1]
    _KIND = {'deposit': 'deposit', 'manual_deposit': 'manual_deposit',
             'withdrawal': 'withdrawal', 'manual_withdrawal': 'withdrawal',
             'bonus': 'bonus', 'manual_bonus': 'bonus', 'freespin': 'bonus'}
    events = []
    for ts, typ, amt, ba, bba, btype, descr, method in ev_rows:
        kind = _KIND.get(str(typ), str(typ))
        events.append({
            'ts': (_dt.datetime.fromisoformat(str(ts).split('.')[0])
                   + _dt.timedelta(hours=3)).strftime('%d.%m %H:%M'),
            'kind': kind,
            'amount': float(amt or 0),
            'balance_after': float(ba) if ba is not None else None,
            'bonus_balance_after': float(bba) if bba is not None else None,
            # какой именно бонус дали (запрос владельца): тип + название из описания
            'btype': str(btype) if kind == 'bonus' else None,
            # через какую платёжку пополнил/вывел (запрос владельца)
            'method': (str(method) or None) if kind != 'bonus' else None,
            'name': (str(descr).strip()[:80] or None) if descr else None,
        })
    bonus_events = [e for e in events if e['kind'] == 'bonus']

    fmt_ist = lambda s: (_dt.datetime.fromisoformat(s.split('.')[0])   # noqa: E731
                         + _dt.timedelta(hours=3)).strftime('%d.%m.%y %H:%M')
    if deposit:
        deposit['ts'] = fmt_ist(deposit['ts_raw'])
    return api_json({
        'player_id': pid,
        'mode': 'deposit' if deposit else 'range',
        'deposit': deposit,
        'window': {'from': fmt_ist(w_from), 'to': None if open_ended else fmt_ist(w_to),
                   'open_ended': open_ended},
        # «данные есть», если в окне была игра ЛЮБЫМ кошельком: чисто бонусные окна
        # (и июльские money-операции без баланса) раньше падали в «нет данных»
        'has_data': int(n or 0) > 0 or int(bn or 0) > 0,
        'max_balance': float(mx) if n else None,
        'peak_at': fmt_ist(str(peak_at)) if n else None,
        'start_balance': float(start_bal) if n else None,
        'end_balance': float(end_bal) if n else None,
        # сводка бонусного кошелька (для окон без реальной игры и вех графика)
        'bonus_wallet': ({
            'n': int(bn), 'max': float(bmx), 'peak_at': fmt_ist(str(bpeak_at)),
            'start': float(bstart_bal), 'end': float(bend_bal),
        } if bn else None),
        'bets': int(bets or 0),
        'no_spins': int(bets or 0) == 0,                 # ТЗ: «ставок не было — макс = баланс после депозита»
        # ставки в окне были, но БЕЗ данных о балансе (казино не шлёт остаток
        # кошелька с 03.07.2026) — фронт объясняет это точно, а не «нет активности»
        'spins_no_balance': spins_no_balance,
        'deposits_count': int(dw[0][0] or 0),
        'deposits_sum': float(dw[0][1] or 0),
        'spark': spark,                                  # «горка» реального кошелька (мини)
        'series': series,                                # траектории обоих кошельков (график)
        'events': events,                                # журнал операций окна (текстом)
        'bonus_count': len(bonus_events),
        'bonus_sum': round(sum(e['amount'] for e in bonus_events), 2),
        'wallet': 'real',                                # balance_source='money' — реальный кошелёк
    })


# ════════════════════════════════════════════════════════════════════════════
# ЭКСПОРТ СЕГМЕНТА  (идентичен /players.csv и /players.xlsx — те же колонки/строки)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/players/export.csv')
@require_auth(roles=EXPORT_ROLES)
def players_export_csv():
    """CSV сегмента = ровно то, что отдаёт HTML-роут /players.csv на тех же
    фильтрах (переиспускаем _export_rows / _EXPORT_COLS / _export_name)."""
    W, params, flt = pb._players_filter(request.args)
    rows = pb._export_rows(W, params)
    pb._export_log(flt, 'csv', len(rows))
    out = ['﻿' + ';'.join(pb._EXPORT_COLS)]   # BOM — Excel открывает UTF-8 без кракозябр
    for r in rows:
        out.append(';'.join('' if v is None else str(v) for v in r))
    return Response('\r\n'.join(out), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition':
                             f'attachment; filename="{pb._export_name(flt, "csv")}"'})


@bp.get('/players/export.xlsx')
@require_auth(roles=EXPORT_ROLES)
def players_export_xlsx():
    """XLSX сегмента = ровно то, что отдаёт HTML-роут /players.xlsx."""
    from openpyxl import Workbook
    W, params, flt = pb._players_filter(request.args)
    rows = pb._export_rows(W, params)
    pb._export_log(flt, 'xlsx', len(rows))
    wb = Workbook()
    ws = wb.active
    ws.title = 'players'
    ws.append(pb._EXPORT_COLS)
    for r in rows:
        ws.append(list(r))
    ws.freeze_panes = 'A2'
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        buf.read(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':
                 f'attachment; filename="{pb._export_name(flt, "xlsx")}"'})
