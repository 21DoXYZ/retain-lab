"""api/bonus_economics.py — домен «Бонус-экономика» (ТЗ этап 2, §3.3).

Один эндпоинт для реструктурированного экрана /bonus (BonusScreen):

  GET /api/v1/bonus/economics?from&to&type&campaign&aff&vip
    → { kpi:    [7 плашек P&L с бейджами доступности],
        funnel: [7 этапов воронки бонуса],
        abuse:  {personas, depositors, share_pct, ...},
        filters:{applied, options} }

ПРИНЦИП (как у всех api/*.py): формулы НЕ переписываем — берём готовые
константы/функции борда (`pb.q`, `BONUS_OK`, `_ggr_kpis`, `calc_ngr`,
`PERSONA_SQL`, `data_asof`) и уже посчитанные витрины ClickHouse
(`bonus_uplift`, `bonus_effectiveness_t`, `bonus_status_current`). Одни данные —
одни цифры: `issued` сходится с бонус-вкладкой GGR (`api/money.py::_ggr_tab`).

Часть метрик пока НЕ считается из имеющихся данных — плашки честно помечены
статусом, а не заглушены нулём:
  • cost / roi   → status 'needs_event' (ждёт события казино `bonus_converted`);
  • activated / wagering_* → status 'missing' (таблица `bonus_status_current`
    пустая — казино ещё не шлёт поток статусов бонуса);
  • converted_or_expired → status 'indirect' (косвенный прокси = ручные списания);
  • uplift / incr_deposits → status 'partial' (модельная оценка за весь период).

Роли — те же, что у `/bonus` (`api/marketing.py::MARKETING_ROLES`).
Регистрируется автоматически пакетом `api/` по переменной `bp`.
"""
from __future__ import annotations

import re

from flask import Blueprint, request

from .core import require_auth, api_json

import player_board as pb   # готовые helper-функции/константы борда (НЕ дублируем)

bp = Blueprint('api_bonus_economics', __name__, url_prefix='/api/v1')

# ── роли: 1-в-1 с /bonus (маркетинговый/модельный слой) ──────────────────────
MARKETING_ROLES = [
    'super_admin', 'director', 'head_retention',
    'marketing_manager', 'analyst', 'vip_manager',
    # «Бонусы: эффект» открыт руководителю КЦ (запрос клиента). Операторам меню
    # убрано (2026-07-29) — им «реакция на бонусы» в карточке, не агрегатный дашборд.
    'head_department',
]

# ── классификатор типа бонуса — те же ветки, что в бонус-вкладке GGR
#    (api/money.py:326-328), но с ASCII-ключами (чисто ложатся в URL ?type=). ──
BONUS_TYPE_EXPR = (
    "multiIf(type='freespin','freespin',"
    "description ILIKE '%deneme%','nodeposit',"
    "description ILIKE '%kay%p%','cashback',"
    "description ILIKE '%dsc%' OR description ILIKE '%yat%','deposit_match',"
    "type='manual_bonus','manual','other')"
)
TYPE_KEYS = ('freespin', 'nodeposit', 'cashback', 'deposit_match', 'manual', 'other')

# архетип «бонусник» из PERSONA_SQL (та же классификация, что в /archetypes)
PERSONA_BONUS = '🎁 Бонусник'

_DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')


def _f(x):
    """None/Decimal-safe float."""
    return float(x) if x is not None else None


# ════════════════════════════════════════════════════════════════════════════
# Разбор фильтров (?from&to&type&campaign&aff&vip)
# ════════════════════════════════════════════════════════════════════════════
def _vd(s):
    """Строгая маска YYYY-MM-DD либо None (как _vd в ggr_page)."""
    s = (s or '').strip()
    return s if _DATE_RE.fullmatch(s) else None


