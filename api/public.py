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
_tok_cache = {'mtime': 0.0, 'map': {}}


def _token_map() -> dict:
    """{токен: tenant_id} из tokens.json (hot-reload), как у ingest.

    КЛЮЧ ФАЙЛА = ID ТЕНАНТА: токен привязан к своему пространству. Инбокс
    отдаёт тексты баннеров и ссылку подписки на бота - токен ОДНОГО клиента
    не имеет права читать их у другого. Платформенный INGEST_TOKEN из env
    остаётся всетенантным фолбэком ('' = любой тенант).
    """
    env = {t.strip(): '' for t in os.environ.get('INGEST_TOKEN', '').split(',')
           if t.strip()}
    try:
        mt = os.path.getmtime(TOKENS_FILE)
        if mt != _tok_cache['mtime']:
            with open(TOKENS_FILE) as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                _tok_cache['map'] = {str(v): str(k) for k, v in data.items() if v}
            else:                        # старый формат-список: без привязки
                _tok_cache['map'] = {str(v): '' for v in data if v}
            _tok_cache['mtime'] = mt
        return {**env, **_tok_cache['map']} if _tok_cache['map'] else env
    except Exception:
        return {**env, **_tok_cache['map']} if _tok_cache['map'] else env


def _token_ok(tenant: str = '') -> bool:
    """Токен валиден И принадлежит запрошенному тенанту (или всетенантный)."""
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return False
    got = h[7:]
    for tok, own in _token_map().items():
        if hmac.compare_digest(got, tok):
            return not own or not tenant or own == tenant
    return False


def _cors(resp):
    origin = request.headers.get('Origin', '')
    if origin:
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
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
    if len(_rl) > 10000:   # защита памяти: чистим только протухшие вёдра,
        for k in [k for k, v in _rl.items()   # сброс всех разом обнулял лимиты
                  if not v or v[-1] <= now - _RL_WIN]:   # платформы целиком
            _rl.pop(k, None)
    return True


