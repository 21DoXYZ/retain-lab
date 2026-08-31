"""Экран «Деньги»: откуда деньги и ПОЧЕМУ изменились.

JTBD фаундера: «когда выручка просела - узнать причину, а не факт». Ядро -
разложение: собранное = регистрации × активация × конверсия × средний чек.
Сравниваем окно 30 дней с предыдущими 30: какой множитель просел - тот и
чинить (трафик / продукт / оффер / прайс). Плюс отмены с причинами из
cancel_reasons (LLM-категоризация cancel-flow и чатов).

Контракт как у _home_*. `q` - инъекция player_board.q.
"""

from __future__ import annotations


def _flt(x) -> float:
    try:
        v = float(x or 0)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


def _window(q, tenant: str, frm: int, to: int) -> dict:
    """Факторы за окно [today-frm, today-to): signups, activated, payers, cash."""
    p = {'t': tenant}
    f = q(f"""
        SELECT count(),
               countIf(coalesce(generations_total, 0) > 0)
        FROM user_event_features
        WHERE tenant_id = {{t:String}}
          AND toDate(first_seen) >= today() - {int(frm)}
          AND toDate(first_seen) < today() - {int(to)}
        """, p)[1][0]
    m = q(f"""
        SELECT uniqExact(customer_id), round(sum(amt), 2) FROM (
          SELECT invoice_id, argMax(customer_id, updated_at) AS customer_id,
                 argMax(amount_paid, updated_at) AS amt,
                 argMax(status, updated_at) AS st,
                 argMax(created_ts, updated_at) AS c
          FROM stripe_invoices WHERE tenant_id = {{t:String}} GROUP BY invoice_id
        ) WHERE st = 'paid'
          AND toDate(c) >= today() - {int(frm)} AND toDate(c) < today() - {int(to)}
        """, p)[1][0]
    signups, activated = int(f[0]), int(f[1])
    payers, cash = int(m[0]), _flt(m[1])
    return {
        'signups': signups,
        'activated': activated,
        'act_rate': round(activated / signups * 100, 1) if signups else 0.0,
        'payers': payers,
        'conv_rate': round(payers / signups * 100, 1) if signups else 0.0,
        'avg_check': round(cash / payers, 2) if payers else 0.0,
        'cash': round(cash, 2),
    }


def decomposition(q, tenant: str) -> dict | None:
    """30 дней против предыдущих 30: по каждому множителю - было/стало/Δ%.
    worst - множитель с самым глубоким падением (его дашборд красит красным)."""
    try:
        cur = _window(q, tenant, 30, 0)
        prev = _window(q, tenant, 60, 30)
        factors = []
        for key in ('signups', 'act_rate', 'conv_rate', 'avg_check'):
            was, now = _flt(prev[key]), _flt(cur[key])
            delta = round((now - was) / was * 100, 1) if was else None
            factors.append({'key': key, 'prev': was, 'cur': now, 'delta_pct': delta})
        drops = [f for f in factors if f['delta_pct'] is not None and f['delta_pct'] < 0]
        worst = min(drops, key=lambda f: f['delta_pct'])['key'] if drops else ''
        return {'current': cur, 'previous': prev, 'factors': factors, 'worst': worst}
    except Exception as exc:  # noqa: BLE001
        print(f'[money] {tenant}: decomposition failed: {exc}', flush=True)
        return None


def cancel_reasons(q, tenant: str, days: int = 60) -> list | None:
    """Отмены по причинам (LLM-категории из cancel-flow и чатов поддержки)."""
    try:
        rows = q(f"""
            SELECT category, count() AS n, round(sum(toFloat64(mrr)), 2) AS mrr_lost,
                   groupArray(3)(summary) AS examples
            FROM (
              SELECT event_id, argMax(category, created_at) AS category,
                     argMax(summary, created_at) AS summary,
                     argMax(mrr, created_at) AS mrr,
                     argMax(ts, created_at) AS ts
              FROM cancel_reasons WHERE tenant_id = {{t:String}} GROUP BY event_id
            )
            WHERE ts >= now() - INTERVAL {int(days)} DAY
            GROUP BY category ORDER BY n DESC
            """, {'t': tenant})[1]
        return [{'category': str(r[0]), 'count': int(r[1]),
                 'mrr_lost': _flt(r[2]), 'examples': [str(x) for x in (r[3] or [])]}
                for r in rows]
    except Exception as exc:  # noqa: BLE001
        print(f'[money] {tenant}: cancel_reasons failed: {exc}', flush=True)
        return None
