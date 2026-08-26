"""api/tenants.py — создание рабочего пространства клиента (последний ручной шов).

БЫЛО: новый клиент = я руками правлю tokens.json, tenants.json, завожу логин в
Supabase и вписываю id в код. СТАЛО: одна форма - платформа вводит название
продукта и почту владельца, система сама делает всё:

  1. id пространства из названия продукта (slugify, уникальность проверяется);
  2. ingest-токен (ключ tokens.json = id пространства - привязка к тенанту);
  3. запись в tenants.json (product_name - подставляется в тексты кампаний);
  4. логин владельца в Supabase (роль director) + строка crm_users с
     tenant_id = новое пространство -> он видит ТОЛЬКО свои данные;
  5. кампании берутся из общего каркаса _default, офферы пусты до опросника.

Пароль владельца показывается ОДИН раз в ответе (как токен при регенерации).
Доступ к ручкам - только super_admin (платформа), клиентские роли не видят.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from flask import Blueprint, request

from .core import require_auth, api_json
from stripe_sync import channels_admin as ca
from stripe_sync.provision_util import (new_password, new_token, slugify_tenant,
                                        validate_signup)

bp = Blueprint('api_tenants', __name__, url_prefix='/api/v1')

PLATFORM_ROLES = ('super_admin',)
TOKENS_FILE = os.environ.get('TOKENS_FILE', '/secrets/tokens.json')
# Серверный токен (Server Events API, §3/§4a): секрет бэкенда клиента,
# в HTML не попадает - только ему ingest разрешает открытый email.
SERVER_TOKENS_FILE = os.environ.get('SERVER_TOKENS_FILE', '/secrets/server_tokens.json')


def _bad(reason: str, code: int = 400):
    return api_json(None, code, reason)


def _tokens() -> dict:
    try:
        with open(TOKENS_FILE) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_token(tenant: str, token: str) -> None:
    """Атомарная запись (как в channels_admin): сендеры/ingest читают файл на лету."""
    import tempfile
    data = _tokens()
    data[tenant] = token
    d = os.path.dirname(TOKENS_FILE) or '.'
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.tokens-', suffix='.json')
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, TOKENS_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _save_server_token(tenant: str, token: str) -> None:
    """Атомарная запись серверного токена (файл той же формы, что tokens.json)."""
    import tempfile
    try:
        with open(SERVER_TOKENS_FILE) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data[tenant] = token
    d = os.path.dirname(SERVER_TOKENS_FILE) or '.'
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.srvtokens-', suffix='.json')
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, SERVER_TOKENS_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _known_tenants() -> set:
    import json as _json
    from pathlib import Path
    out = set(ca.load_tenants().keys()) | set(_tokens().keys())
    p = Path(__file__).resolve().parent.parent / 'stripe_sync' / 'saas_campaigns.json'
    try:
        out |= set(_json.loads(p.read_text()).keys())
    except Exception:
        pass
    return out


def _supabase_create_user(email: str, password: str) -> tuple[str, str]:
    """(user_id, '') либо ('', reason). Служебный ключ - только на сервере."""
    url = os.environ.get('SUPABASE_URL', '').strip().rstrip('/')
    key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not url or not key:
        return '', 'supabase_not_configured'
    payload = json.dumps({'email': email, 'password': password,
                          'email_confirm': True,
                          'app_metadata': {'role': 'director'}}).encode()
    req = urllib.request.Request(
        f'{url}/auth/v1/admin/users', data=payload, method='POST',
        headers={'Content-Type': 'application/json', 'apikey': key,
                 'Authorization': f'Bearer {key}'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode() or '{}')
        uid = str(data.get('id') or '')
        return (uid, '') if uid else ('', 'supabase_no_id')
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()[:200]
        if 'already been registered' in body or exc.code == 422:
            return '', 'email_already_used'
        return '', f'supabase_http_{exc.code}'
    except Exception as exc:  # noqa: BLE001
        return '', f'supabase_{type(exc).__name__}'


def _crm_user_row(user_id: str, full_name: str, tenant: str) -> str:
    """Строка crm_users: роль director + скоуп тенанта. '' - ок, иначе причина."""
    dsn = os.environ.get('SUPABASE_DB_URL', '').strip()
    if not dsn:
        return 'db_not_configured'
    try:
        import psycopg  # noqa: PLC0415
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crm.crm_users (id, full_name, role, tenant_id)
                VALUES (%(id)s, %(name)s, 'director', %(t)s)
                ON CONFLICT (id) DO UPDATE
                   SET full_name = EXCLUDED.full_name, tenant_id = EXCLUDED.tenant_id
                """,
                {'id': user_id, 'name': full_name[:120], 't': tenant})
            conn.commit()
        return ''
    except Exception as exc:  # noqa: BLE001
        return f'db_{type(exc).__name__}'


@bp.get('/saas/tenants')
@require_auth(roles=PLATFORM_ROLES)
def list_tenants():
    """Список пространств: id, название продукта, есть ли токен."""
    confs = ca.load_tenants()
    tokens = _tokens()
    out = []
    for tid in sorted(set(confs) | set(tokens)):
        conf = confs.get(tid) or {}
        out.append({
            'tenant_id': tid,
            'product_name': conf.get('product_name')
                            or (conf.get('onboarding_answers') or {}).get('product_name', ''),
            'has_token': bool(tokens.get(tid)),
            'onboarded': bool(conf.get('onboarding_answers')),
        })
    return api_json({'tenants': out})


@bp.post('/saas/tenants')
@require_auth(roles=PLATFORM_ROLES)
def create_tenant():
    """Создать пространство клиента целиком: id + токен + логин владельца."""
    body = request.get_json(silent=True) or {}
    product_name = str(body.get('product_name', '')).strip()
    owner_email = str(body.get('owner_email', '')).strip().lower()

    reason = validate_signup(product_name, owner_email)
    if reason:
        return _bad(reason)

    tenant = slugify_tenant(product_name, _known_tenants())
    password = new_password()

    user_id, reason = _supabase_create_user(owner_email, password)
    if reason:
        return _bad(reason, 409 if reason == 'email_already_used' else 502)

    reason = _crm_user_row(user_id, product_name, tenant)
    if reason:
        return _bad(reason, 502)

    token = new_token()
    _save_token(tenant, token)
    server_token = new_token()
    _save_server_token(tenant, server_token)
    ca.update_tenant(tenant, {
        'product_name': product_name,
        'created_at': datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
    })

    host = os.environ.get('SAAS_HOST', '').strip()
    snippet = (
        f'<script src="https://{host}/snippet/ra.js"\n'
        f'        data-endpoint="https://{host}/ingest/saas/events"\n'
        f'        data-token="{token}" data-tenant="{tenant}"></script>'
    ) if host else ''

    print(f'[provision] создано пространство {tenant} для «{product_name}», '
          f'владелец {owner_email}', flush=True)
    return api_json({
        'tenant_id': tenant,
        'product_name': product_name,
        'owner_email': owner_email,
        'owner_password': password,   # показывается ОДИН раз
        'ingest_token': token,
        # Секрет для Server Events API (бэкенд клиента; в HTML не вставлять):
        'server_events_token': server_token,
        'snippet': snippet,
        'login_url': f'https://{host}/login' if host else '',
    })
