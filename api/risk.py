"""api/risk.py — JSON-домен «Риск и фрод»: единая лента флагов (W2-T3).

Экран SPA: /flags. Эндпоинт: GET /api/v1/risk/flags?kind=

Лента сводит УЖЕ посчитанные системой сигналы в одну очередь «требует проверки».
Математику НЕ переписываем — каждый источник берёт ТОТ ЖЕ запрос, что и его
родной экран (паритет цифр):
  • no_deposit_withdrawal — запрос «zd» из api/money.py::audit (money.py:432-436):
    manual_withdrawal > 50k при депозитах < 10% от вывода. entity=player.
  • suspicious_operator   — reviewers с unclear_pct >= 40 (money.py:425) + бейдж
    is_admin. entity=operator, amount = сумма их списаний.
  • affiliate_players_win (ggr_real < 0) / affiliate_cash_drain (net_profit < 0) —
    логика api/affiliates.py:144-145. entity=affiliate.
  • bonus_abuse           — игроки персоны «🎁 Бонусник» (PERSONA_SQL) с net > 0
    (в плюсе на фриспинах). entity=player, amount = net.

severity: 3 при amount >= 100000, 2 при >= 20000, иначе 1.
Сортировка: severity desc, amount desc. Лимит 200 строк суммарно (по amount).
totals.by_kind — ПОЛНЫЕ counts (до лимита в 200). checked_at = now UTC iso.

Регистрация — по переменной `bp` (пакет api/ авто-подхватывает модуль).
Роли = AUDIT_ROLES из api/money.py (включает risk_officer).
"""
from __future__ import annotations

import datetime as _dt

from flask import Blueprint, request

from .core import require_auth, api_json
from .money import AUDIT_ROLES  # единый источник ролевой матрицы аудита
# готовые запросы/константы борда (математику не переписываем)
from player_board import q, CAT, PERSONA_SQL, DEP_OK, WD_OK, aff_ggr_split

bp = Blueprint('api_risk', __name__, url_prefix='/api/v1')

# Виды флагов (порядок = порядок плиток на экране).
KINDS = (
    'no_deposit_withdrawal',
    'suspicious_operator',
    'affiliate_players_win',
    'affiliate_cash_drain',
    'bonus_abuse',
)

# Общий лимит ленты (после сортировки по severity/amount).
FEED_LIMIT = 200


def _flt(x) -> float:
    """None/NaN-safe float (как в остальных доменах)."""
    try:
        v = float(x or 0)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


def _severity(amount: float) -> int:
    """3 — крупный (>=100k), 2 — заметный (>=20k), 1 — прочее."""
    a = abs(amount)
    if a >= 100000:
        return 3
    if a >= 20000:
        return 2
    return 1


def _row(kind: str, entity: str, ident, label: str, amount: float,
         count: int, href: str, details: dict) -> dict:
    """Единая строка ленты. amount_try — денежная величина (тон neg на фронте)."""
    amt = _flt(amount)
    return {
        'kind': kind,
        'entity': entity,
        'id': ident,
        'label': label,
        'amount_try': round(amt, 2),
        'count': int(count or 0),
        'severity': _severity(amt),
        'href': href,
        'details': details,
    }


def _no_deposit_withdrawal_rows() -> list[dict]:
    """Крупные ручные списания у игроков с депозитом < 10% вывода.
    Запрос «zd» дословно из api/money.py::audit (money.py:432-436, LIMIT 80)."""
    zd = q("""WITH mw AS (SELECT casino_player_id, sum(amount) wd, count() n
        FROM money_transactions WHERE type='manual_withdrawal' AND status='completed'
        GROUP BY casino_player_id),
      dp AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') dep
        FROM money_transactions GROUP BY casino_player_id)
      SELECT mw.casino_player_id, u.account_type, round(mw.wd), round(coalesce(dp.dep,0)), mw.n
      FROM mw LEFT JOIN dp ON dp.casino_player_id=mw.casino_player_id
              LEFT JOIN users u ON u.casino_player_id=mw.casino_player_id
      WHERE mw.wd > 50000 AND toFloat64(coalesce(dp.dep,0)) < toFloat64(mw.wd)*0.1
      ORDER BY mw.wd DESC LIMIT 80""")[1]
    rows = []
    for zpid, zat, zwd, zdep, zn in zd:
        pid = int(zpid)
        rows.append(_row(
            'no_deposit_withdrawal', 'player', pid, str(pid),
            amount=_flt(zwd), count=int(zn or 0), href=f'/players/{pid}',
            details={'deposited': _flt(zdep), 'ops': int(zn or 0),
                     'account_type': zat or 'normal'},
        ))
    return rows


def _suspicious_operator_rows() -> list[dict]:
    """Ревьюеры с долей «непонятных» списаний >= 40% (тест/прочее/без пометки).
    Запрос — как api/money.py::audit (money.py:425, LIMIT 15) + бейдж is_admin."""
    admins = {r[0] for r in q(
        "SELECT toString(casino_player_id) FROM users "
        "WHERE role IN ('admin','support') OR account_type='service'")[1]}
    apprs = q(f"""SELECT reviewed_by, count(), round(sum(amount)),
        round(100*sumIf(amount, {CAT} IN ('🧪 тест-операции','прочее','(без пометки)'))/sum(amount))
      FROM money_transactions WHERE type='manual_withdrawal' AND status='completed'
      GROUP BY reviewed_by ORDER BY 3 DESC LIMIT 15""")[1]
    rows = []
    for rb, c, s, unclear in apprs:
        up = _flt(unclear)
        if up < 40:
            continue
        rb_s = str(rb)
        rows.append(_row(
            'suspicious_operator', 'operator', rb_s, rb_s,
            amount=_flt(s), count=int(c or 0), href='/audit',
            details={'unclear_pct': up, 'ops_count': int(c or 0),
                     'is_admin': rb_s in admins},
        ))
    return rows


