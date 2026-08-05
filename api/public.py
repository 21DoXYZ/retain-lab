"""api/public.py — публичные ручки для СНИППЕТА на сайтах тенантов.

Отдельный префикс /public/* (не /api/*): flask-cors на /api/* пускает только
origin нашего SPA, а виджет зовёт нас с ЛЮБОГО домена тенанта — здесь свой
echo-origin CORS (класс токена тот же «публичный», что у /ingest/saas/events).

Auth: Bearer = ingest-токен тенанта (secrets/tokens.json, hot-reload; фолбэк
INGEST_TOKEN). Токен один класс на тенанта v1 — изоляция по-тенантно появится
вместе со вторым тенантом (перевод tokens.json в {tenant: token}).

GET /public/saas/inbox?tenant=&user= — активные in-app баннеры юзера:
живы (expires_at), юзер всё ещё в стадии кампании (оплатил — баннер гаснет),
не закрыты/не кликнуты (события inapp_dismissed/inapp_clicked).
"""
from __future__ import annotations

import hmac
import json
import os

from flask import Blueprint, request

from .core import api_json
from player_board import q

bp = Blueprint('api_public', __name__, url_prefix='/public')

TOKENS_FILE = os.environ.get('TOKENS_FILE', '/secrets/tokens.json')
_tok_cache = {'mtime': 0.0, 'tokens': set()}


def _valid_tokens() -> set[str]:
    """Как у ingest: tokens.json (dict или list) с hot-reload, фолбэк env."""
    env = {t.strip() for t in os.environ.get('INGEST_TOKEN', '').split(',') if t.strip()}
    try:
        mt = os.path.getmtime(TOKENS_FILE)
        if mt != _tok_cache['mtime']:
            with open(TOKENS_FILE) as fh:
                data = json.load(fh)
            vals = data.values() if isinstance(data, dict) else data
            _tok_cache['tokens'] = {str(v) for v in vals if v}
            _tok_cache['mtime'] = mt
        return _tok_cache['tokens'] or env
    except Exception:
        return _tok_cache['tokens'] or env


def _token_ok() -> bool:
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return False
    got = h[7:]
    return any(hmac.compare_digest(got, t) for t in _valid_tokens())


def _cors(resp):
    origin = request.headers.get('Origin', '')
    if origin:
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        resp.headers['Vary'] = 'Origin'
    return resp


@bp.after_request
def _public_cors(resp):
    return _cors(resp)


@bp.route('/saas/inbox', methods=['OPTIONS'])
def inbox_preflight():
    return '', 204


# Простой токен-бакет в процессе: 60 запросов / 5 минут на (ip, user).
# Борд - один процесс, этого достаточно; при масштабировании - Redis.
_rl: dict = {}
_RL_MAX, _RL_WIN = 60, 300


def _rate_ok(key: str) -> bool:
    import time as _t
    now = _t.time()
    bucket = [t for t in _rl.get(key, []) if t > now - _RL_WIN]
    if len(bucket) >= _RL_MAX:
        _rl[key] = bucket
        return False
    bucket.append(now)
    _rl[key] = bucket
    if len(_rl) > 10000:   # защита памяти от мусорных ключей
        _rl.clear()
    return True


@bp.get('/saas/inbox')
def inbox():
    ip = request.headers.get('X-Real-Client-IP', request.remote_addr or '')
    if not _rate_ok(f"{ip}|{request.args.get('user', '')}"):
        return api_json(None, 429, 'rate_limited')
    if not _token_ok():
        return api_json(None, 401, 'unauthorized')
    tenant = (request.args.get('tenant') or '').strip()
    user = (request.args.get('user') or '').strip()
    if not tenant or not user:
        return api_json(None, 400, 'tenant_and_user_required')

    rows = q(
        """
        SELECT message_id, title, body, cta_label, cta_url
        FROM retention.inapp_inbox
        WHERE tenant_id = {t:String} AND client_user_id = {u:String}
          AND expires_at > now()
          AND entry_stage IN (
              SELECT stage FROM user_actions
              WHERE tenant_id = {t:String} AND client_user_id = {u:String})
          AND message_id NOT IN (
              SELECT JSONExtractString(meta, 'message_id')
              FROM retention.saas_events
              WHERE tenant_id = {t:String}
                AND event_type IN ('inapp_dismissed', 'inapp_clicked')
                AND meta != '')
        ORDER BY created_at DESC
        LIMIT 3
        """,
        {'t': tenant, 'u': user})[1]

    return api_json({'messages': [
        {'message_id': r[0], 'title': r[1], 'body': r[2],
         'cta_label': r[3], 'cta_url': r[4]} for r in rows]})
