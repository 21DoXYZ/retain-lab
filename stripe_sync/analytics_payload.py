"""Аналитический дашборд тенанта: один payload на всю вкладку «Аналитика».

Отвечает на вопрос собственника «что вообще происходит»: рост, деньги, гео,
воронка, вовлечённость, устройства. Всё из наших же событий (saas_events_*,
user_actions, mrr_facts) - ни одной внешней зависимости.

Два режима:
  • внутренний (public=False)  - всё, включая имена людей в срезах;
  • публичный  (public=True)   - только агрегаты, без единого email/имени
    (внешняя ссылка read-only, которую владелец даёт инвестору/партнёру).

Каждый блок собран в своём try/except: упавший кусок отдаёт None, а не роняет
весь дашборд (тот же контракт, что у _home_* в api/saas.py). Функция `q` -
инъекция player_board.q (columns, rows), чтобы не тащить сюда flask-контекст.
"""

from __future__ import annotations

from datetime import date, timedelta


def _flt(x) -> float:
    try:
        v = float(x or 0)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


# Страна ISO2 -> человекочитаемое имя + флаг (эмодзи). Покрывает то, что реально
# встречается у SaaS-аудитории; неизвестный код показываем как есть.
_COUNTRY = {
    'US': 'United States', 'GB': 'United Kingdom', 'DE': 'Germany', 'FR': 'France',
    'CA': 'Canada', 'AU': 'Australia', 'IN': 'India', 'BR': 'Brazil', 'NL': 'Netherlands',
    'ES': 'Spain', 'IT': 'Italy', 'PL': 'Poland', 'UA': 'Ukraine', 'RU': 'Russia',
    'TR': 'Turkey', 'MX': 'Mexico', 'JP': 'Japan', 'KR': 'South Korea', 'CN': 'China',
    'SG': 'Singapore', 'AE': 'UAE', 'SE': 'Sweden', 'CH': 'Switzerland', 'IE': 'Ireland',
    'PT': 'Portugal', 'ID': 'Indonesia', 'PH': 'Philippines', 'NG': 'Nigeria',
    'ZA': 'South Africa', 'AR': 'Argentina', 'CL': 'Chile', 'CO': 'Colombia',
    'NO': 'Norway', 'DK': 'Denmark', 'FI': 'Finland', 'BE': 'Belgium', 'AT': 'Austria',
    'CZ': 'Czechia', 'RO': 'Romania', 'GR': 'Greece', 'IL': 'Israel', 'HK': 'Hong Kong',
    'TW': 'Taiwan', 'MY': 'Malaysia', 'TH': 'Thailand', 'VN': 'Vietnam', 'NZ': 'New Zealand',
    'SA': 'Saudi Arabia', 'EG': 'Egypt', 'PK': 'Pakistan', 'BD': 'Bangladesh',
}


def _country_name(code: str) -> str:
    code = (code or '').upper()
    return _COUNTRY.get(code, code or 'Unknown')


def _flag(code: str) -> str:
    code = (code or '').upper()
    if len(code) != 2 or not code.isalpha():
        return '🌐'
    return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)


def build(q, tenant: str, public: bool = False) -> dict:
    """Собрать весь payload вкладки. `q(sql, params) -> (columns, rows)`."""
    p = {'t': tenant}
    out: dict = {
        'tenant': tenant,
        'overview': _overview(q, p),
        'growth': _growth(q, p),
        'geography': _geography(q, p),
        'funnel': _funnel(q, p),
        'revenue': _revenue(q, p),
        'engagement': _engagement(q, p),
        'devices': _devices(q, p),
        'events': _events(q, p),
    }
    return out


def _overview(q, p) -> dict | None:
    """Верхние KPI: люди, деньги, движение за 30 дней."""
    try:
        u = q("""
            SELECT count(),
                   countIf(sub_status IN ('active', 'past_due')),
                   countIf(sub_status = 'trialing'),
                   countIf(toUnixTimestamp(last_seen) > 0 AND last_seen >= now() - INTERVAL 7 DAY),
                   countIf(toUnixTimestamp(last_seen) > 0 AND last_seen >= now() - INTERVAL 30 DAY)
            FROM user_actions WHERE tenant_id = {t:String}
            """, p)[1][0]
        mrr = _flt(q("SELECT coalesce(sum(mrr), 0) FROM mrr_facts WHERE tenant_id = {t:String}", p)[1][0][0])
        # приход/отток за 30 дней (по событиям, deduped)
        mv = q("""
            SELECT uniqExactIf(identity_id, event_type = 'signup'),
                   uniqExactIf(identity_id, event_type = 'billing.invoice_paid'),
                   uniqExactIf(identity_id, event_type IN
                     ('billing.subscription_cancelled', 'billing.subscription_cancel_scheduled'))
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND ts >= now() - INTERVAL 30 DAY
            """, p)[1][0]
        total, paying, trialing = int(u[0]), int(u[1]), int(u[2])
        return {
            'users_total': total,
            'paying': paying,
            'trialing': trialing,
            'free': max(total - paying - trialing, 0),
            'active_7d': int(u[3]),
            'active_30d': int(u[4]),
            'mrr': round(mrr, 2),
            'arr': round(mrr * 12, 2),
            'arpu': round(mrr / paying, 2) if paying else 0.0,
            'new_signups_30d': int(mv[0]),
            'new_paying_30d': int(mv[1]),
            'churned_30d': int(mv[2]),
            'paying_rate': round(paying / total * 100, 1) if total else 0.0,
        }
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] overview failed: {exc}', flush=True)
        return None


