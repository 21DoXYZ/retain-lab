"""Экран «Запуски» + блок «вчера» для главной.

Отвечает маркетологу и фаундеру на два вопроса из JTBD:
  • «Что дал трафик по дням/запускам?»  - когорты по дате регистрации:
    регистрации → активация → оплата → деньги когорты (деньги догоняются
    во времени, поэтому считаем по identity, а не по дню платежа);
  • «Где люди застревают и как их дожать?» - готовые сегменты застревания
    с живым счётчиком и НАСТОЯЩИМ audience-фильтром: кнопка «кампания»
    открывает конструктор с этим же фильтром - обещанное = зачисленное.

Каждый блок в своём try/except (контракт _home_*). `q` - инъекция
player_board.q.
"""

from __future__ import annotations


def _flt(x) -> float:
    try:
        v = float(x or 0)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


# ── Когорты по дню регистрации ───────────────────────────────────────────────

def cohorts(q, tenant: str, days: int = 14) -> list | None:
    """По дню first_seen: signups, activated (>=1 генерация), paying,
    cash (все оплаченные инвойсы людей этой когорты - когорта догоняет)."""
    try:
        # user_actions может отдавать НЕСКОЛЬКО строк на identity (по подписке) -
        # прямой JOIN умножал кэш когорты в разы. Сжимаем до одной строки на
        # человека ДО джойна с деньгами.
        rows = q(f"""
            SELECT toDate(f.first_seen) AS d,
                   count() AS signups,
                   countIf(coalesce(f.generations_total, 0) > 0) AS activated,
                   countIf(ua.pay = 1) AS paying,
                   coalesce(sum(inv.cash), 0) AS cash
            FROM user_event_features f
            LEFT JOIN (
              SELECT identity_id,
                     max(sub_status IN ('active', 'past_due')) AS pay,
                     any(nullIf(stripe_customer_id, '')) AS cid
              FROM user_actions WHERE tenant_id = {{t:String}}
              GROUP BY identity_id
            ) ua ON ua.identity_id = f.identity_id
            LEFT JOIN (
              SELECT customer_id, sum(amt) AS cash FROM (
                SELECT invoice_id, argMax(customer_id, updated_at) AS customer_id,
                       argMax(amount_paid, updated_at) AS amt,
                       argMax(status, updated_at) AS st
                FROM stripe_invoices WHERE tenant_id = {{t:String}}
                GROUP BY invoice_id
              ) WHERE st = 'paid' GROUP BY customer_id
            ) inv ON inv.customer_id = ua.cid
            WHERE f.tenant_id = {{t:String}}
              AND f.first_seen >= today() - {int(days) - 1}
              AND toUnixTimestamp(f.first_seen) > 0
            GROUP BY d ORDER BY d DESC
            """, {'t': tenant})[1]
        return [{'day': str(r[0]), 'signups': int(r[1]), 'activated': int(r[2]),
                 'paying': int(r[3]), 'cash': round(_flt(r[4]), 2)} for r in rows]
    except Exception as exc:  # noqa: BLE001
        print(f'[launches] {tenant}: cohorts failed: {exc}', flush=True)
        return None


# ── Сегменты застревания ─────────────────────────────────────────────────────
# key -> audience-фильтр движка сегментов. Названия рисует фронт (i18n).
STUCK_SEGMENTS: list[tuple[str, dict]] = [
    # упёрся в цены/пейвол, но не платит - покупка была в голове
    ('paywall', {'status': 'free', 'saw_pricing': True}),
    # создал проект, но ни одной генерации - застрял до ценности
    ('no_gen', {'projects_min': 1, 'gens_max': 0}),
    # получил результат, но не забрал (не скачал за 14 дней)
    ('no_download', {'gens_min': 1, 'no_download': True, 'status': 'free'}),
    # молчат 14+ дней, а были активны - остывают
    ('gone_quiet', {'not_seen_days': 14, 'gens_min': 1, 'status': 'free'}),
]


def stuck_segments(q, tenant: str) -> list | None:
    """Счётчик + достижимость по каждому сегменту застревания."""
    from stripe_sync.segment import AUDIENCE_FROM, build
    out = []
    try:
        for key, audience in STUCK_SEGMENTS:
            conds, sparams, _ = build(dict(audience))
            where = " AND ".join(["ua.tenant_id = {t:String}"] + conds)
            r = q(f"SELECT count(), countIf(ua.email_norm != '') "
                  f"{AUDIENCE_FROM} WHERE {where}",
                  {'t': tenant, **sparams})[1][0]
            out.append({'key': key, 'count': int(r[0]),
                        'reachable_email': int(r[1]), 'audience': audience})
        return out
    except Exception as exc:  # noqa: BLE001
        print(f'[launches] {tenant}: segments failed: {exc}', flush=True)
        return out or None


# ── «Вчера» для главной ──────────────────────────────────────────────────────

def home_yesterday(q, tenant: str) -> dict | None:
    """Собрано вчера (+сегодня отдельно), отмены и рефанд-разговоры за сутки.
    recurring/разовое - по совпадению суммы с ценой подписки (см. _cash)."""
    try:
        p = {'t': tenant}
        prices = sorted({round(_flt(r[0]), 2) for r in q(
            "SELECT DISTINCT argMax(amount, updated_at) FROM stripe_subscriptions "
            "WHERE tenant_id = {t:String} GROUP BY subscription_id", p)[1]
            if _flt(r[0]) > 0})
        in_list = ", ".join(str(x) for x in prices) or "0"
        r = q(f"""
            SELECT round(sumIf(amt, toDate(c) = yesterday()), 2),
                   countIf(toDate(c) = yesterday()),
                   round(sumIf(amt, toDate(c) = yesterday() AND NOT is_rec), 2),
                   round(sumIf(amt, toDate(c) = today()), 2),
                   countIf(toDate(c) = today())
            FROM (
              SELECT invoice_id, argMax(amount_paid, updated_at) AS amt,
                     argMax(status, updated_at) AS st,
                     argMax(created_ts, updated_at) AS c,
                     round(argMax(amount_paid, updated_at), 2) IN ({in_list}) AS is_rec
              FROM stripe_invoices WHERE tenant_id = {{t:String}} GROUP BY invoice_id
            ) WHERE st = 'paid'""", p)[1][0]
        ev = q("""
            SELECT uniqExactIf(identity_id, event_type IN
                     ('billing.subscription_cancelled', 'billing.subscription_cancel_scheduled')),
                   uniqExactIf(coalesce(nullIf(JSONExtractString(meta, 'conversation_id'), ''),
                                        toString(identity_id)),
                     event_type = 'support.message'
                     AND positionCaseInsensitive(JSONExtractString(meta, 'text'), 'refund') > 0)
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND ts >= now() - INTERVAL 1 DAY
            """, p)[1][0]
        return {
            'collected': _flt(r[0]), 'payments': int(r[1]),
            'onetime': _flt(r[2]),
            'today_collected': _flt(r[3]), 'today_payments': int(r[4]),
            'cancels_24h': int(ev[0]), 'refund_talks_24h': int(ev[1]),
        }
    except Exception as exc:  # noqa: BLE001
        print(f'[launches] {tenant}: yesterday failed: {exc}', flush=True)
        return None