def _parse_filters():
    """Санитизация query-параметров.

    Кампания валидируется по БЕЛОМУ СПИСКУ (фактические `payment_method`
    'campaign:*' из БД), поэтому в SQL уходит только заведомо существующее
    значение — инъекция невозможна, escape не нужен."""
    frm = _vd(request.args.get('from'))
    to = _vd(request.args.get('to'))
    if frm and to and frm > to:
        frm, to = to, frm

    t = (request.args.get('type') or '').strip()
    typ = t if t in TYPE_KEYS else None

    # аффилиат — только alnum/underscore (как в _ggr_filters), 64 символа
    aff = ''.join(c for c in request.args.get('aff', '') if c.isalnum() or c == '_')[:64]
    aff = aff or None

    vip_raw = (request.args.get('vip') or '').strip()
    vip = int(vip_raw) if vip_raw.isdigit() and 0 <= int(vip_raw) <= 5 else None

    campaign = (request.args.get('campaign') or '').strip()[:80] or None
    return frm, to, typ, aff, vip, campaign


def _date_cond(frm, to):
    """Оконный фильтр по бизнес-дню (Стамбул). Явный toTimeZone — безопасно при
    server-tz Asia/Makassar (образец — api/affiliates.py / api/money.py)."""
    col = "toDate(toTimeZone(created_at,'Europe/Istanbul'))"
    if frm and to:
        return f"{col} BETWEEN '{frm}' AND '{to}'"
    if frm:
        return f"{col} >= '{frm}'"
    if to:
        return f"{col} <= '{to}'"
    return '1'


def _player_scope(aff, vip):
    """Условие принадлежности игрока срезу: normal [+ affiliate_code] [+ vip_level].
    vip_level живёт в player_features, поэтому добавляется отдельным подзапросом."""
    users = "account_type='normal'"
    if aff:
        users += f" AND affiliate_code='{aff}'"      # aff уже [A-Za-z0-9_]
    scope = f"casino_player_id IN (SELECT casino_player_id FROM users WHERE {users})"
    if vip is not None:
        scope += (f" AND casino_player_id IN "
                  f"(SELECT casino_player_id FROM player_features WHERE vip_level={vip})")
    return scope


