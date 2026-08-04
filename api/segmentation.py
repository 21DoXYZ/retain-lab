"""api/segmentation.py — JSON-API домена «Сегментация» (агент C3).

Экраны SPA, обслуживаемые этим модулем (эталон — живой борд :8050):
  GET /api/v1/cohorts     — каталог когорт (все срезы A1..G29a), «36 срезов»
  GET /api/v1/rfm         — RFM-сегменты (Recency · Frequency · Monetary)
  GET /api/v1/dist        — распределения: LTV-децили, churn-децили, перцентили депозитов
  GET /api/v1/archetypes  — поведенческие архетипы игроков
  GET /api/v1/funnel      — воронка депозитов (регистрация → играл → #1 … → #N)

ПРИНЦИП (SPA_BUILD_PLAN.md §2C): расчёты НЕ переписываются. Данные берутся из
готовых структур/запросов `player_board.py` (headless-бэкенд):
  • /cohorts — переиспользуем кэш борда `pb._COHORTS_CACHE`, который наполняет
    сам борд (view `pb.cohorts()` со SPEC из 34 срезов). Ноль дублирования SQL.
  • /archetypes — переиспышем `pb.PERSONA_SQL` и `pb.PERSONA_DESC` (модульные
    константы борда) — та же классификация персон.
  • /rfm, /dist, /funnel — SQL этих view-функций живёт локально внутри самих
    функций борда (не импортируется), поэтому строки запросов скопированы
    ДОСЛОВНО (char-for-char) и исполняются через тот же `pb.q`. Формулы те же —
    цифры 1-в-1 (паритет проверяет V5). Рядом с каждым запросом указан источник.

Доступ (аналитический слой, SPA_BUILD_PLAN.md §1):
  analyst / director / marketing_manager / head_retention / finance / super_admin.

NAV: пункты /cohorts /rfm /dist /funnel /archetypes уже объявлены B1 в
`crm-spa/components/ui/nav.ts` (группа «Главное», roles = ANALYSTS). nav.ts не трогаем.
"""
from __future__ import annotations

from flask import Blueprint

from .core import require_auth, api_json, req_locale
from .i18n_catalog import loc, loc_deep   # перевод каталога по X-Locale
import player_board as pb          # готовые helper-функции/константы борда

bp = Blueprint('api_segmentation', __name__, url_prefix='/api/v1')

# Аналитический слой read-only (раздел 1 плана). Единый список ролей для домена.
ANALYST_ROLES = [
    'super_admin', 'director', 'head_retention',
    'analyst', 'marketing_manager', 'finance',
]

# База normal-игроков для процентов (как в борде).
_NORMAL = "account_type='normal'"


def _rows(sql, params=None):
    """Строки результата (pb.q возвращает (cols, rows) — берём rows)."""
    return pb.q(sql, params)[1]


# ════════════════════════════════════════════════════════════════════════════
# /cohorts — все срезы. Переиспользуем структурированный кэш борда (G) целиком.
# ════════════════════════════════════════════════════════════════════════════
# Текст-предупреждение из шапки борда (разные знаменатели у срезов) — для паритета
# подписи. Сам борд рендерит его в <div class=lead> над сеткой когорт.
COHORTS_NOTE = ('у разных срезов разный знаменатель: общие — по 39 010, '
                'денежные (депозиты/выводы) — только по игрокам с транзакциями (~31 837), '
                'игровые — по игравшим (~27 967). '
                'Сравнивать высоту баров между карточками напрямую нельзя.')


def _cohort_groups():
    """Структурированные группы когорт `G` из кэша борда `pb._COHORTS_CACHE`.

    Кэш наполняет сам борд (view `cohorts()` — прогрев `_warm_cohorts` при старте,
    либо первый заход на HTML `/cohorts`). Если для текущей даты данных кэша ещё
    нет — тихо вызываем `pb.cohorts()` (side-effect: строит и кэширует G, HTML
    отбрасываем). Так мы НЕ дублируем SPEC/SQL 34 срезов, а переиспользуем их.

    Формат G (как строит борд): [{'name': <группа>, 'items': [
      {'id','title','type': 'bar|time|area|donut', 'data': [{'label','value'}]}
      | {'id','title','type':'table', 'rows': [[label, value], ...]} ]}].
    """
    asof = str(pb.data_asof())
    if asof not in pb._COHORTS_CACHE:
        pb.cohorts()                 # side-effect наполнит _COHORTS_CACHE[asof]
    entry = pb._COHORTS_CACHE.get(asof)
    groups = entry[0] if entry else []
    return groups, asof


