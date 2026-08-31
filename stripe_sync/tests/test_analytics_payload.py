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
        if 'first_seen' in sql:
            return (None, [[30]])                          # signups из features
        if 'saas_events_deduped' in sql:
            return (None, [[0, 5, 2]])                     # -,paid,churn
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


def test_recurring_amounts_coupon_rule():
    """Купонные суммы признаются подписочными, только если та же скидка
    видна минимум на двух прайсах (аудит 31.08: 33.15/84.15 улетали в разовые,
    а 170.55 не должен пролезать)."""
    def q(sql, _p=None):
        if 'stripe_subscriptions' in sql:
            return (None, [[9.0], [39.0], [99.0]])
        return (None, [[9.0], [39.0], [99.0], [33.15], [84.15], [4.05],
                       [17.55], [189.0], [170.55], [95.0]])
    rec = ap._recurring_amounts(q, {'t': 't'})
    assert {9.0, 39.0, 99.0} <= rec
    assert 33.15 in rec and 84.15 in rec      # -15%: виден на 39 и 99
    assert 4.05 in rec and 17.55 in rec       # -55%: виден на 9 и 39
    # одиночные суммы, не кратные прайсу со известной скидкой, - не подписка
    assert 189.0 not in rec and 170.55 not in rec and 95.0 not in rec


def test_recurring_single_price_discount_rejected():
    """Скидка, замеченная лишь на ОДНОМ прайсе, не признаётся купоном -
    это может быть совпадение с разовым оффером."""
    def q(sql, _p=None):
        if 'stripe_subscriptions' in sql:
            return (None, [[9.0], [39.0], [99.0]])
        return (None, [[9.0], [4.05], [189.0]])
    rec = ap._recurring_amounts(q, {'t': 't'})
    assert 4.05 not in rec


def test_invoice_subscription_from_parent():
    import mapper
    assert mapper._invoice_subscription({'subscription': 'sub_1'}) == 'sub_1'
    assert mapper._invoice_subscription(
        {'parent': {'subscription_details': {'subscription': 'sub_2'}}}) == 'sub_2'
    assert mapper._invoice_subscription(
        {'lines': {'data': [{'parent': {'subscription_item_details':
                                        {'subscription': 'sub_3'}}}]}}) == 'sub_3'
    assert mapper._invoice_subscription({}) == ''
