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

import logging
logger = logging.getLogger('api.public')
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

# ── Email: отписка и вебхуки доставки Resend ─────────────────────────────────

def _ch_client():
    import clickhouse_connect
    return clickhouse_connect.get_client(
        host=os.environ.get('CH_HOST', 'clickhouse'),
        port=int(os.environ.get('CH_PORT', '8123')),
        username=os.environ.get('CH_USER', 'default'),
        password=os.environ.get('CH_PASSWORD', ''),
        database=os.environ.get('CH_DB', 'retention'))


def _suppress(tenant: str, address: str, reason: str, detail: str = '') -> None:
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    _ch_client().insert(
        'retention.email_suppressions',
        [[tenant, address.strip().lower(), reason, detail[:300], now]],
        column_names=['tenant_id', 'address', 'reason', 'detail', 'created_at'])


_UNSUB_PAGE = (
    '<!doctype html><html><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<title>Unsubscribed</title></head>'
    '<body style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;'
    'background:#f6f7f9;display:grid;place-items:center;min-height:100vh">'
    '<div style="background:#fff;border-radius:12px;padding:32px 28px;max-width:420px;'
    'text-align:center;color:#101828">'
    '<div style="font-size:17px;font-weight:600;margin-bottom:8px">{title}</div>'
    '<div style="font-size:14px;color:#667085;line-height:1.5">{text}</div>'
    '</div></body></html>')


def _unsub_page(title: str, text: str, code: int = 200):
    from flask import Response
    return Response(_UNSUB_PAGE.format(title=title, text=text), status=code,
                    mimetype='text/html; charset=utf-8')


@bp.route('/unsubscribe', methods=['GET', 'POST'])
def unsubscribe():
    """Отписка по подписанной ссылке из письма. GET - страница подтверждения,
    POST - one-click (List-Unsubscribe-Post, так делают Gmail/Outlook).
    Подпись обязательна: иначе можно было бы отписать любого чужого."""
    from stripe_sync.email_delivery import unsub_token_valid

    tenant = (request.args.get('t') or '').strip()
    address = (request.args.get('a') or '').strip().lower()
    sig = (request.args.get('s') or '').strip()
    if not tenant or not address or not unsub_token_valid(tenant, address, sig):
        return _unsub_page('Link is not valid',
                           'This unsubscribe link is broken or incomplete.', 400)
    try:
        _suppress(tenant, address, 'unsubscribed', 'user request')
    except Exception as exc:  # noqa: BLE001
        logger.error('unsubscribe: не записалось: %s', exc)
        return _unsub_page('Something went wrong',
                           'Please try again in a minute.', 503)
    print(f'[unsubscribe] {tenant}: {address}', flush=True)
    return _unsub_page('You are unsubscribed',
                       'You will not receive marketing emails from this product '
                       'again. Billing and account notices may still arrive.')


@bp.post('/resend/webhook')
def resend_webhook():
    """События доставки от Resend (Svix-подпись). Fail-closed: без секрета
    RESEND_WEBHOOK_SECRET или с плохой подписью - 400, ничего не пишем.
    Баунс и жалоба сразу кладут адрес в список подавления."""
    from stripe_sync.email_delivery import parse_webhook, verify_svix

    secret = os.environ.get('RESEND_WEBHOOK_SECRET', '').strip()
    raw = request.get_data() or b''
    ok = verify_svix(secret,
                     request.headers.get('svix-id', ''),
                     request.headers.get('svix-timestamp', ''),
                     raw,
                     request.headers.get('svix-signature', ''))
    if not ok:
        return api_json(None, 400, 'bad_signature')

    import json as _json
    try:
        doc = _json.loads(raw.decode() or '{}')
    except ValueError:
        return api_json(None, 400, 'invalid_json')

    ev = parse_webhook(doc)
    if not ev:
        return api_json({'status': 'ignored'})

    tenant = str(request.args.get('tenant') or '').strip()
    if not tenant:
        # tenant в query вебхука (у каждого тенанта свой endpoint-URL)
        return api_json(None, 400, 'tenant_required')

    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    client = _ch_client()

    # к какому касанию относится письмо - ищем по id письма провайдера
    camp, step = '', -1
    if ev['provider_id']:
        rows = client.query(
            "SELECT campaign_id, step_idx FROM retention.campaign_send_log "
            "WHERE tenant_id = %(t)s AND provider_id = %(p)s LIMIT 1",
            parameters={'t': tenant, 'p': ev['provider_id']}).result_rows
        if rows:
            camp, step = rows[0][0], int(rows[0][1])

    client.insert(
        'retention.email_events',
        [[tenant, ev['provider_id'], ev['event_type'], ev['address'], camp,
          step, ev['detail'], now]],
        column_names=['tenant_id', 'provider_id', 'event_type', 'address',
                      'campaign_id', 'step_idx', 'detail', 'ts'])

    if ev['suppress_reason'] and ev['address']:
        _suppress(tenant, ev['address'], ev['suppress_reason'], ev['detail'])
        print(f"[resend] {tenant}: {ev['address']} -> {ev['suppress_reason']}", flush=True)

    return api_json({'status': 'ok'})
