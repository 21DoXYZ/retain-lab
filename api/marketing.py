"""api/marketing.py — домен «Модели и маркетинг» (агент C4).

JSON-эндпоинты для экранов SPA: /ltv, /actions, /bonus, /bonuses, /campaigns,
/games + скоры VIP-моделей (vip_churn / early_vip / non_promising).

ПРИНЦИП (SPA_BUILD_PLAN.md §2C): логика/формулы НЕ переписываются. Модуль
переиспользует ГОТОВЫЕ helper-функции и SQL из player_board (`pb.q`,
`pb.offer_for`, `pb._bonus_distribution`, `pb.SEGMENTS`, `pb.GN`, `pb._has_table`,
`pb.KIND_LBL`) и каталог бонусов (`bonus_catalog`). Одни данные — одни цифры:
JSON здесь отдаёт ровно те числа, что рисует HTML-страница борда (паритет V5).

Роли (SPA_BUILD_PLAN.md §1 — маркетинговый/модельный слой):
  marketing_manager · analyst · director · head_retention · vip_manager · super_admin
VIP-скоры дополнительно открыты risk_officer.

Регистрируется автоматически: пакет `api/` находит модуль по переменной `bp`.
"""
from __future__ import annotations

from flask import Blueprint, request

from .core import require_auth, api_json, req_locale

import player_board as pb   # готовые helper-функции и SQL борда (НЕ дублируем)

bp = Blueprint('api_marketing', __name__, url_prefix='/api/v1')

# ── матрица ролей (раздел 1 плана) ───────────────────────────────────────────
MARKETING_ROLES = [
    'super_admin', 'director', 'head_retention',
    'marketing_manager', 'analyst', 'vip_manager',
]
VIP_SCORE_ROLES = MARKETING_ROLES + ['risk_officer']
# «Бонусы: эффект» открыт руководителю КЦ (запрос клиента) — только этот дашборд
# (агрегаты, без списка игроков/PII), не весь маркетинг. Операторам меню убрано
# (2026-07-29): им нужна «реакция на бонусы» в КАРТОЧКЕ (BONUS_BLOCK_ROLES), не агрегат.
BONUS_VIEW_ROLES = MARKETING_ROLES + ['head_department']

# фильтры движка действий — 1:1 со стартовым словарём в player_board.actions()
_ACT_WHERE = {
    'SAVE': "startsWith(action,'SAVE')",
    'WINBACK': "startsWith(action,'WINBACK')",
    'NUDGE': "startsWith(action,'NUDGE')",
    'CONVERT': "startsWith(action,'CONVERT')",
    'NURTURE': "startsWith(action,'NURTURE')",
    'all': "action!='наблюдать'",
}

# три VIP-модели: таблица → (колонка-скор, человекочитаемая подпись, «высокий = …»)
VIP_MODELS = (
    ('vip_churn', 'player_vip_churn_ml', 'p_vip_churn',
     'VIP-риск оттока', 'высокий скор = VIP под риском ухода'),
    ('early_vip', 'player_early_vip_ml', 'p_early_vip',
     'Ранний VIP', 'высокий скор = станет VIP уже за первую неделю'),
    ('non_promising', 'player_non_promising_vip_ml', 'p_non_promising',
     'Неперспективный VIP', 'высокий скор = вряд ли вырастет в тире (разгрузить VIP-менеджера)'),
)


def _f(v):
    """Decimal/None-safe float."""
    return float(v) if v is not None else None