@bp.get('/cohorts')
@require_auth(roles=ANALYST_ROLES)
def cohorts():
    """Каталог всех когорт-срезов (данные + метки), сгруппированных A..G.
    Данные идентичны HTML-странице `/cohorts` (общий кэш борда)."""
    try:
        groups, asof = _cohort_groups()
    except Exception as e:                       # ClickHouse недоступен / кэш не построился
        return api_json(error=f'cohorts unavailable: {e}', code=503)
    total = sum(len(g.get('items', [])) for g in groups)
    lc = req_locale()
    return api_json({
        'groups': loc_deep(groups, lc),          # метки + подписи данных по X-Locale
        'meta': {
            'title': loc('Все когорты', lc),
            'subtitle': loc('36 срезов', lc),
            'note': loc(COHORTS_NOTE, lc),
            'as_of': asof,
            'count': total,
        },
    })


# ════════════════════════════════════════════════════════════════════════════
# /rfm — RFM-сегменты. SQL скопирован дословно из player_board.py::rfm().
# ════════════════════════════════════════════════════════════════════════════
# Метаданные сегментов (цвет badge + смысл + действие) — 1-в-1 с борда (META в rfm()).
RFM_META = {
    'Champions':          ('#dcfce7', '#166534', 'недавно + часто + много', 'беречь, VIP-программа'),
    'Loyal':              ('#dbeafe', '#1e40af', 'стабильное ядро',         'апсейл, удержание'),
    'New / Promising':    ('#fef9c3', '#854d0e', 'недавно, мало активности', 'онбординг'),
    'Cant-Lose-Them':     ('#fee2e2', '#991b1b', 'ценные, но пропали',      '🔴 срочно вернуть'),
    'At-Risk':            ('#ffedd5', '#9a3412', 'были активны, уходят',    'удержание сейчас'),
    'Hibernating / Lost': ('#f1f5f9', '#475569', 'давно не играли',         'win-back или отпустить'),
    'Need-Attention':     ('#f3e8ff', '#6b21a8', 'средние',                 'реактивация'),
}

# ⤵ дословно player_board.py::rfm() (строки 2104-2122)
_RFM_SQL = """
      WITH scored AS (
        SELECT turnover, recency_days, active_days,
          6 - ntile(5) OVER (ORDER BY recency_days) AS R,
          ntile(5) OVER (ORDER BY active_days)      AS F,
          ntile(5) OVER (ORDER BY turnover)         AS M
        FROM player_features WHERE account_type='normal' AND turnover > 0
      )
      SELECT multiIf(
          R>=4 AND F>=4 AND M>=4,        'Champions',
          R>=3 AND F>=3,                 'Loyal',
          R>=4 AND F<=2,                 'New / Promising',
          R<=2 AND F>=4 AND M>=4,        'Cant-Lose-Them',
          R<=2 AND F>=3,                 'At-Risk',
          R<=2,                          'Hibernating / Lost',
                                         'Need-Attention') AS seg,
        count() AS n, round(avg(turnover)) AS avg_turn,
        round(avg(recency_days)) AS avg_rec, round(avg(active_days),1) AS avg_act
      FROM scored GROUP BY seg ORDER BY n DESC"""


@bp.get('/rfm')
@require_auth(roles=ANALYST_ROLES)
def rfm():
    """RFM-сегменты по игравшим (turnover>0) + строка «не играли» (сходится к базе)."""
    try:
        rows = _rows(_RFM_SQL)
        base = _rows("SELECT count() FROM player_features WHERE account_type='normal'")[0][0]
    except Exception as e:
        return api_json(error=f'rfm unavailable: {e}', code=503)

    played = sum(r[1] for r in rows)
    never = base - played
    total = base or 1

    segments = []
    for seg, n, avg_turn, avg_rec, avg_act in rows:
        bg, fg, mean, action = RFM_META.get(seg, ('#ededed', '#666', '', ''))
        segments.append({
            'seg': seg, 'n': n, 'pct': round(100 * n / total, 1),
            'avg_turn': avg_turn, 'avg_rec': avg_rec, 'avg_act': avg_act,
            'bg': bg, 'fg': fg, 'mean': mean, 'action': action,
        })
    # строка «не играли» (нет RFM) — как отдельная строка внизу в борде
    never_row = {
        'seg': '⚪ Не играли (нет RFM)', 'n': never,
        'pct': round(100 * never / total, 1),
        'avg_turn': 0, 'avg_rec': None, 'avg_act': None,
        'bg': '#ededed', 'fg': '#94a3b8',
        'mean': 'зарегистрированы, но без ставок',
        'action': 'конверсия в игру / 1-й депозит',
    }
    lc = req_locale()
    return api_json({
        'segments': loc_deep(segments, lc),
        'never': loc_deep(never_row, lc),
        'base': base, 'played': played, 'never_count': never,
        'meta': {'title': loc('RFM-сегменты', lc),
                 'subtitle': 'Recency · Frequency · Monetary'},
    })


