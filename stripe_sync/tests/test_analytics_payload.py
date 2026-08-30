"""Тесты аналитического payload: чистые хелперы + устойчивость build()."""

from stripe_sync import analytics_payload as ap


def test_country_name_and_flag():
    assert ap._country_name('US') == 'United States'
    assert ap._country_name('us') == 'United States'
    assert ap._country_name('') == 'Unknown'
    assert ap._country_name('ZZ') == 'ZZ'  # неизвестный код - как есть
    # флаг из ISO2: regional indicators; мусор -> глобус
    assert ap._flag('US') == '\U0001F1FA\U0001F1F8'
    assert ap._flag('') == '🌐'
    assert ap._flag('X') == '🌐'


def test_build_has_all_blocks_and_survives_bad_query():
    """Каждый блок в своём try/except: падение q не роняет весь payload."""
    def q_boom(_sql, _p=None):
        raise RuntimeError('ch down')
    d = ap.build(q_boom, 't1')
    for key in ('overview', 'growth', 'geography', 'funnel',
                'revenue', 'engagement', 'devices', 'events'):
        assert key in d and d[key] is None
    assert d['tenant'] == 't1'


def test_overview_shapes_numbers():
    """Стаб q по подстроке запроса: проверяем арифметику overview."""
    def q(sql, _p=None):
        if 'FROM user_actions' in sql:
            return (None, [[100, 20, 10, 40, 80]])         # total,paying,trial,a7,a30
        if 'coalesce(sum(mrr)' in sql:
            return (None, [[1000.0]])
        if 'saas_events_deduped' in sql:
            return (None, [[30, 5, 2]])                    # signups,paid,churn
        return (None, [[0]])
    ov = ap._overview(q, {'t': 't'})
    assert ov['users_total'] == 100 and ov['paying'] == 20
    assert ov['free'] == 70 and ov['mrr'] == 1000.0
    assert ov['arr'] == 12000.0 and ov['arpu'] == 50.0
    assert ov['paying_rate'] == 20.0
    assert ov['new_signups_30d'] == 30 and ov['churned_30d'] == 2


def test_funnel_percentages():
    def q(_sql, _p=None):
        return (None, [[200, 120, 60, 20]])
    fn = ap._funnel(q, {'t': 't'})
    steps = {s['key']: s for s in fn['steps']}
    assert steps['signup']['pct'] == 100.0
    assert steps['activated']['count'] == 120 and steps['activated']['pct'] == 60.0
    assert steps['paid']['pct'] == 10.0


def test_cash_splits_recurring_and_onetime():
    """Собранный кэш = recurring (есть sub) + разовые (sub пустой)."""
    def q(_sql, _p=None):
        # count, sum(amt), sumIf(has_sub), sumIf(NOT has_sub), countIf(NOT has_sub)
        return (None, [[34, 3276.0, 819.0, 2457.0, 13]])
    c = ap._cash(q, {'t': 't'})
    assert c['d30']['collected'] == 3276.0
    assert c['d30']['recurring'] == 819.0
    assert c['d30']['onetime'] == 2457.0
    assert c['d30']['onetime_count'] == 13
    assert c['d30']['invoices'] == 34
    # all-time окно тоже собирается (та же заглушка)
    assert c['all']['collected'] == 3276.0


def test_coverage_freshness_and_geo():
    def q(sql, _p=None):
        if 'max(ts)' in sql:
            return (None, [['2026-08-28 10:00:00', 30]])   # 30 мин назад
        return (None, [[400, 268]])                         # total, located
    c = ap._coverage(q, {'t': 't'})
    assert c['minutes_since'] == 30 and c['stale'] is False
    assert c['geo_pct'] == 67.0 and c['geo_located'] == 268

def test_coverage_stale_over_6h():
    def q(sql, _p=None):
        if 'max(ts)' in sql:
            return (None, [['2026-08-28 00:00:00', 500]])   # >6ч
        return (None, [[10, 0]])
    c = ap._coverage(q, {'t': 't'})
    assert c['stale'] is True and c['geo_pct'] == 0.0