# ════════════════════════════════════════════════════════════════════════════
# /ltv — LTV-прогноз (кривая · тиры · молодые киты)   [player_board.ltv()]
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/ltv')
@require_auth(roles=MARKETING_ROLES)
def ltv():
    curve = pb.q("SELECT day, cohort_n, avg_cum_deposit, median_cum_deposit "
                 "FROM ltv_curve ORDER BY day")[1]
    tiers = pb.q("SELECT early_tier_D7, cohort_n, exp_d30, exp_d90, exp_d120 "
                 "FROM ltv_tier_model ORDER BY early_tier_D7")[1]
    whales, whales_head = pb.q("SELECT countIf(early_tier='D'), "
                               "round(sumIf(ltv_headroom, early_tier='D')) FROM player_ltv")[1][0]
    young = pb.q("SELECT count() FROM player_ltv "
                 "WHERE early_tier IN ('C','D') AND days_since_ftd<=30")[1][0][0]
    tot_head = pb.q("SELECT round(sum(ltv_headroom)) FROM player_ltv")[1][0][0]
    yw = pb.q("SELECT casino_player_id, days_since_ftd, tier_provisional, early_tier, "
              "dep_d7, dep_to_date, pred_ltv_d90, ltv_headroom "
              "FROM player_ltv WHERE early_tier IN ('C','D') AND days_since_ftd<=30 "
              "ORDER BY pred_ltv_d90 DESC, dep_d7 DESC LIMIT 20")[1]

    d1 = (_f(curve[0][2]) if curve else 1) or 1   # guard от деления на 0
    growth = round(_f(curve[-1][2]) / d1, 1) if curve else None

    return api_json({
        'kpi': {
            'tot_head': _f(tot_head),
            'whales': whales,
            'whales_head': _f(whales_head),
            'young': young,
            'growth_d120_d1': growth,   # во сколько раз растёт LTV к D120
        },
        'curve': [{
            'day': day, 'cohort_n': n, 'avg': _f(avg), 'median': _f(med),
            'x_d1': round(_f(avg) / d1, 2),
        } for day, n, avg, med in curve],
        'tiers': [{
            'tier': t, 'cohort_n': n,
            'exp_d30': _f(e30), 'exp_d90': _f(e90), 'exp_d120': _f(e120),
        } for t, n, e30, e90, e120 in tiers],
        'young_whales': [{
            'player_id': pid, 'days_since_ftd': age, 'tier_provisional': bool(prov),
            'early_tier': t, 'dep_d7': _f(d7), 'dep_to_date': _f(dtot),
            'pred_ltv_d90': _f(p90), 'ltv_headroom': _f(head),
        } for pid, age, prov, t, d7, dtot, p90, head in yw],
    })


