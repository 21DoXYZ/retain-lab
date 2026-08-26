"""POST /public/saas/wa/connect-links — минтинг подписанных wa.me-ссылок.

Контракт для тенантского WMS (QR-вкладыш в посылку): Bearer = ingest-токен
тенанта, тело {"client_user_ids": [...]}. Проверяем то, что дорого ломается
молча: подпись кода реально парсится parse_connect_text (иначе скан QR ничего
не привяжет), чужой токен не минтит ссылки чужого пространства (увод
уведомлений), а ненастроенный канал отвечает явной причиной, не 500.
"""

import json
import sys
import types
import urllib.parse
from pathlib import Path

from flask import Flask

# api.public тянет player_board (весь борд + clickhouse) только ради q().
# Ручке connect-links q не нужен — подменяем модуль лёгкой заглушкой.
if 'player_board' not in sys.modules:
    _pb = types.ModuleType('player_board')
    _pb.q = lambda *a, **k: ([], [])
    sys.modules['player_board'] = _pb

import api.public as pub  # noqa: E402
from stripe_sync.wa_templates import parse_connect_text  # noqa: E402

TENANT = 'simbago'
TOKEN = 'tok-simbago-1'


def make_client(tmp_path, monkeypatch, tenants=None, tokens=None):
    tokens_file = tmp_path / 'tokens.json'
    tokens_file.write_text(json.dumps(tokens or {TENANT: TOKEN}))
    monkeypatch.setattr(pub, 'TOKENS_FILE', str(tokens_file))
    pub._tok_cache.update({'mtime': 0.0, 'map': {}})
    pub._rl.clear()
    monkeypatch.delenv('INGEST_TOKEN', raising=False)

    import stripe_sync.channels_admin as ca
    conf = tenants if tenants is not None else {
        TENANT: {'wa_phone_display': '+62 812-3456-789'}}
    monkeypatch.setattr(ca, 'load_tenants', lambda path='': conf)

    app = Flask(__name__)
    app.register_blueprint(pub.bp)
    return app.test_client()


def post(client, body, token=TOKEN):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    return client.post('/public/saas/wa/connect-links', json=body,
                       headers=headers)


def test_minted_link_carries_a_code_that_parses_back(tmp_path, monkeypatch):
    """Скан QR шлёт text из ссылки во входящие — parse_connect_text обязан
    вернуть ровно тот client_user_id, который мы заминтили."""
    client = make_client(tmp_path, monkeypatch)
    r = post(client, {'tenant': TENANT, 'client_user_ids': ['42']})
    assert r.status_code == 200
    links = r.get_json()['data']['links']
    url = links['42']
    assert url.startswith('https://wa.me/628123456789?text=')
    text = urllib.parse.unquote(url.split('text=', 1)[1])
    assert parse_connect_text(TENANT, text) == '42'
    # чужой tenant ту же подпись не примет
    assert parse_connect_text('other', text) == ''


def test_guest_id_format_survives_roundtrip(tmp_path, monkeypatch):
    """Формат гостя из simbago (guest:+E.164) — не [a-z0-9], но код base64url."""
    client = make_client(tmp_path, monkeypatch)
    uid = 'guest:+6281234567890'
    r = post(client, {'tenant': TENANT, 'client_user_ids': [uid]})
    url = r.get_json()['data']['links'][uid]
    text = urllib.parse.unquote(url.split('text=', 1)[1])
    assert parse_connect_text(TENANT, text) == uid


def test_foreign_or_missing_token_is_401(tmp_path, monkeypatch):
    client = make_client(
        tmp_path, monkeypatch,
        tokens={TENANT: TOKEN, 'other': 'tok-other'})
    body = {'tenant': TENANT, 'client_user_ids': ['1']}
    assert post(client, body, token='tok-other').status_code == 401
    assert post(client, body, token='wrong').status_code == 401
    assert post(client, body, token=None).status_code == 401


def test_unconfigured_channel_answers_with_reason_not_500(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, tenants={TENANT: {}})
    r = post(client, {'tenant': TENANT, 'client_user_ids': ['1']})
    assert r.status_code == 200
    assert r.get_json()['data'] == {'links': {}, 'reason': 'wa_not_configured'}


def test_input_limits(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert post(client, {'tenant': TENANT}).status_code == 400
    assert post(client, {'tenant': TENANT,
                         'client_user_ids': []}).status_code == 400
    too_many = {'tenant': TENANT,
                'client_user_ids': [str(i) for i in range(101)]}
    assert post(client, too_many).status_code == 400
    assert post(client, {'client_user_ids': ['1']}).status_code == 400  # без tenant

    # пустые id молча пропускаются, валидные минтятся
    r = post(client, {'tenant': TENANT, 'client_user_ids': ['', '7']})
    assert list(r.get_json()['data']['links']) == ['7']
