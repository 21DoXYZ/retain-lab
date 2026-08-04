"""api/traffic.py — JSON-домен «Трафик»: вердикты по источникам/аффилиатам (W2-T2).

Headless-обёртка над готовыми данными player_board.py + витринами retention.*.
Логика/формулы НЕ переписаны — берём константы и helper'ы из `player_board`
(одни данные — одни цифры). Считает «прогноз качества когорты на 5-й день»:
для каждого источника трафика (registration_source) или аффилиата (affiliate_code)
берётся когорта регистраций за последние N дней и выносится вердикт
scale/watch/disable/maturing на основе прогноза LTV D90 (retention.player_ltv),
квантильного диапазона (player_ltv_quantiles) и реального GGR когорты.

Эндпоинт (под /api/v1):
  GET /api/v1/traffic/verdicts?dim=source|affiliate&days=30
    → {rows: [...], meta: {asof, median_ltv, global_ftd_rate}}

Роли — тот же набор, что у внутренних видов трафика (пункт affiliates, AFF_ROLES).

CH-конвенции: окно дат — от max(reg_date) в данных (датасет живёт по 15.07.2026,
не от now()); наивная арифметика по toDate (server tz = Asia/Makassar — никаких
tz-функций в оконных фильтрах); LEFT/INNER JOIN отсутствие даёт 0, не NULL.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from .core import require_auth, api_json
import player_board as pb  # готовые helper-функции и константы борда

bp = Blueprint('api_traffic', __name__, url_prefix='/api/v1')

# ── матрица ролей (внутренние админ-виды трафика; как у пункта affiliates) ──
TRAFFIC_ROLES = ['super_admin', 'head_retention', 'director',
                 'affiliate_manager', 'finance', 'analyst']

# ════════════════════════════════════════════════════════════════════════════
# Пороги вердикта — ЧЕРНОВЫЕ, согласовать с Василием (оригинал — в демо-файле).
# Держим константами вверху файла, чтобы правка порогов не трогала логику.
# ════════════════════════════════════════════════════════════════════════════
MATURING_AGE_DAYS = 5        # когорта моложе → «зреет», вердикт не выносим
MATURING_MIN_PLAYERS = 10    # игроков меньше → «зреет» (мало данных)
DISABLE_LTV_FACTOR = 0.5     # pred_d90_avg ниже 0.5× медианы → отключить
SCALE_LTV_FACTOR = 1.5       # pred_d90_avg выше 1.5× медианы → масштабировать
CONF_HIGH_PLAYERS = 50       # high-уверенность требует ≥ стольких игроков
CONF_LOW_PLAYERS = 20        # игроков меньше → low-уверенность
CONF_SPREAD_MAX = 1.5        # (p90−p10)/pred_d90_sum ниже → узкий разброс

_ALLOWED_DAYS = (7, 14, 30, 90)


def _verdict(age_days: int, players: int, ggr_real: float, pred_avg: float,
             ftd_rate: float, median_ltv: float, global_ftd_rate: float) -> str:
    """Вердикт по источнику. Порядок важен: сначала гард «зреет» (мало данных),
    затем «отключить» (бьёт кассу / низкий прогноз), «масштабировать», иначе
    «наблюдать»."""
    if age_days < MATURING_AGE_DAYS or players < MATURING_MIN_PLAYERS:
        return 'maturing'
    if ggr_real < 0 or pred_avg < DISABLE_LTV_FACTOR * median_ltv:
        return 'disable'
    if pred_avg > SCALE_LTV_FACTOR * median_ltv and ftd_rate >= global_ftd_rate:
        return 'scale'
    return 'watch'


def _confidence(players: int, p10_sum: float, p90_sum: float, pred_sum: float) -> str:
    """Уверенность вердикта: high — много игроков и узкий P10–P90; low — мало
    игроков; иначе mid."""
    spread = (p90_sum - p10_sum) / max(pred_sum, 1.0)
    if players >= CONF_HIGH_PLAYERS and spread < CONF_SPREAD_MAX:
        return 'high'
    if players < CONF_LOW_PLAYERS:
        return 'low'
    return 'mid'


# Кэш вердиктов: тяжёлый скан game_transactions на каждый запрос не нужен —
# датасет статичен между прогонами лупа. Ключ включает max(reg_date), поэтому
# при появлении новых данных кэш инвалидируется сам (паттерн _COHORTS_CACHE).
_VERDICTS_CACHE: dict = {}
_VERDICTS_CACHE_MAX = 24   # 2 dim × 4 days × запас по датам


@bp.get('/traffic/verdicts')
@require_auth(roles=TRAFFIC_ROLES)
def traffic_verdicts():
    """Вердикты по источникам (dim=source) или аффилиатам (dim=affiliate).

    Когорта = игроки users с регистрацией за последние `days` дней (окно — от
    max(reg_date) в датасете, не от now). Для каждого источника: игроков/7д, FTD,
    депозиты, прогноз LTV D90 (сумма и на игрока по скоренным), диапазон P10–P90,
    реальный GGR когорты, возраст (дней с медианной даты регистрации), вердикт и
    уверенность."""
    dim = request.args.get('dim', 'source')
    if dim not in ('source', 'affiliate'):
        dim = 'source'
    try:
        days = int(request.args.get('days', '30'))
    except (TypeError, ValueError):
        days = 30
    if days not in _ALLOWED_DAYS:
        days = 30

    # окно: от максимальной reg_date в данных (датасет живёт по 15.07.2026 —
    # от now() когорта была бы пустой). Наивная арифметика, без tz-функций.
    dmax_row = pb.q("SELECT toDate(max(reg_date)) FROM users "
                    "WHERE account_type='normal' AND reg_date IS NOT NULL")[1]
    dmax = dmax_row[0][0] if dmax_row and dmax_row[0][0] else None
    if dmax is None:
        return api_json({'rows': [], 'meta': {'asof': None, 'median_ltv': 0.0,
                        'global_ftd_rate': 0.0, 'days': days, 'dim': dim}})
    cache_key = (dim, days, dmax)
    cached = _VERDICTS_CACHE.get(cache_key)
    if cached is not None:
        return api_json(cached)
    dmin = dmax - timedelta(days=days - 1)
    d7 = dmax - timedelta(days=6)
    DMAX, DMIN, D7 = dmax.isoformat(), dmin.isoformat(), d7.isoformat()

    DIM = "substring(registration_source,1,42)" if dim == 'source' else "affiliate_code"
    COH = (f"account_type='normal' AND reg_date IS NOT NULL "
           f"AND toDate(reg_date) BETWEEN '{DMIN}' AND '{DMAX}'")
    if dim == 'affiliate':
        COH += " AND affiliate_code != ''"
    COHSUB = f"(SELECT casino_player_id, {DIM} grp FROM users WHERE {COH})"

    # 1) регистрационная база когорты: игроки / 7д / FTD / медианный возраст
    _, base = pb.q(f"""SELECT {DIM} grp,
        uniqExact(casino_player_id) players,
        countIf(toDate(reg_date) >= '{D7}') players_7d,
        countIf(ftd_date IS NOT NULL) ftd,
        round(sumIf(toFloat64(ftd_amount), ftd_amount>0)) ftd_sum,
        dateDiff('day', toDate(median(reg_date)), toDate('{DMAX}')) age_days
      FROM users WHERE {COH} GROUP BY grp""")

    # 2) депозиты когорты (спека казино: DEP_OK — кэш-депозит, completed)
    _, mny = pb.q(f"""SELECT u.grp, round(sumIf(m.amount, {pb.DEP_OK}),2) dep
      FROM money_transactions m INNER JOIN {COHSUB} u USING(casino_player_id)
      GROUP BY u.grp""")

    # 3) ggr_real когорты — реальные ставки − выигрыши (completed), как в аффилиатах
    _, gg = pb.q(f"""SELECT u.grp,
        round(sumIf(g.bet_amount, g.transaction_type='bet' AND g.status='completed')
            - sumIf(g.win_amount, g.transaction_type='win' AND g.status='completed'),2) ggr_real
      FROM game_transactions g INNER JOIN {COHSUB} u USING(casino_player_id)
      GROUP BY u.grp""")

    # 4) прогноз LTV D90 — сумма и число скоренных (avg = sum/scored)
    _, lt = pb.q(f"""SELECT u.grp, round(sum(l.pred_ltv_d90)) pred_sum, count() scored
      FROM player_ltv l INNER JOIN {COHSUB} u USING(casino_player_id)
      GROUP BY u.grp""")

    # 5) квантильный диапазон P10/P90 (честно про разброс прогноза)
    _, qn = pb.q(f"""SELECT u.grp, round(sum(q.ltv_p10)) p10, round(sum(q.ltv_p90)) p90
      FROM player_ltv_quantiles q INNER JOIN {COHSUB} u USING(casino_player_id)
      GROUP BY u.grp""")

    # глобальные ориентиры (по всем скоренным / всей нормальной базе)
    _med = pb.q("SELECT round(median(pred_ltv_d90)) FROM player_ltv")[1]
    median_ltv = float(_med[0][0] or 0) if _med else 0.0
    _fr = pb.q("SELECT count(), countIf(ftd_date IS NOT NULL) "
               "FROM users WHERE account_type='normal'")[1][0]
    global_ftd_rate = (float(_fr[1]) / float(_fr[0])) if _fr and _fr[0] else 0.0

    MNY = {r[0]: r for r in mny}
    GG = {r[0]: r for r in gg}
    LT = {r[0]: r for r in lt}
    QN = {r[0]: r for r in qn}

    rows = []
    for (grp, players, players_7d, ftd, ftd_sum, age_days) in base:
        players = int(players or 0)
        ftd = int(ftd or 0)
        dep = float(MNY[grp][1] or 0) if grp in MNY else 0.0
        ggr_real = float(GG[grp][1] or 0) if grp in GG else 0.0
        pred_sum = float(LT[grp][1] or 0) if grp in LT else 0.0
        scored = int(LT[grp][2] or 0) if grp in LT else 0
        pred_avg = (pred_sum / scored) if scored else 0.0
        p10_sum = float(QN[grp][1] or 0) if grp in QN else 0.0
        p90_sum = float(QN[grp][2] or 0) if grp in QN else 0.0
        age = int(age_days or 0)
        ftd_rate = (ftd / players) if players else 0.0

        rows.append({
            'source': grp or '—',
            'players': players,
            'players_7d': int(players_7d or 0),
            'ftd': ftd,
            'ftd_sum': float(ftd_sum or 0),
            'deposits': dep,
            'pred_d90_sum': pred_sum,
            'pred_d90_avg': round(pred_avg, 2),
            'p10_sum': p10_sum,
            'p90_sum': p90_sum,
            'ggr_real': ggr_real,
            'age_days': age,
            'verdict': _verdict(age, players, ggr_real, pred_avg, ftd_rate,
                                median_ltv, global_ftd_rate),
            'confidence': _confidence(players, p10_sum, p90_sum, pred_sum),
        })

    rows.sort(key=lambda r: r['players'], reverse=True)

    payload = {'rows': rows, 'meta': {
        'asof': DMAX,
        'median_ltv': median_ltv,
        'global_ftd_rate': round(global_ftd_rate, 4),
        'days': days,
        'dim': dim,
        'window': {'from': DMIN, 'to': DMAX},
    }}
    if len(_VERDICTS_CACHE) >= _VERDICTS_CACHE_MAX:
        _VERDICTS_CACHE.clear()
    _VERDICTS_CACHE[cache_key] = payload
    return api_json(payload)