# ════════════════════════════════════════════════════════════════════════════
# /actions — движок решений (кому · когда · какой бонус)  [player_board.actions()]
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/actions')
@require_auth(roles=MARKETING_ROLES)
def actions():
    act = request.args.get('act', 'SAVE')
    if act not in _ACT_WHERE:
        act = 'SAVE'
    where = _ACT_WHERE[act]

    # KPI-карточки (те же выборки, что в HTML)
    save_n, save_v = pb.q("SELECT count(), round(sum(value_try)) "
                          "FROM player_actions WHERE startsWith(action,'SAVE')")[1][0]
    wb_n = pb.q("SELECT count() FROM player_actions WHERE startsWith(action,'WINBACK')")[1][0][0]
    nudge_n = pb.q("SELECT count() FROM player_actions WHERE startsWith(action,'NUDGE')")[1][0][0]
    conv_n = pb.q("SELECT count() FROM player_actions WHERE startsWith(action,'CONVERT')")[1][0][0]

    # распределение по всем действиям (incl. «наблюдать»)
    dist = pb.q("SELECT action, count(), round(sum(value_try)) FROM player_actions "
                "GROUP BY action ORDER BY sum(value_try) DESC")[1]
    ndist = sum(r[1] for r in dist)

    # приоритетный список по фильтру (60 строк) — 1:1 SQL борда
    rows = pb.q(
        "SELECT pa.casino_player_id, pa.lifecycle, pa.action, round(pa.value_try), "
        "pa.p_churn, pa.p_2nd_deposit, pa.bonus, pa.when_to, pa.dep_count, pa.early_tier, "
        "pa.pred_ltv_d90, toFloat64(ifNull(pf.net,0)) "
        "FROM player_actions pa LEFT JOIN player_features pf USING (casino_player_id) "
        f"WHERE {where} ORDER BY pa.priority DESC, pa.value_try DESC LIMIT 60")[1]

    ids = [int(r[0]) for r in rows]
    vip_by_id = _vip_scores_for_ids(ids)   # обогащение VIP-скорами (если таблицы есть)

    loc = req_locale()
    out_rows = []
    for pid, lf, a, val, pch, p2, bonus, when, dc, tier, ltv_pred, net in rows:
        # оффер из РЕАЛЬНОГО каталога — та же функция, что в HTML-ячейке (на языке оператора)
        name, terms, reason = pb.offer_for({
            'lifecycle': lf, 'dep_count': dc, 'early_tier': tier,
            'pred_ltv_d90': ltv_pred, 'p_churn': pch, 'net': net}, loc)
        out_rows.append({
            'player_id': pid, 'lifecycle': lf, 'action': a,
            'value_try': _f(val), 'p_churn': _f(pch), 'p_2nd_deposit': _f(p2),
            'when_to': pb.when_to_label(when, loc), 'dep_count': dc, 'early_tier': tier,
            'pred_ltv_d90': _f(ltv_pred), 'net': _f(net),
            'offer_name': name, 'offer_terms': terms, 'offer_reason': reason,
            'vip_scores': vip_by_id.get(pid, {}),
        })

    return api_json({
        'filter': act,
        'filters': [{'key': k, 'label': lab} for k, lab in pb.ACT_FILTERS],
        'cards': {
            'save_n': save_n, 'save_v': _f(save_v),
            'wb_n': wb_n, 'nudge_n': nudge_n, 'conv_n': conv_n,
        },
        'distribution': [{'action': a, 'players': n, 'value_try': _f(v)} for a, n, v in dist],
        'distribution_total': ndist,
        'rows': out_rows,
    })


# ════════════════════════════════════════════════════════════════════════════
# /bonus — эффект бонусов (uplift · эффективность · рекомендации) [player_board.bonus()]
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/bonus')
@require_auth(roles=BONUS_VIEW_ROLES)
def bonus():
    up = {m: _f(v) for m, v in pb.q("SELECT metric, value FROM bonus_uplift")[1]}
    eff = pb.q("SELECT bonus_type, players, dep_resp_14d_pct, retained_30d_pct, bonus_events "
               "FROM bonus_effectiveness_t ORDER BY bonus_events DESC")[1]
    rec = pb.q("SELECT rec_bonus, count() FROM player_bonus_ml "
               "GROUP BY rec_bonus ORDER BY count() DESC")[1]

    att = up.get('att_pp', 0) or 0
    lo = up.get('ci_lo_pp', 0) or 0
    hi = up.get('ci_hi_pp', 0) or 0
    rt = (up.get('retain_treated', 0) or 0) * 100
    rc = (up.get('retain_control', 0) or 0) * 100
    nt = int(up.get('n_treated', 0) or 0)
    nc = int(up.get('n_control', 0) or 0)
    nrec = sum(r[1] for r in rec)

    return api_json({
        'uplift': {
            'att_pp': att, 'ci_lo_pp': lo, 'ci_hi_pp': hi,
            'retain_treated_pct': rt, 'retain_control_pct': rc, 'raw_pp': rt - rc,
            'n_treated': nt, 'n_control': nc,
        },
        'effectiveness': [{
            'bonus_type': str(bt), 'players': pl, 'bonus_events': ev,
            'dep_resp_14d_pct': _f(dr), 'retained_30d_pct': _f(ret),
        } for bt, pl, dr, ret, ev in eff],
        'recommendations': [{
            'rec_bonus': str(b), 'players': n,
            'pct': round(100 * n / (nrec or 1)),
        } for b, n in rec],
        'rec_total': nrec,
    })