# ════════════════════════════════════════════════════════════════════════════
# /dist — распределения. SQL скопирован дословно из player_board.py::dist().
# ════════════════════════════════════════════════════════════════════════════
# ⤵ дословно player_board.py::dist() (строки 1991-1996)
_DIST_CHURN_BREAKDOWN_SQL = """WITH (SELECT toDate(max(created_at)) FROM game_transactions) AS dmax SELECT
        countIf(account_type='normal' AND ever_played AND dateDiff('day',toDate(last_bet_date),dmax)<=30 AND active_days>=2),
        countIf(account_type='normal' AND ever_played AND dateDiff('day',toDate(last_bet_date),dmax)<=30 AND active_days<2),
        countIf(account_type='normal' AND ever_played AND dateDiff('day',toDate(last_bet_date),dmax)>30),
        countIf(account_type='normal' AND NOT ever_played)
      FROM player_features"""


@bp.get('/dist')
@require_auth(roles=ANALYST_ROLES)
def dist():
    """Распределения ценности/риска: LTV-децили, churn-децили, перцентили депозитов,
    разбор «почему churn не по всей базе». Идентично HTML `/dist`."""
    try:
        ld = _rows("SELECT decile, players, avg_ltv, sum_ltv, pct_of_value FROM ltv_deciles ORDER BY decile")
        cd = _rows("SELECT decile, players, avg_risk, lo, hi FROM churn_deciles ORDER BY decile")
        dp = _rows("SELECT p10,p25,p50,p75,p90,p95,p99,pmax FROM deposit_percentiles")[0]
        ndep = _rows("SELECT count() FROM player_features WHERE account_type='normal' AND dep_count>0")[0][0]
        sc_n, os_n, gn_n, nv_n = _rows(_DIST_CHURN_BREAKDOWN_SQL)[0]
    except Exception as e:
        return api_json(error=f'dist unavailable: {e}', code=503)

    top_pct = ld[0][4] if ld else 0
    nld = sum(r[1] for r in ld)
    ncd = sum(r[1] for r in cd)

    ltv_deciles = [
        {'decile': no, 'players': p, 'avg_ltv': av, 'sum_ltv': sm,
         'pct_of_value': pc, 'is_whale': no == 1}
        for no, p, av, sm, pc in ld
    ]
    churn_deciles = [
        {'decile': no, 'players': p, 'avg_risk': av, 'lo': lo, 'hi': hi}
        for no, p, av, lo, hi in cd
    ]
    pctl_labels = ['P10', 'P25', 'P50', 'P75', 'P90', 'P95', 'P99', 'max']
    deposit_percentiles = [{'label': lab, 'value': v} for lab, v in zip(pctl_labels, dp)]

    # тот же разбор, что в борде (bd), — метки/пояснения дословно
    churn_breakdown = [
        {'group': '🟢 Активны + удерживаемы', 'desc': '≥2 дня, играл ≤30 дн',
         'players': sc_n, 'note': '← только эти и скорятся на churn'},
        {'group': '🔴 Уже ушли', 'desc': 'последняя ставка >30 дн назад',
         'players': gn_n, 'note': 'не «удерживать», а возвращать (winback)'},
        {'group': '⚪ Никогда не играли', 'desc': 'нет ни одной ставки',
         'players': nv_n, 'note': 'удерживать нечего'},
        {'group': '💨 Разовые', 'desc': '1 активный день — пришёл-ушёл',
         'players': os_n, 'note': 'нечего удерживать (исключены по ML_PLAN)'},
    ]

    return api_json(loc_deep({
        'cards': {
            'top10_pct_of_value': top_pct,
            'median_deposit': dp[2], 'p90_deposit': dp[4], 'p99_deposit': dp[6],
            'max_deposit': dp[7],
        },
        'ltv_deciles': ltv_deciles, 'ltv_base': nld,
        'churn_deciles': churn_deciles, 'churn_base': ncd,
        'deposit_percentiles': deposit_percentiles, 'depositors': ndep,
        'churn_breakdown': churn_breakdown,
        'churn_breakdown_total': sc_n + os_n + gn_n + nv_n,
        'meta': {'title': 'Распределения', 'subtitle': 'перцентили и концентрация'},
    }, req_locale()))