def _growth(q, p) -> dict | None:
    """30-дневные ряды: подписки, активные, генерации, новые платящие + рост базы."""
    try:
        act = {str(r[0]): (int(r[1]), int(r[2])) for r in q("""
            SELECT toDate(ts) AS d,
                   uniqExactIf(identity_id, source IN ('snippet', 'product')),
                   countIf(event_type = 'generation_completed')
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND ts >= today() - 29
            GROUP BY d
            """, p)[1]}
        sig = {str(r[0]): int(r[1]) for r in q("""
            SELECT toDate(first_seen) AS d, count()
            FROM user_event_features
            WHERE tenant_id = {t:String} AND first_seen >= today() - 29
            GROUP BY d
            """, p)[1]}
        pay = {str(r[0]): int(r[1]) for r in q("""
            SELECT toDate(ts) AS d, uniqExact(identity_id)
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND event_type = 'billing.invoice_paid'
              AND ts >= today() - 29
            GROUP BY d
            """, p)[1]}
        # накопленная база на начало окна (всё, что было до 30 дней назад)
        base_before = int(q("""
            SELECT count() FROM user_event_features
            WHERE tenant_id = {t:String} AND first_seen < today() - 29
            """, p)[1][0][0])
        grid = [(date.today() - timedelta(days=29 - i)) for i in range(30)]
        signups = [sig.get(str(d), 0) for d in grid]
        cum, running = [], base_before
        for s in signups:
            running += s
            cum.append(running)
        return {
            'days': [d.strftime('%d.%m') for d in grid],
            'signups': signups,
            'active': [act.get(str(d), (0, 0))[0] for d in grid],
            'generations': [act.get(str(d), (0, 0))[1] for d in grid],
            'new_paying': [pay.get(str(d), 0) for d in grid],
            'cumulative_users': cum,
        }
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] growth failed: {exc}', flush=True)
        return None


def _geography(q, p) -> dict | None:
    """Топ стран: люди + платящие + MRR по стране. Страна = лучшая по юзеру
    (argMaxIf в user_event_features.geo_country уже отбрасывает пустые)."""
    try:
        rows = q("""
            SELECT f.geo_country AS c,
                   count() AS users,
                   countIf(ua.sub_status IN ('active', 'past_due')) AS paying,
                   sum(toFloat64OrZero(toString(ua.mrr))) AS mrr
            FROM user_event_features f
            LEFT JOIN user_actions ua
              ON ua.tenant_id = f.tenant_id AND ua.identity_id = f.identity_id
            WHERE f.tenant_id = {t:String} AND f.geo_country != ''
            GROUP BY c ORDER BY users DESC LIMIT 20
            """, p)[1]
        countries = [{
            'code': str(r[0]),
            'name': _country_name(str(r[0])),
            'flag': _flag(str(r[0])),
            'users': int(r[1]),
            'paying': int(r[2]),
            'mrr': round(_flt(r[3]), 2),
        } for r in rows]
        known = sum(c['users'] for c in countries)
        total = int(q("SELECT count() FROM user_event_features WHERE tenant_id = {t:String}", p)[1][0][0])
        return {'countries': countries, 'known': known, 'total': total,
                'unknown': max(total - known, 0)}
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] geography failed: {exc}', flush=True)
        return None


def _funnel(q, p) -> dict | None:
    """Путь до денег: регистрация -> первый проект -> первая ценность -> оплата."""
    try:
        r = q("""
            SELECT count(),
                   countIf(coalesce(f.projects_total, 0) > 0),
                   countIf(coalesce(f.generations_total, 0) > 0),
                   countIf(ua.sub_status IN ('active', 'past_due'))
            FROM user_actions ua
            LEFT JOIN user_event_features f
              ON f.tenant_id = ua.tenant_id AND f.identity_id = ua.identity_id
            WHERE ua.tenant_id = {t:String}
            """, p)[1][0]
        steps = [int(r[0]), int(r[1]), int(r[2]), int(r[3])]
        base = steps[0] or 1
        return {
            'steps': [
                {'key': 'signup', 'count': steps[0], 'pct': 100.0},
                {'key': 'activated', 'count': steps[1], 'pct': round(steps[1] / base * 100, 1)},
                {'key': 'value', 'count': steps[2], 'pct': round(steps[2] / base * 100, 1)},
                {'key': 'paid', 'count': steps[3], 'pct': round(steps[3] / base * 100, 1)},
            ],
        }
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] funnel failed: {exc}', flush=True)
        return None