@bp.get('/saas/inbox')
def inbox():
    ip = request.headers.get('X-Real-Client-IP', request.remote_addr or '')
    if not _rate_ok(f"{ip}|{request.args.get('user', '')}"):
        return api_json(None, 429, 'rate_limited')
    tenant = (request.args.get('tenant') or '').strip()
    if not _token_ok(tenant):
        return api_json(None, 401, 'unauthorized')
    user = (request.args.get('user') or '').strip()
    if not tenant or not user:
        return api_json(None, 400, 'tenant_and_user_required')

    rows = q(
        """
        SELECT message_id, title, body, cta_label, cta_url, kind
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

    # Ссылка подписки на бота тенанта - ПОДПИСАННАЯ и собранная здесь: голый
    # id в ссылке позволял бы увести чужие уведомления в свой чат. tg_bot
    # остаётся для старых сниппетов (они строят легаси-ссылку сами).
    tg_bot, tg_link, wa_link = '', '', ''
    try:
        from stripe_sync.channels_admin import load_tenants
        from stripe_sync.telegram_connect import connect_url
        from stripe_sync.wa_templates import connect_url as wa_connect_url
        tc = load_tenants().get(tenant, {}) or {}
        tg_bot = str(tc.get('telegram_bot_username') or '')
        if tg_bot:
            tg_link = connect_url(tg_bot, tenant, user)
        if tc.get('wa_phone_display'):
            wa_link = wa_connect_url(str(tc['wa_phone_display']), tenant, user)
    except Exception:  # noqa: BLE001 - канал не настроен: просто нет кнопки
        tg_bot, tg_link, wa_link = '', '', ''

    return api_json({'tg_bot': tg_bot, 'tg_link': tg_link, 'wa_link': wa_link,
                     'messages': [
        {'message_id': r[0], 'title': r[1], 'body': r[2],
         'cta_label': r[3], 'cta_url': r[4],
         'kind': (r[5] if len(r) > 5 else 'banner') or 'banner'} for r in rows]})

# ── WhatsApp connect-ссылки для бэкенда тенанта (QR-вкладыш в посылку) ───────
# Тенантский WMS минтит подписанные wa.me-ссылки пачкой (упаковочный лист с QR:
# покупатель сканирует - привязка client_user_id + согласие, см. parse_connect_
# text). Auth и класс токена те же, что у inbox: Bearer = ingest-токен тенанта,
# fail-closed 401. Подпись выдаём только владельцу токена - голая генерация
# без auth позволяла бы увести чужие уведомления в свой чат.

_CONNECT_LINKS_MAX = 100


@bp.route('/saas/wa/connect-links', methods=['OPTIONS'])
def wa_connect_links_preflight():
    return '', 204


@bp.post('/saas/wa/connect-links')
def wa_connect_links():
    ip = request.headers.get('X-Real-Client-IP', request.remote_addr or '')
    if not _rate_ok(f'{ip}|wa-connect-links'):
        return api_json(None, 429, 'rate_limited')
    body = request.get_json(silent=True) or {}
    tenant = str(body.get('tenant') or request.args.get('tenant') or '').strip()
    if not _token_ok(tenant):
        return api_json(None, 401, 'unauthorized')
    if not tenant:
        return api_json(None, 400, 'tenant_required')
    ids = body.get('client_user_ids')
    if not isinstance(ids, list) or not ids:
        return api_json(None, 400, 'client_user_ids_required')
    if len(ids) > _CONNECT_LINKS_MAX:
        return api_json(None, 400, 'too_many_ids')

    try:
        from stripe_sync.channels_admin import load_tenants
        from stripe_sync.wa_templates import connect_url as wa_connect_url
        tc = load_tenants().get(tenant, {}) or {}
        # Cloud API номер - основной; личный WhatsApp (WAHA) - фолбэк: оба
        # вебхука парсят один и тот же connect-код.
        phone = str(tc.get('wa_phone_display') or tc.get('wa_personal_number')
                    or '')
    except Exception:  # noqa: BLE001 - конфиг недоступен = канал не настроен
        phone, wa_connect_url = '', None
    if not phone or wa_connect_url is None:
        return api_json({'links': {}, 'reason': 'wa_not_configured'})

    links: dict[str, str] = {}
    for raw in ids:
        uid = str(raw or '').strip()
        if not uid:
            continue
        url = wa_connect_url(phone, tenant, uid)
        if url:
            links[uid] = url
    return api_json({'links': links})


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


def _tenant_webhook_secret(tenant: str) -> str:
    """Секрет подписи вебхука Resend ЭТОГО пространства: при своём аккаунте
    клиент заводит вебхук у себя и получает свой whsec_. env - фолбэк для
    платформенного аккаунта."""
    try:
        from stripe_sync.channels_admin import load_tenants
        own = str((load_tenants().get(tenant, {}) or {}).get('resend_webhook_secret') or '')
    except Exception:  # noqa: BLE001 - файла нет/битый: остаётся платформенный
        own = ''
    return own.strip() or os.environ.get('RESEND_WEBHOOK_SECRET', '').strip()


@bp.post('/resend/webhook')
def resend_webhook():
    """События доставки от Resend (Svix-подпись). Fail-closed: без секрета
    RESEND_WEBHOOK_SECRET или с плохой подписью - 400, ничего не пишем.
    Баунс и жалоба сразу кладут адрес в список подавления."""
    from stripe_sync.email_delivery import parse_webhook, verify_svix

    tenant = str(request.args.get('tenant') or '').strip()
    if not tenant:
        # у каждого пространства свой URL вебхука: без него событие некуда класть
        return api_json(None, 400, 'tenant_required')
    secret = _tenant_webhook_secret(tenant)
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

    # Входящий ОТВЕТ юзера (email.received, Resend inbound). Самый горячий
    # сигнал из всех: пишем в email_replies, находим юзера по адресу и
    # останавливаем ему все живые цепочки - дожимать ответившего роботом
    # нельзя, дальше разговор ведёт человек.
    from stripe_sync.email_delivery import parse_inbound
    inb = parse_inbound(doc)
    if inb:
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        client = _ch_client()
        identity = ''
        if inb['from_email']:
            rows = client.query(
                'SELECT identity_id FROM retention.identities '
                'WHERE tenant_id = %(t)s AND email_norm = %(e)s LIMIT 1',
                parameters={'t': tenant, 'e': inb['from_email']}).result_rows
            identity = str(rows[0][0]) if rows else ''
        client.insert(
            'retention.email_replies',
            [[tenant, inb['from_email'], identity, inb['subject'],
              inb['text'], inb['provider_id'], now]],
            column_names=['tenant_id', 'from_email', 'identity_id', 'subject',
                          'body', 'provider_id', 'ts'])
        stopped = 0
        if identity:
            active = client.query(
                'SELECT campaign_id, control, entry_stage, step_idx, '
                'next_step_at, enrolled_at '
                'FROM retention.campaign_enrollments_current '
                "WHERE tenant_id = %(t)s AND identity_id = %(i)s "
                "AND status = 'active'",
                parameters={'t': tenant, 'i': identity}).result_rows
            if active:
                client.insert(
                    'retention.campaign_enrollments',
                    [[tenant, str(r[0]), identity, int(r[1]), str(r[2]),
                      int(r[3]), r[4], 'exited', r[5], now] for r in active],
                    column_names=['tenant_id', 'campaign_id', 'identity_id',
                                  'control', 'entry_stage', 'step_idx',
                                  'next_step_at', 'status', 'enrolled_at',
                                  'updated_at'])
                stopped = len(active)
        print(f'[resend] {tenant}: reply from {inb["from_email"] or "?"} '
              f'(identity={identity or "-"}, chains stopped={stopped})',
              flush=True)
        return api_json({'status': 'reply'})

    ev = parse_webhook(doc)
    if not ev:
        return api_json({'status': 'ignored'})

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



# ── WhatsApp Cloud API: вебхук per-tenant ────────────────────────────────────
# GET - верификация подписки (hub.challenge) при настройке приложения;
# POST - статусы доставки, входящие сообщения, статусы шаблонов. Подпись
# X-Hub-Signature-256 app secret'ом ЭТОГО тенанта: чужой апдейт не пройдёт.

def _wa_conf(tenant: str) -> dict:
    try:
        from stripe_sync.channels_admin import load_tenants
        return load_tenants().get(str(tenant), {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def _wa_verify_token(tenant: str) -> str:
    from stripe_sync.email_delivery import UNSUB_SECRET
    return hmac.new(UNSUB_SECRET.encode(), f"wawh|{tenant}".encode(),
                    __import__('hashlib').sha256).hexdigest()[:32]


# ── Ответы на реордер-напоминания (Replenishment Autopilot) ──────────────────
# Оба вебхука (Cloud API и личный WAHA) прогоняют входящее через один хелпер:
# валидный RB_-код или точная кнопочная фраза от ПРИВЯЗАННОГО контакта
# становится событием replenishment_* в шине - его потребляет replenishment.py.
# Свободный текст событием не становится никогда: он для оператора в инбоксе.

_REPLY_EVENT = {'confirmed': 'replenishment_confirmed',
                'still_have': 'replenishment_still_have',
                'optout': 'replenishment_optout'}


def _replenishment_reply(ch, tenant: str, text: str, sender: str,
                         msg_id: str, now) -> str:
    """Кнопочный ответ -> событие retention.saas_events. '' - события нет.

    Правила уверенности:
      - confirmed ТОЛЬКО по валидному подписанному RB_-коду (двигает EWMA);
      - still_have/optout по точной фразе - но только когда у identity РОВНО
        ОДИН активный план: при нескольких не гадаем, оставляем оператору;
      - непривязанный отправитель (нет contact с согласием) - ничего.
    Возвращает event_type записанного события (для лога/тестов).
    """
    from stripe_sync.wa_templates import parse_reply_intent
    intent, plan_id = parse_reply_intent(tenant, text)
    if not intent:
        return ''
    rows = ch.query(
        "SELECT client_user_id FROM retention.contacts_current "
        "WHERE tenant_id = %(t)s AND channel = 'whatsapp' "
        "AND address = %(a)s AND consent = 1",
        parameters={'t': tenant, 'a': str(sender or '')}).result_rows
    if not rows or not str(rows[0][0] or ''):
        return ''                    # непривязанный отправитель - не наш ответ
    uid = str(rows[0][0])
    active = ch.query(
        "SELECT plan_id, sku FROM retention.replenishment_plans_current "
        "WHERE tenant_id = %(t)s AND status = 'ACTIVE' AND identity_id IN ("
        "SELECT identity_id FROM retention.identities_current "
        "WHERE tenant_id = %(t)s AND client_user_id = %(u)s)",
        parameters={'t': tenant, 'u': uid}).result_rows
    by_plan = {str(r[0]): str(r[1] or '') for r in active}
    if plan_id:
        if plan_id not in by_plan:
            return ''                # старый/чужой код: цикл уже не активен
    elif len(by_plan) == 1:
        plan_id = next(iter(by_plan))
    else:
        return ''                    # 0 планов - не о чем; >1 - не гадаем
    event_type = _REPLY_EVENT[intent]
    ch.insert(
        'retention.saas_events',
        [[tenant, f'wa-reply-{msg_id}', event_type, now, uid, '', '',
          'wa_reply', '',
          json.dumps({'plan_id': plan_id, 'sku': by_plan.get(plan_id, ''),
                      'from': str(sender or '')})]],
        column_names=['tenant_id', 'event_id', 'event_type', 'ts',
                      'client_user_id', 'email_hash', 'email', 'source',
                      'stripe_customer_id', 'meta'])
    print(f'[wa-reply] {tenant}: {event_type} uid={uid} plan={plan_id}',
          flush=True)
    return event_type


@bp.route('/wa/webhook/<tenant>', methods=['GET'])
def wa_webhook_verify(tenant: str):
    from flask import Response
    if request.args.get('hub.mode') == 'subscribe' and hmac.compare_digest(
            request.args.get('hub.verify_token', ''), _wa_verify_token(tenant)):
        return Response(request.args.get('hub.challenge', ''), mimetype='text/plain')
    return api_json(error='forbidden', code=403)


@bp.post('/wa/webhook/<tenant>')
def wa_webhook(tenant: str):
    from stripe_sync.whatsapp_cloud import (SUPPRESS_ERROR_CODES, parse_webhook,
                                            verify_signature)

    tc = _wa_conf(tenant)
    secret = str(tc.get('wa_app_secret') or '')
    if not secret:
        return api_json(error='not_connected', code=404)
    if not verify_signature(secret, request.get_data(),
                            request.headers.get('X-Hub-Signature-256', '')):
        return api_json(error='forbidden', code=403)

    parsed = parse_webhook(request.get_json(silent=True) or {})
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc)
    ch = None

    def _ch():
        nonlocal ch
        if ch is None:
            ch = _ch_client()
        return ch

    # СТАТУСЫ ДОСТАВКИ - в шину: по wa-id сообщения касание находится в send
    # log (detail успешной отправки). Ошибка 131050 = человек запретил бизнесу
    # писать себе: гасим согласие немедленно, fail-closed.
    rows = []
    for st in parsed['statuses']:
        rows.append([tenant, f"wa-st-{st['wa_msg_id']}-{st['status']}",
                     'wa_status', now, '', '', '', 'whatsapp', '',
                     json.dumps({'wa_msg_id': st['wa_msg_id'],
                                 'status': st['status'],
                                 'error_code': st['error_code']})])
        if st['error_code'] in SUPPRESS_ERROR_CODES and st['recipient']:
            uid_rows = _ch().query(
                'SELECT client_user_id FROM retention.contacts_current '
                'WHERE tenant_id = %(t)s AND channel = %(c)s AND address = %(a)s',
                parameters={'t': tenant, 'c': 'whatsapp',
                            'a': st['recipient']}).result_rows
            if uid_rows:
                _ch().insert('retention.contacts',
                             [[tenant, uid_rows[0][0], 'whatsapp',
                               st['recipient'], 0, now, now]],
                             column_names=['tenant_id', 'client_user_id',
                                           'channel', 'address', 'consent',
                                           'consent_ts', 'updated_at'])
    if rows:
        _ch().insert('retention.saas_events', rows,
                     column_names=['tenant_id', 'event_id', 'event_type', 'ts',
                                   'client_user_id', 'email_hash', 'email',
                                   'source', 'stripe_customer_id', 'meta'])

    # ВХОДЯЩИЕ. Сообщение с нашим кодом привязки = номер + аккаунт + железный
    # opt-in (человек написал первым) одним действием. Без кода - фиксируем
    # событие (окно 24ч открыто), но контакт не создаём: привязывать не к кому.
    from stripe_sync.wa_templates import parse_connect_text
    for msg in parsed['inbound']:
        uid = parse_connect_text(tenant, msg['text'])
        _ch().insert('retention.saas_events',
                     [[tenant, f"wa-in-{msg['wa_msg_id']}", 'wa_inbound', now,
                       uid, '', '', 'whatsapp', '',
                       json.dumps({'from': msg['from'], 'type': msg['type']})]],
                     column_names=['tenant_id', 'event_id', 'event_type', 'ts',
                                   'client_user_id', 'email_hash', 'email',
                                   'source', 'stripe_customer_id', 'meta'])
        if uid:
            _ch().insert('retention.contacts',
                         [[tenant, uid, 'whatsapp', msg['from'], 1, now, now]],
                         column_names=['tenant_id', 'client_user_id', 'channel',
                                       'address', 'consent', 'consent_ts',
                                       'updated_at'])
            print(f"[wa] {tenant}: connect uid={uid} from={msg['from']}", flush=True)
        else:
            # ответ на реордер-напоминание (RB_-код в payload кнопки или
            # точная кнопочная фраза) -> событие replenishment_*
            _replenishment_reply(_ch(), tenant, msg['text'], msg['from'],
                                 msg['wa_msg_id'], now)

    # СТАТУСЫ ШАБЛОНОВ - в реестр tenants.json: слать можно только APPROVED,
    # и отправка узнаёт об одобрении отсюда, а не по таймеру.
    if parsed['templates']:
        from stripe_sync.channels_admin import update_tenant
        registry = dict(tc.get('wa_templates') or {})
        for tpl in parsed['templates']:
            if tpl['name'] in registry:
                registry[tpl['name']] = {**registry[tpl['name']],
                                         'status': tpl['event'],
                                         'reason': tpl['reason']}
        update_tenant(tenant, {'wa_templates': registry})
        print(f"[wa] {tenant}: шаблоны {[(t['name'], t['event']) for t in parsed['templates']]}",
              flush=True)

    # Meta ретраит не-2xx: наш ответ всегда ok
    return api_json({'ok': True})


# ── Личный WhatsApp (WAHA, трек C): вебхук по ВНУТРЕННЕЙ сети ────────────────
# WAHA шлёт сюда статусы сессии и сообщения. Подпись X-Webhook-Hmac (sha512
# от сырого тела) ключом, который мы сами задали при создании сессии.
# Только приём: статус - в tenants.json, входящее с нашим подписанным кодом -
# контакт с согласием, голое входящее - событие в шину (для инбокса потом).

@bp.post('/wa/personal/<tenant>')
def wa_personal_webhook(tenant: str):
    from stripe_sync import wa_personal as wap

    if not wap.verify_webhook(tenant, request.get_data(),
                              request.headers.get('X-Webhook-Hmac', '')):
        return api_json(error='forbidden', code=403)

    ev = wap.parse_event(request.get_json(silent=True) or {})
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc)

    def msg_ts():
        unix = int(ev.get('ts_unix') or 0)
        return datetime.fromtimestamp(unix, tz=timezone.utc) if unix else now

    if ev['kind'] == 'status':
        from stripe_sync.channels_admin import update_tenant
        update_tenant(tenant, {'wa_personal_status': ev['status'],
                               'wa_personal_number': ev['number'] or None})
        print(f"[wa-personal] {tenant}: {ev['status']} {ev['number']}", flush=True)

    elif ev['kind'] == 'outbound':
        # свой ответ (из инбокса или с телефона) - в тред, без событий подписки
        _ch_client().insert(
            'retention.wa_messages',
            [[tenant, ev['chat_id'], ev['wa_msg_id'] or f'out-{now.timestamp()}',
              'out', ev['text'], '', msg_ts()]],
            column_names=['tenant_id', 'chat_id', 'wa_msg_id', 'direction',
                          'text', 'sender_name', 'ts'])

    elif ev['kind'] == 'inbound':
        from stripe_sync.wa_templates import parse_connect_text
        uid = parse_connect_text(tenant, ev['text'])
        ch = _ch_client()
        ch.insert('retention.wa_messages',
                  [[tenant, ev['chat_id'],
                    ev['wa_msg_id'] or f'in-{now.timestamp()}',
                    'in', ev['text'], ev.get('name', ''), msg_ts()]],
                  column_names=['tenant_id', 'chat_id', 'wa_msg_id', 'direction',
                                'text', 'sender_name', 'ts'])
        ch.insert('retention.saas_events',
                  [[tenant, f"wap-in-{ev['wa_msg_id'] or now.timestamp()}",
                    'wa_personal_inbound', now, uid, '', '', 'whatsapp_personal',
                    '', json.dumps({'from': ev['from']})]],
                  column_names=['tenant_id', 'event_id', 'event_type', 'ts',
                                'client_user_id', 'email_hash', 'email',
                                'source', 'stripe_customer_id', 'meta'])
        if uid:
            # человек пришёл по НАШЕЙ подписанной ссылке - это явное согласие
            # и привязка аккаунта; тот же контракт, что у Cloud API
            ch.insert('retention.contacts',
                      [[tenant, uid, 'whatsapp', ev['from'], 1, now, now]],
                      column_names=['tenant_id', 'client_user_id', 'channel',
                                    'address', 'consent', 'consent_ts',
                                    'updated_at'])
            print(f"[wa-personal] {tenant}: connect uid={uid}", flush=True)
        else:
            # ответ на реордер-напоминание текстом (личный канал шлёт код в
            # тексте ссылки, кнопок нет) -> событие replenishment_*
            _replenishment_reply(
                ch, tenant, ev['text'], ev['from'],
                ev['wa_msg_id'] or f"wap-{now.timestamp()}", now)

    return api_json({'ok': True})