# ════════════════════════════════════════════════════════════════════════════
# /archetypes — переиспользуем pb.PERSONA_SQL + pb.PERSONA_DESC (константы борда).
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/archetypes')
@require_auth(roles=ANALYST_ROLES)
def archetypes():
    """Поведенческие архетипы. Классификация персон — `pb.PERSONA_SQL` (та же, что
    в борде); агрегирующая обёртка — дословно player_board.py::archetypes()."""
    try:
        # ⤵ дословно player_board.py::archetypes() (строки 2526-2529), PERSONA_SQL из борда
        rows = _rows(
            f"""SELECT persona, count() c, round(avg(avg_bet)) ab, round(avg(active_days),1) ad,
        round(avg(distinct_games),1) ag, round(100*countIf(is_depositor)/count()) dp, round(sum(turnover)/1e6,1) tm
      FROM (SELECT {pb.PERSONA_SQL} persona, avg_bet, active_days, distinct_games, is_depositor, turnover
        FROM player_features WHERE account_type='normal') GROUP BY persona""")
    except Exception as e:
        return api_json(error=f'archetypes unavailable: {e}', code=503)

    total = sum(r[1] for r in rows) or 1
    rows = sorted(rows, key=lambda r: r[1], reverse=True)
    lc = req_locale()
    items = []
    for persona, c, ab, ad, ag, dp, tm in rows:
        # локализуем персону ДО partition — иначе 'name' взялся бы из рус. строки
        p_loc = loc(persona, lc)
        emoji, _, name = str(p_loc).partition(' ')
        items.append({
            'persona': p_loc, 'emoji': emoji, 'name': name,
            'desc': loc(pb.PERSONA_DESC.get(persona, ''), lc),
            'count': c, 'pct': round(100 * c / total, 1),
            'avg_bet': ab, 'active_days': ad, 'distinct_games': ag,
            'depositor_pct': dp, 'turnover_mn': tm,
        })
    return api_json({
        'total': sum(r[1] for r in rows),
        'archetypes': items,
        'meta': {'title': loc('Архетипы игроков', lc), 'subtitle': loc('похожие по поведению', lc)},
    })


# ════════════════════════════════════════════════════════════════════════════
# /funnel — воронка депозитов. SQL скопирован дословно из player_board.py::funnel().
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/funnel')
@require_auth(roles=ANALYST_ROLES)
def funnel():
    """Воронка: регистрация → играл → депозит #1 (FTD) → #2 … → #N.
    Единая база депозитов из `deposit_ladder` (как в борде)."""
    try:
        reg = _rows("SELECT count() FROM users WHERE account_type='normal'")[0][0]
        played = _rows("SELECT countIf(ever_played) FROM player_features WHERE account_type='normal'")[0][0]
        lad = _rows("SELECT deposit_no, reached FROM deposit_ladder ORDER BY deposit_no")
    except Exception as e:
        return api_json(error=f'funnel unavailable: {e}', code=503)

    # порядок этапов — как в борде; локализуем метки (в т.ч. динамический «Депозит #N»)
    lc = req_locale()
    dep = loc('Депозит', lc)
    stage_pairs = [(loc('Регистрация', lc), reg), (loc('Играл хоть раз', lc), played)]
    for no, reached in lad:
        stage_pairs.append((loc('Депозит #1 (FTD)', lc) if no == 1 else f'{dep} #{no}', reached))

    mx = stage_pairs[0][1] or 1
    stages = []
    prev = None
    for name, n in stage_pairs:
        step_conv = None if prev is None else (round(100 * n / prev) if prev else 0)
        stages.append({
            'name': name, 'n': n,
            'pct_of_reg': round(100 * n / reg, 1) if reg else 0,
            'step_conv': step_conv,
            'bar_pct': round(n / mx * 100) if mx else 0,
        })
        prev = n

    return api_json({
        'reg': reg, 'stages': stages,
        'meta': {'title': loc('Воронка депозитов', lc), 'subtitle': loc('где теряем', lc)},
    })