def _revenue(q, p) -> dict | None:
    """Деньги: MRR по планам + распределение платящих."""
    try:
        # mrr в mrr_facts - вычисляемая (агрегатная) колонка вью: фильтровать её
        # в WHERE нельзя (ILLEGAL_AGGREGATION), только HAVING поверх суммы.
        rows = q("""
            SELECT coalesce(nullIf(plan_id, ''), 'unknown') AS plan,
                   count() AS n,
                   coalesce(sum(mrr), 0) AS mrr_sum
            FROM mrr_facts
            WHERE tenant_id = {t:String}
            GROUP BY plan HAVING mrr_sum > 0
            ORDER BY mrr_sum DESC LIMIT 12
            """, p)[1]
        plans = [{'plan': str(r[0]), 'count': int(r[1]), 'mrr': round(_flt(r[2]), 2)}
                 for r in rows]
        total = sum(pl['mrr'] for pl in plans) or 1.0
        for pl in plans:
            pl['share'] = round(pl['mrr'] / total * 100, 1)
        return {'plans': plans, 'mrr_total': round(sum(pl['mrr'] for pl in plans), 2)}
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] revenue failed: {exc}', flush=True)
        return None


def _engagement(q, p) -> dict | None:
    """Вовлечённость: DAU/WAU/MAU, липкость, генераций на активного."""
    try:
        r = q("""
            SELECT uniqExactIf(identity_id, ts >= now() - INTERVAL 1 DAY),
                   uniqExactIf(identity_id, ts >= now() - INTERVAL 7 DAY),
                   uniqExactIf(identity_id, ts >= now() - INTERVAL 30 DAY),
                   countIf(event_type = 'generation_completed' AND ts >= now() - INTERVAL 30 DAY)
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND source IN ('snippet', 'product')
            """, p)[1][0]
        dau, wau, mau, gens = int(r[0]), int(r[1]), int(r[2]), int(r[3])
        return {
            'dau': dau, 'wau': wau, 'mau': mau,
            'stickiness': round(dau / mau * 100, 1) if mau else 0.0,
            'gens_per_active_30d': round(gens / mau, 1) if mau else 0.0,
        }
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] engagement failed: {exc}', flush=True)
        return None


def _devices(q, p) -> dict | None:
    """Устройства: мобайл/десктоп + топ платформ (из meta сниппета)."""
    try:
        r = q("""
            SELECT countIf(JSONExtractInt(meta, 'mobile') = 1),
                   countIf(JSONHas(meta, 'mobile') AND JSONExtractInt(meta, 'mobile') = 0)
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND source = 'snippet'
              AND ts >= now() - INTERVAL 30 DAY
            """, p)[1][0]
        mobile, desktop = int(r[0]), int(r[1])
        plats = [{'name': str(pr[0]), 'count': int(pr[1])} for pr in q("""
            SELECT JSONExtractString(meta, 'platform') AS pl, count()
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND source = 'snippet'
              AND JSONExtractString(meta, 'platform') != ''
              AND ts >= now() - INTERVAL 30 DAY
            GROUP BY pl ORDER BY count() DESC LIMIT 6
            """, p)[1]]
        return {'mobile': mobile, 'desktop': desktop, 'platforms': plats}
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] devices failed: {exc}', flush=True)
        return None


def _events(q, p) -> dict | None:
    """Пульс продукта: топ типов событий за 30 дней (что люди вообще делают)."""
    try:
        # прячем чистую телеметрию (сеть/видимость/сессия) - блок про то, что
        # люди ДЕЛАЮТ в продукте, а не про технические тики браузера
        rows = q("""
            SELECT event_type, count()
            FROM saas_events_deduped
            WHERE tenant_id = {t:String} AND ts >= now() - INTERVAL 30 DAY
              AND event_type NOT IN (
                'heartbeat', 'ping', 'network_change', 'visibility_change',
                'session_start', 'session_end', 'inapp_shown', 'inapp_dismissed',
                'scroll', 'focus', 'blur', 'resize', 'online', 'offline')
            GROUP BY event_type ORDER BY count() DESC LIMIT 12
            """, p)[1]
        return {'top': [{'type': str(r[0]), 'count': int(r[1])} for r in rows]}
    except Exception as exc:  # noqa: BLE001
        print(f'[analytics] events failed: {exc}', flush=True)
        return None
