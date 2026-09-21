"""Экран Кампаний обязан показывать тот же базовый K7, что реально шлёт tick.

Вертикальные дефолты (service) накладываются в campaign_tick ДО overrides;
если экран их не накладывает, владелец сервисного тенанта видит ecom-текст
(«Running low on ...») и цель order_confirmed, которых у него нет.
"""

import sys
import types

if 'player_board' not in sys.modules:
    _pb = types.ModuleType('player_board')
    _pb.q = lambda *a, **k: ([], [])
    sys.modules['player_board'] = _pb

import api.saas as saas  # noqa: E402


def _k7(conf):
    return next(c for c in conf.get('campaigns', [])
                if c.get('campaign_id') == 'K7_replenishment')


def test_campaigns_conf_applies_service_vertical(monkeypatch):
    tenants = {'groom': {'replenishment': {
        'enabled': True, 'vertical': 'service',
        'plan_source_events': ['visit_completed']}}}
    from stripe_sync import channels_admin as ca
    monkeypatch.setattr(saas.ca, 'load_tenants', lambda *a, **k: tenants)
    monkeypatch.setattr(ca, 'load_tenants', lambda *a, **k: tenants)
    from stripe_sync import overrides as ovr
    monkeypatch.setattr(ovr, 'load_tenant', lambda *a, **k: {})
    monkeypatch.setattr(saas, '_ch_direct',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))

    conf = saas._campaigns_conf('groom')
    k7 = _k7(conf)
    assert k7['steps'][0]['subject'] == 'Time for your next {{product}}?'
    assert k7['goal']['event_type'] == 'visit_completed'

    # ecom-тенант (нет replenishment-конфига) видит базовый каркас как был
    monkeypatch.setattr(saas.ca, 'load_tenants', lambda *a, **k: {})
    monkeypatch.setattr(ca, 'load_tenants', lambda *a, **k: {})
    k7e = _k7(saas._campaigns_conf('shop'))
    assert k7e['steps'][0]['subject'] == 'Running low on {{product}}?'
    assert k7e['goal']['event_type'] == 'order_confirmed'