# ════════════════════════════════════════════════════════════════════════════
# /bonuses — каталог реальных акций + подбор   [player_board.bonuses()]
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/bonuses')
@require_auth(roles=MARKETING_ROLES)
def bonuses():
    from bonus_catalog import load_catalog, _available_today, loc_field, render_why

    loc = req_locale()
    cat = load_catalog()
    dist = pb._bonus_distribution()          # кэш по дате данных; НЕ переписываем
    counts, examples, total = dist['counts'], dist['examples'], dist['total']
    matched = sum(v for k, v in counts.items() if k != '—')

    out = []
    for b in sorted(cat['bonuses'], key=lambda x: -counts.get(x['id'], 0)):
        n = counts.get(b['id'], 0)
        icon, kind = pb.KIND_LBL.get(b['kind'], ('•', b['kind']))
        vip = b.get('vip_percent')
        if vip:
            pct = f"{min(vip.values())}–{max(vip.values())}%"
        elif b.get('percent'):
            pct = f"{b['percent']}%"
        else:
            pct = '—'
        # лимиты — те же подписи, что в оффере игроку (pb.OFFER_LBL), на языке оператора
        limits = []
        if b.get('min_deposit'):
            limits.append(f"{pb._lbl('min_deposit', loc)} {pb.f(b['min_deposit'])}₺")
        if b.get('min_loss'):
            limits.append(f"{pb._lbl('min_loss', loc)} {pb.f(b['min_loss'])}₺")
        if b.get('max_bonus'):
            limits.append(f"{pb._lbl('max_bonus', loc)} {pb.f(b['max_bonus'])}₺")
        ex = examples.get(b['id'])
        out.append({
            # name_ru/name_tr — как раньше (контракт экрана); name — на языке оператора,
            # name_en — англ. перевод. Условия/причина примера уже локализованы.
            'id': b['id'], 'name': loc_field(b, 'name', loc),
            'name_ru': b['name_ru'], 'name_tr': b['name_tr'],
            'name_en': b.get('name_en'),
            'kind': b['kind'], 'kind_label': kind, 'icon': icon, 'area': b['area'],
            'percent_label': pct, 'limits': limits, 'days': b['days'],
            'wager': loc_field(b, 'wager', loc),
            'available_today': bool(_available_today(b)),
            'players': n,
            'example_player': ex[0] if ex else None,
            # ex = (pid, причина_ru, код, параметры) — рисуем код на языке оператора
            'example_reason': render_why(ex[2], ex[3], loc) if ex else None,
        })

    most_common = max(counts, key=counts.get) if counts else '—'
    return api_json({
        'kpi': {
            'catalog_size': len(cat['bonuses']),
            'available_today': sum(1 for b in cat['bonuses'] if _available_today(b)),
            'matched': matched, 'total': total,
            'most_common': most_common,
        },
        'bonuses': out,
    })


# ════════════════════════════════════════════════════════════════════════════
# /campaigns — 8 сегментов для бонус-рассылок   [player_board.campaigns()]
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/campaigns')
@require_auth(roles=MARKETING_ROLES)
def campaigns():
    # тот же единый запрос countIf(...) по всем сегментам, что и в HTML
    counts = pb.q("SELECT " + ', '.join(f"countIf({s[5]})" for s in pb.SEGMENTS) +
                  " FROM player_features WHERE account_type='normal'")[1][0]
    segments = [{
        'key': key, 'icon': icon, 'name': name, 'who': who, 'offer': offer,
        'count': cnt,
    } for (key, icon, name, who, offer, _cond), cnt in zip(pb.SEGMENTS, counts)]
    return api_json({'segments': segments})