def _affiliate_rows() -> tuple[list[dict], list[dict]]:
    """Аффилиаты «игроки бьют игры» (ggr_real < 0) и «касса в минусе»
    (net_profit < 0). Считаем как api/affiliates.py (unfiltered-ветка, :78-153):
    ggr_real = real_bets - real_wins; net_profit = deposits - withdrawals."""
    _, pf = q("""SELECT affiliate_code, count() players, countIf(ftd_amount>0) ftd
        FROM player_features WHERE account_type='normal' AND affiliate_code!=''
        GROUP BY affiliate_code""")
    _, mny = q(f"""SELECT u.affiliate_code,
        round(sumIf(m.amount, m.{DEP_OK}),2) dep,
        round(sumIf(abs(m.amount), m.{WD_OK}),2) wd
      FROM money_transactions m
      INNER JOIN (SELECT casino_player_id, affiliate_code FROM users
                  WHERE account_type='normal' AND affiliate_code!='') u USING(casino_player_id)
      GROUP BY u.affiliate_code""")
    G4 = aff_ggr_split()  # {code: (real_bets, real_wins, fs_bets, fs_wins)}

    PF = {r[0]: r for r in pf}
    M = {r[0]: r for r in mny}
    codes = set(PF) | set(M) | set(G4)

    pwin, cash = [], []
    for code in codes:
        players = int(PF[code][1]) if code in PF else 0
        ftd = int(PF[code][2]) if code in PF else 0
        mr = M.get(code)
        dep = float(mr[1] or 0) if mr else 0.0
        wd = float(mr[2] or 0) if mr else 0.0
        rb, rw, _fb, _fw = G4.get(code, (0.0, 0.0, 0.0, 0.0))
        ggr_real = rb - rw
        net_profit = dep - wd
        href = f'/affiliates/{code}'
        if ggr_real < 0:  # api/affiliates.py:144 — pw
            pwin.append(_row(
                'affiliate_players_win', 'affiliate', code, str(code),
                amount=abs(ggr_real), count=players, href=href,
                details={'players': players, 'ftd': ftd,
                         'ggr_real': round(ggr_real, 2)},
            ))
        if net_profit < 0:  # api/affiliates.py:145 — cd
            cash.append(_row(
                'affiliate_cash_drain', 'affiliate', code, str(code),
                amount=abs(net_profit), count=players, href=href,
                details={'players': players, 'ftd': ftd,
                         'net_profit': round(net_profit, 2)},
            ))
    return pwin, cash


def _bonus_abuse_rows() -> tuple[list[dict], int]:
    """Игроки архетипа «🎁 Бонусник» (PERSONA_SQL) с net > 0 — в плюсе на
    фриспинах. Возвращает (top-строки по net, полный count для totals)."""
    total = int(q(f"""SELECT count() FROM (
        SELECT {PERSONA_SQL} persona, net FROM player_features WHERE account_type='normal')
      WHERE persona='🎁 Бонусник' AND net > 0""")[1][0][0] or 0)
    top = q(f"""SELECT casino_player_id, round(net), round(freespin_ratio,3) FROM (
        SELECT casino_player_id, net, freespin_ratio, {PERSONA_SQL} persona
        FROM player_features WHERE account_type='normal')
      WHERE persona='🎁 Бонусник' AND net > 0 ORDER BY net DESC LIMIT {FEED_LIMIT}""")[1]
    rows = []
    for pid, net, fsr in top:
        p = int(pid)
        rows.append(_row(
            'bonus_abuse', 'player', p, str(p),
            amount=_flt(net), count=1, href=f'/players/{p}',
            details={'freespin_ratio': _flt(fsr)},
        ))
    return rows, total


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/risk/flags — единая лента флагов (все виды или ?kind=<вид>)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/risk/flags')
@require_auth(roles=AUDIT_ROLES)
def risk_flags():
    """Агрегированная очередь «требует проверки». Каждый источник — свой готовый
    запрос (математика 1-в-1 с /audit и /affiliates). totals.by_kind — полные
    counts до лимита в 200; сама лента — топ-200 по severity/amount."""
    kind = request.args.get('kind') or ''
    kind = kind if kind in KINDS else ''

    nd_rows = _no_deposit_withdrawal_rows()
    op_rows = _suspicious_operator_rows()
    pwin_rows, cash_rows = _affiliate_rows()
    ba_rows, ba_total = _bonus_abuse_rows()

    # полные counts по видам (до общего лимита) — для плиток и сверки с источниками
    by_kind = {
        'no_deposit_withdrawal': len(nd_rows),
        'suspicious_operator': len(op_rows),
        'affiliate_players_win': len(pwin_rows),
        'affiliate_cash_drain': len(cash_rows),
        'bonus_abuse': ba_total,
    }

    rows = nd_rows + op_rows + pwin_rows + cash_rows + ba_rows
    if kind:
        rows = [r for r in rows if r['kind'] == kind]
    # severity desc, amount desc → топ-200 (severity монотонна по amount)
    rows.sort(key=lambda r: (r['severity'], r['amount_try']), reverse=True)
    rows = rows[:FEED_LIMIT]

    return api_json({
        'rows': rows,
        'totals': {'by_kind': by_kind, 'total': sum(by_kind.values())},
        'kind': kind or None,
        'checked_at': _dt.datetime.now(_dt.timezone.utc).isoformat(),
    })
