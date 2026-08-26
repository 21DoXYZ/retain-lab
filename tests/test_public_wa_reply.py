"""Ответы клиента на реордер-напоминание в WhatsApp -> события replenishment_*.

Проверяем контракт _replenishment_reply (общий хелпер обоих вебхуков) и
проводку через личный вебхук WAHA: валидный RB_-код пишет confirmed с plan_id
из кода, точная кнопочная фраза при одном активном плане пишет событие с его
plan_id, неоднозначность (два плана) и непривязанный отправитель не пишут
НИЧЕГО - свободная классификация запрещена, текст уходит оператору.
"""

import json
import sys
import types
from datetime import datetime

from flask import Flask

if 'player_board' not in sys.modules:
    _pb = types.ModuleType('player_board')
    _pb.q = lambda *a, **k: ([], [])
    sys.modules['player_board'] = _pb

import api.public as pub  # noqa: E402
from stripe_sync.wa_templates import reorder_code  # noqa: E402

TENANT = 'simbago'
NOW = datetime(2026, 8, 26, 10, 0, 0)


class FakeCH:
    """Мини-двойник clickhouse_connect: contacts_current и планы задаются
    тестом, все insert копятся для ассертов."""

    def __init__(self, contacts=None, plans=None):
        self.contacts = contacts or {}      # {address: client_user_id}
        self.plans = plans or []            # [(plan_id, sku)]
        self.inserted = []                  # (table, rows, columns)

    def query(self, sql, parameters=None):
        p = parameters or {}
        if 'contacts_current' in sql:
            uid = self.contacts.get(p.get('a'))
            rows = [(uid,)] if uid else []
        elif 'replenishment_plans_current' in sql:
            rows = list(self.plans)
        else:
            rows = []
        return types.SimpleNamespace(result_rows=rows)

    def insert(self, table, rows, column_names=None):
        self.inserted.append((table, rows, column_names))

    def events(self, event_type):
        return [r for t, rows, _ in self.inserted for r in rows
                if t == 'retention.saas_events' and r[2] == event_type]


def _reply(ch, text, sender='6281234', msg_id='m1'):
    return pub._replenishment_reply(ch, TENANT, text, sender, msg_id, NOW)


def test_valid_code_writes_confirmed_with_plan_id(monkeypatch):
    code = reorder_code(TENANT, 'plan1')
    ch = FakeCH(contacts={'6281234': 'u42'}, plans=[('plan1', 'food-2kg')])
    assert _reply(ch, f'yes {code}') == 'replenishment_confirmed'
    (row,) = ch.events('replenishment_confirmed')
    assert row[0] == TENANT and row[1] == 'wa-reply-m1'
    assert row[4] == 'u42' and row[7] == 'wa_reply'
    meta = json.loads(row[9])
    assert meta['plan_id'] == 'plan1' and meta['sku'] == 'food-2kg'


def test_stale_or_foreign_code_writes_nothing():
    """Код валиден, но цикл уже не активен у этого identity - не пишем."""
    code = reorder_code(TENANT, 'plan_closed')
    ch = FakeCH(contacts={'6281234': 'u42'}, plans=[('plan1', 'food-2kg')])
    assert _reply(ch, code) == ''
    assert ch.inserted == []


def test_button_phrase_with_single_active_plan(monkeypatch):
    ch = FakeCH(contacts={'6281234': 'u42'}, plans=[('plan1', 'food-2kg')])
    assert _reply(ch, 'Masih ada') == 'replenishment_still_have'
    meta = json.loads(ch.events('replenishment_still_have')[0][9])
    assert meta['plan_id'] == 'plan1'

    ch2 = FakeCH(contacts={'6281234': 'u42'}, plans=[('plan1', 'food-2kg')])
    assert _reply(ch2, 'STOP') == 'replenishment_optout'
    assert json.loads(ch2.events('replenishment_optout')[0][9])['plan_id'] == 'plan1'


def test_ambiguous_plans_without_code_write_nothing():
    """Два активных плана и фраза без кода - не гадаем, оставляем оператору."""
    ch = FakeCH(contacts={'6281234': 'u42'},
                plans=[('plan1', 'food-2kg'), ('plan2', 'litter-5l')])
    assert _reply(ch, 'still have') == ''
    assert _reply(ch, 'stop') == ''
    assert ch.inserted == []


def test_unbound_sender_writes_nothing():
    ch = FakeCH(contacts={}, plans=[('plan1', 'food-2kg')])
    assert _reply(ch, 'still have') == ''
    assert ch.inserted == []


def test_free_text_writes_nothing():
    ch = FakeCH(contacts={'6281234': 'u42'}, plans=[('plan1', 'food-2kg')])
    assert _reply(ch, 'корм ещё остался, напишите позже') == ''
    assert ch.inserted == []


def test_personal_webhook_wires_reply_into_events(monkeypatch):
    """Проводка: входящее WAHA с кнопочной фразой от привязанного контакта
    доходит до saas_events как replenishment_still_have."""
    from stripe_sync import wa_personal as wap

    ch = FakeCH(contacts={'6281234': 'u42'}, plans=[('plan1', 'food-2kg')])
    monkeypatch.setattr(pub, '_ch_client', lambda: ch)
    monkeypatch.setattr(wap, 'verify_webhook', lambda *a, **k: True)

    app = Flask(__name__)
    app.register_blueprint(pub.bp)
    payload = {'event': 'message',
               'payload': {'id': 'wamid-9', 'from': '6281234@c.us',
                           'body': 'still have', 'timestamp': 1756202000}}
    r = app.test_client().post(f'/public/wa/personal/{TENANT}', json=payload)
    assert r.status_code == 200
    (row,) = ch.events('replenishment_still_have')
    assert row[1] == 'wa-reply-wamid-9' and row[4] == 'u42'
    assert json.loads(row[9])['plan_id'] == 'plan1'
    # штатное событие входящего тоже записано (инбокс живёт как раньше)
    assert ch.events('wa_personal_inbound')