def _campaign_options():
    """Топ фактических кампаний (payment_method 'campaign:<name>') — для Select и
    как белый список валидации фильтра."""
    try:
        rows = pb.q("SELECT payment_method, count() c FROM money_transactions "
                    "WHERE payment_method LIKE 'campaign:%' "
                    "GROUP BY payment_method ORDER BY c DESC LIMIT 40")[1]
    except Exception:
        return []
    # отдаём имя кампании без префикса 'campaign:'
    return [str(pm)[9:] for pm, _c in rows if str(pm).startswith('campaign:')]


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/bonus/economics
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/bonus/economics')
@require_auth(roles=MARKETING_ROLES)
def bonus_economics():
    frm, to, typ, aff, vip, campaign = _parse_filters()

    # кампания — только из белого списка (иначе тихо игнорируем фильтр)
    campaigns = _campaign_options()
    if campaign and campaign != '*' and campaign not in campaigns:
        campaign = None
    campaign_active = bool(campaign)

    scope = _player_scope(aff, vip)
    dw = _date_cond(frm, to)

    # ── общий WHERE для выдач (money_transactions, BONUS_OK) ──
    issued_where = [pb.BONUS_OK, scope]
    issued_params: dict = {}
    if dw != '1':
        issued_where.append(dw)
    if typ:
        issued_where.append(f"{BONUS_TYPE_EXPR}='{typ}'")
    if campaign:
        if campaign == '*':
            issued_where.append("payment_method LIKE 'campaign:%'")
        else:
            # campaign уже прошёл белый список, но значение приходит из ingest-потока
            # казино — параметризуем (защита в глубину, находка ревью W2)
            issued_where.append("payment_method = {camp:String}")
            issued_params['camp'] = f'campaign:{campaign}'
    IW = ' AND '.join(issued_where)

    # ── 1) issued (P&L: сколько бонусов выдано) ──
    try:
        s, cnt, uniq = pb.q(
            f"SELECT round(sum(abs(amount))), count(), uniqExact(casino_player_id) "
            f"FROM money_transactions WHERE {IW}", issued_params)[1][0]
    except Exception as e:
        return api_json(error=f'bonus economics unavailable: {e}', code=503)
    issued_sum = _f(s) or 0.0
    issued_cnt = int(cnt or 0)
    issued_uniq = int(uniq or 0)

    # ── 2) ggr / ngr (казино-масштаб; при любом срезе — «частично») ──
    filtered = bool(typ or aff or vip is not None or campaign_active)
    scope_g = _player_scope(aff, vip)
    gw = f"{pb.GSUCCESS} AND currency='TRY' AND {scope_g} AND {dw}"
    mw = f"{scope_g} AND {dw}"
    try:
        k = pb._ggr_kpis(gw, mw, dw, scope_g, dw)
        ggr_val, ngr_val = _f(k['ggr']), _f(k['ngr'])
        ggr_ngr_ok = True
    except Exception:
        ggr_val = ngr_val = None
        ggr_ngr_ok = False
    money_status = 'ok' if (ggr_ngr_ok and not filtered) else ('partial' if ggr_ngr_ok else 'needs_event')

    # ── 3) uplift / incr_deposits (bonus_uplift — модельная оценка, весь период) ──
    up = {}
    try:
        up = {m: _f(v) for m, v in pb.q("SELECT metric, value FROM bonus_uplift")[1]}
    except Exception:
        up = {}
    att = up.get('att_pp')
    n_treated = int(up.get('n_treated') or 0)
    # incremental удержанные (≈ доп. депозиторы) = att_pp% × treated
    incr = round(att / 100 * n_treated) if (att is not None and n_treated) else None

    kpi = [
        {'key': 'issued', 'value': issued_sum, 'count': issued_cnt,
         'uniq': issued_uniq, 'status': 'ok'},
        {'key': 'cost', 'value': None, 'status': 'needs_event', 'event': 'bonus_converted'},
        {'key': 'incr_deposits', 'value': incr,
         'status': 'partial' if incr is not None else 'needs_event'},
        {'key': 'ggr', 'value': ggr_val, 'status': money_status},
        {'key': 'ngr', 'value': ngr_val, 'status': money_status},
        {'key': 'roi', 'value': None, 'status': 'needs_event', 'event': 'bonus_converted'},
        {'key': 'uplift', 'value': att,
         'ci_lo': up.get('ci_lo_pp'), 'ci_hi': up.get('ci_hi_pp'),
         'n_treated': n_treated, 'n_control': int(up.get('n_control') or 0),
         'status': 'partial' if att is not None else 'needs_event'},
    ]

    # ════════════════════════════════════════════════════════════════════════
    # Воронка бонуса (7 этапов)
    # ════════════════════════════════════════════════════════════════════════
    # activated / wagering_* — из bonus_status_current (пока 0 строк → 'missing').
    # Маппинг статусов провизорный: поток от казино ещё не подключён.
    STATUS_MAP = {'activated': 'activated',
                  'wagering_started': 'wagering',
                  'wagering_done': 'wagering_completed'}
    try:
        bsc_total = pb.q("SELECT count() FROM bonus_status_current")[1][0][0]
    except Exception:
        bsc_total = 0

    def _bsc(stage_status):
        if not bsc_total:
            return {'value': None, 'status': 'missing'}
        try:
            n = pb.q("SELECT count() FROM bonus_status_current WHERE status={s:String}",
                     {'s': stage_status})[1][0][0]
            return {'value': int(n or 0), 'status': 'ok'}
        except Exception:
            return {'value': None, 'status': 'missing'}

    # converted_or_expired — косвенный прокси: сумма ручных списаний completed
    conv_where = [scope]
    if dw != '1':
        conv_where.append(dw)
    try:
        conv_sum = _f(pb.q(
            "SELECT round(sum(amount)) FROM money_transactions "
            f"WHERE type='manual_withdrawal' AND status='completed' AND {' AND '.join(conv_where)}"
        )[1][0][0]) or 0.0
    except Exception:
        conv_sum = None

    # deposit_14d / retained_30d — витрина bonus_effectiveness_t, взвешено по bonus_events
    try:
        dep14, ret30 = pb.q(
            "SELECT round(sum(dep_resp_14d_pct*bonus_events)/nullIf(sum(bonus_events),0),1), "
            "round(sum(retained_30d_pct*bonus_events)/nullIf(sum(bonus_events),0),1) "
            "FROM bonus_effectiveness_t")[1][0]
        dep14, ret30 = _f(dep14), _f(ret30)
    except Exception:
        dep14 = ret30 = None

    funnel = [
        {'stage': 'issued', 'value': issued_cnt, 'status': 'ok', 'note_key': 'issued'},
        {'stage': 'activated', **_bsc(STATUS_MAP['activated']), 'note_key': 'waitsEvent'},
        {'stage': 'wagering_started', **_bsc(STATUS_MAP['wagering_started']), 'note_key': 'waitsEvent'},
        {'stage': 'wagering_done', **_bsc(STATUS_MAP['wagering_done']), 'note_key': 'waitsEvent'},
        {'stage': 'converted_or_expired', 'value': conv_sum,
         'status': 'indirect' if conv_sum is not None else 'missing', 'note_key': 'indirect'},
        {'stage': 'deposit_14d', 'value': dep14,
         'status': 'ok' if dep14 is not None else 'missing', 'unit': 'pct', 'note_key': 'mart'},
        {'stage': 'retained_30d', 'value': ret30,
         'status': 'ok' if ret30 is not None else 'missing', 'unit': 'pct', 'note_key': 'mart'},
    ]

    # ════════════════════════════════════════════════════════════════════════
    # Abuse: архетип «🎁 Бонусник» + доля от депозиторов (снимок, фильтры не влияют)
    # ════════════════════════════════════════════════════════════════════════
    try:
        personas, personas_dep, depositors = pb.q(
            f"SELECT countIf(persona={{p:String}}), "
            f"countIf(persona={{p:String}} AND dep_count>0), countIf(dep_count>0) "
            f"FROM (SELECT {pb.PERSONA_SQL} persona, dep_count "
            f"FROM player_features WHERE account_type='normal')",
            {'p': PERSONA_BONUS})[1][0]
        personas, personas_dep, depositors = int(personas or 0), int(personas_dep or 0), int(depositors or 0)
        share_pct = round(100 * personas_dep / depositors, 1) if depositors else 0.0
    except Exception:
        personas = personas_dep = depositors = 0
        share_pct = 0.0
    abuse = {'personas': personas, 'depositors': depositors,
             'personas_depositors': personas_dep, 'share_pct': share_pct,
             'href': '/flags?kind=bonus_abuse'}

    return api_json({
        'kpi': kpi,
        'funnel': funnel,
        'abuse': abuse,
        'filters': {
            'applied': {'from': frm, 'to': to, 'type': typ, 'campaign': campaign,
                        'aff': aff, 'vip': vip, 'windowed': dw != '1'},
            'options': {
                'types': list(TYPE_KEYS),
                'campaigns': campaigns,
                'vip_levels': _vip_levels(),
            },
        },
    })


def _vip_levels():
    """Уровни vip_level, реально присутствующие в базе (для Select)."""
    try:
        rows = pb.q("SELECT DISTINCT vip_level FROM player_features "
                    "WHERE account_type='normal' ORDER BY vip_level")[1]
        return [int(r[0]) for r in rows if r[0] is not None]
    except Exception:
        return [0, 1, 2, 3, 4, 5]
