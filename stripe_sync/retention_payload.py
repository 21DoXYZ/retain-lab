"""Экран «Удержание»: кто уходит, ПОЧЕМУ, и возвращаются ли люди вообще.

JTBD фаундера: «узнать о риске ДО отмены, чтобы успеть спасти». Скор без
причины бесполезен - карточка риска несёт ПРИЧИНЫ (usage-обрыв, ошибки,
разговор о возврате, карта истекает, несписание, затих) и деньги на кону.

Блоки:
  • risk_list  - платящие под риском с причинами (сортировка по $ на кону);
  • weekly     - недельные когорты возврата: D1/D7/D30 (доля вернувшихся);
  • saved      - что уже спасено кампаниями (uplift в $).

Контракт как у _home_*: блок падает в None, не роняя экран. `q` - инъекция.
"""

from __future__ import annotations


def _flt(x) -> float:
    try:
        v = float(x or 0)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


def risk_list(q, tenant: str, limit: int = 12) -> list | None:
    """Платящие с риском + машиночитаемые причины. Причины считаются из тех же
    фич, что и скоринг, - объяснение всегда совпадает с тем, что видела модель."""
    try:
        p = {'t': tenant}
        # разговоры о возврате за 14 дней: identity уже склеен стичем по email
        refund_ids = {str(r[0]) for r in q("""
            SELECT DISTINCT identity_id FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND event_type = 'support.message'
              AND positionCaseInsensitive(JSONExtractString(meta, 'text'), 'refund') > 0
              AND ts >= now() - INTERVAL 14 DAY
            """, p)[1]}
        cards = {str(r[0]) for r in q("""
            SELECT customer_id FROM card_expiry_current
            WHERE tenant_id = {t:String} AND days_to_expiry BETWEEN 0 AND 45
            """, p)[1]}
        rows = q("""
            SELECT ua.identity_id, ua.email_norm, ua.client_user_id,
                   toFloat64(ua.mrr), coalesce(ua.p_churn, 0), ua.stage,
                   ua.stripe_customer_id,
                   if(toUnixTimestamp(ua.last_seen) = 0, 10000,
                      dateDiff('day', ua.last_seen, now()))                  AS quiet_days,
                   coalesce(f.generations_7d, 0)                             AS g7,
                   coalesce(f.generations_prev_7d, 0)                        AS g_prev7,
                   coalesce(f.js_errors_7d, 0) + coalesce(f.rage_clicks_7d, 0) AS friction,
                   toUnixTimestamp(coalesce(f.last_payment_failed,
                                            toDateTime64(0, 3)))             AS pay_failed_ts
            FROM user_actions ua
            LEFT JOIN user_event_features f
              ON f.tenant_id = ua.tenant_id AND f.identity_id = ua.identity_id
            WHERE ua.tenant_id = {t:String}
              AND ua.sub_status IN ('active', 'past_due')
              AND (coalesce(ua.p_churn, 0) >= 0.2 OR ua.stage IN ('SAVE', 'DUNNING'))
            ORDER BY ua.value_at_stake DESC, ua.p_churn DESC
            LIMIT 40
            """, p)[1]
        out = []
        import time as _time
        now_ts = _time.time()
        for r in rows:
            email = str(r[1] or '')
            reasons = []
            if r[11] and (now_ts - float(r[11])) < 14 * 86400:
                reasons.append('payment_failed')
            if str(r[0]) in refund_ids:
                reasons.append('refund_talk')
            if int(r[8]) == 0 and int(r[9]) > 0:
                reasons.append('usage_drop')
            if int(r[7]) >= 7:
                reasons.append('gone_quiet')
            if int(r[10]) > 0:
                reasons.append('friction')
            if str(r[6] or '') in cards:
                reasons.append('card_expiring')
            if not reasons:
                reasons.append('score_only')
            out.append({
                'identity_id': str(r[0]),
                'email': email or str(r[2] or '')[:24] or str(r[0])[:8],
                'mrr': round(_flt(r[3]), 0),
                'p_churn': round(_flt(r[4]), 2),
                'stage': str(r[5]),
                'reasons': reasons,
            })
        # разговор о возврате важнее любого скора - наверх
        out.sort(key=lambda x: ('refund_talk' not in x['reasons'],
                                'payment_failed' not in x['reasons'], -x['mrr']))
        return out[:limit]
    except Exception as exc:  # noqa: BLE001
        print(f'[retention] {tenant}: risk_list failed: {exc}', flush=True)
        return None


def weekly_return(q, tenant: str, weeks: int = 6) -> list | None:
    """Недельные когорты: из зарегистрировавшихся на неделе W - какая доля
    вернулась на день 1 / в дни 2-7 / в дни 8-30 (по любому событию)."""
    try:
        rows = q(f"""
            WITH firsts AS (
              SELECT identity_id, min(toDate(ts)) AS d0
              FROM saas_events_deduped
              WHERE tenant_id = {{t:String}} AND source IN ('snippet', 'product')
              GROUP BY identity_id
              HAVING d0 >= toMonday(today()) - {int(weeks) * 7}
            ),
            act AS (
              SELECT e.identity_id, f.d0,
                     max(toDate(e.ts) = f.d0 + 1)                          AS r1,
                     max(toDate(e.ts) BETWEEN f.d0 + 2 AND f.d0 + 7)       AS r7,
                     max(toDate(e.ts) BETWEEN f.d0 + 8 AND f.d0 + 30)      AS r30
              FROM saas_events_deduped e
              INNER JOIN firsts f ON f.identity_id = e.identity_id
              WHERE e.tenant_id = {{t:String}} AND e.source IN ('snippet', 'product')
              GROUP BY e.identity_id, f.d0
            )
            SELECT toMonday(d0) AS week, count() AS cohort,
                   round(avg(r1) * 100, 1) AS d1,
                   round(avg(r7) * 100, 1) AS d7,
                   round(avg(r30) * 100, 1) AS d30
            FROM act GROUP BY week ORDER BY week DESC
            """, {'t': tenant})[1]
        return [{'week': str(r[0]), 'cohort': int(r[1]),
                 'd1': _flt(r[2]), 'd7': _flt(r[3]), 'd30': _flt(r[4])}
                for r in rows]
    except Exception as exc:  # noqa: BLE001
        print(f'[retention] {tenant}: weekly failed: {exc}', flush=True)
        return None


def saved(q, tenant: str) -> dict | None:
    """Что уже спасли кампании: подтверждённый прирост против holdout."""
    try:
        r = q("""
            SELECT coalesce(sum(inc), 0), count()
            FROM (
              SELECT campaign_id, argMax(incremental_usd, computed_at) AS inc
              FROM uplift_reports WHERE tenant_id = {t:String} GROUP BY campaign_id)
            WHERE inc > 0
            """, {'t': tenant})[1][0]
        return {'uplift_usd': round(_flt(r[0]), 2), 'campaigns': int(r[1])}
    except Exception as exc:  # noqa: BLE001
        print(f'[retention] {tenant}: saved failed: {exc}', flush=True)
        return None