# ════════════════════════════════════════════════════════════════════════════
# /games — топ игр (сегменты для рассылок, С НАЗВАНИЯМИ)   [player_board.games()]
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/games')
@require_auth(roles=MARKETING_ROLES)
def games():
    nrm = "casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')"
    # game_uuid отдаём рядом с именем: фильтр списка игроков матчит по хешу
    # (startsWith(game_uuid, …) в _players_filter), а имя — только для показа.
    rows = pb.q(f"SELECT {pb.GN()} g, game_uuid, uniqExact(casino_player_id) players, any(provider) prov, "
                "round(sum(turnover)) turn, round(avg(days_played),1) days "
                f"FROM player_games WHERE {nrm} GROUP BY game_uuid ORDER BY players DESC LIMIT 18")[1]
    games_out = [{
        'name': str(g), 'game_uuid': str(gid), 'players': players, 'provider': (prov or None),
        'turnover': _f(turn), 'turnover_mn': round(float(turn or 0) / 1e6, 1),
        'avg_days': _f(days),
    } for g, gid, players, prov, turn, days in rows]
    return api_json({'games': games_out})


# ════════════════════════════════════════════════════════════════════════════
# /vip-scores — сводка трёх VIP-моделей (vip_churn / early_vip / non_promising)
#   таблицы retention.player_*_ml (VIP_INTELLIGENCE_INHOUSE.md)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/vip-scores')
@require_auth(roles=VIP_SCORE_ROLES)
def vip_scores():
    models = {}
    for mkey, table, col, label, hint in VIP_MODELS:
        if not pb._has_table(table):
            models[mkey] = {'available': False, 'label': label, 'hint': hint}
            continue
        try:
            scored, avg, ge50, ge70, ge90 = pb.q(
                f"SELECT count(), avg({col}), countIf({col}>=0.5), "
                f"countIf({col}>=0.7), countIf({col}>=0.9) FROM {table}")[1][0]
            top = pb.q(
                f"SELECT m.casino_player_id, m.{col}, pf.lifecycle, pf.vip_level, "
                "toFloat64(ifNull(pf.net,0)), pf.recency_days, round(pf.turnover), pf.dep_count, "
                "round(pf.avg_bet) "
                f"FROM {table} m LEFT JOIN player_features pf USING (casino_player_id) "
                f"ORDER BY m.{col} DESC LIMIT 20")[1]
            models[mkey] = {
                'available': True, 'label': label, 'hint': hint,
                'scored': scored, 'avg': _f(avg),
                'buckets': {'ge_50': ge50, 'ge_70': ge70, 'ge_90': ge90},
                'top': [{
                    'player_id': pid, 'score': _f(sc), 'lifecycle': lf,
                    'vip_level': vl, 'net': _f(net), 'recency_days': rec,
                    'turnover': _f(turn), 'dep_count': dc, 'avg_bet': _f(ab),
                } for pid, sc, lf, vl, net, rec, turn, dc, ab in top],
            }
        except Exception as e:   # таблица есть, но запрос упал — не роняем весь ответ
            models[mkey] = {'available': False, 'label': label, 'hint': hint,
                            'error': str(e)}
    return api_json({'models': models})


# ── VIP-скоры пачкой по списку id (для обогащения таблицы /actions) ───────────
def _vip_scores_for_ids(ids: list[int]) -> dict[int, dict]:
    """{player_id: {vip_churn, early_vip, non_promising}} по переданным id.
    Пропускает отсутствующие ML-таблицы (fail-soft). Значения — вероятности 0..1."""
    if not ids:
        return {}
    id_list = ','.join(str(i) for i in ids)      # уже провалидированы в int
    out: dict[int, dict] = {}
    for mkey, table, col, _label, _hint in VIP_MODELS:
        if not pb._has_table(table):
            continue
        try:
            rows = pb.q(f"SELECT casino_player_id, {col} FROM {table} "
                        f"WHERE casino_player_id IN ({id_list})")[1]
            for pid, sc in rows:
                out.setdefault(int(pid), {})[mkey] = _f(sc)
        except Exception:
            continue
    return out
