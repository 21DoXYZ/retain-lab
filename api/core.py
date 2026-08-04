"""api/core.py — ядро JSON-API: JWT-middleware, PII-маскирование, базовые эндпоинты.

Все финансовые расчёты и SQL берутся из player_board (headless-бэкенд) —
здесь НЕТ переписанных формул, только выборка полей и их упаковка в JSON.

Эндпоинты (все под /api/v1, все закрыты require_auth):
  GET /api/v1/players/<pid>/summary   — карточка 360 (профиль/деньги/игра/скоры/оффер)
  GET /api/v1/players/<pid>/heatmap   — тепловая карта час×день (для автоподсказки звонка)
  GET /api/v1/queue/priorities?ids=.. — приоритет/действие/бонус/когда по списку id
  POST /api/v1/players/<pid>/offer     — решение отдела по офферу (player_offers)

Аутентификация:
  • Supabase JWT. Свежий Supabase подписывает access-token асимметрично (ES256/RS256)
    и публикует ключи в JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) — ключ
    берётся по `kid` из заголовка. HS256+SUPABASE_JWT_SECRET оставлен ЯВНЫМ legacy-
    фолбэком (старые проекты с общим секретом). Проверяем подпись, срок, aud и iss.
  • Роль приложения берётся из клейма app_metadata.role (кладёт auth-хук
    custom_access_token_hook, миграция 0004; юзер не может его подменить) либо
    user_metadata.role. Верхнеуровневый claim `role` — это Postgres-роль
    ('authenticated'), НЕ роль приложения, поэтому не используется.
  • Владение игроком (anti-IDOR): can_access_player() режет доступ operator/affiliate/
    vip_manager к чужим игрокам поверх ролевого гейта require_auth.
  • Dev-обход: API_AUTH_OFF=1 работает ТОЛЬКО в dev (FLASK_ENV=development или
    ALLOW_AUTH_OFF=1); в проде флаг игнорируется (fail-closed).
"""
from __future__ import annotations

import os
import math
import json
import logging
import datetime
import decimal
import threading
from functools import wraps

import jwt
from jwt import PyJWKClient
from flask import Blueprint, request, g, Response

logger = logging.getLogger('api.core')


# ── ленивый доступ к player_board (разрывает циркулярный импорт) ─────────────────
# player_board.py при импорте вызывает register_api(app), который импортирует пакет
# api/* → api.core. Если core делает `import player_board` НА ВЕРХНЕМ уровне, а core
# импортируется раньше player_board, возникает цикл (core недоинициализирован, когда
# доменные модули берут из него require_auth/api_json). Ленивый прокси импортирует
# player_board только при ПЕРВОМ обращении (во время запроса) — к этому моменту борд
# полностью загружен. Так core импортируется без побочного импорта борда.
class _LazyBoard:
    _mod = None

    def __getattr__(self, name):
        if _LazyBoard._mod is None:
            import player_board as _m   # noqa: PLC0415
            _LazyBoard._mod = _m
        return getattr(_LazyBoard._mod, name)


pb = _LazyBoard()   # готовые helper-функции борда (q, offer_for, _rhythm, ...)

bp = Blueprint('api_core', __name__, url_prefix='/api/v1')

# ── роль → VIP-подпись (только отображение, не формула) ──
VIP_LABELS = {0: '⚪ Regular', 1: '🥈 Silver', 2: '🥇 Gold',
              3: '💠 Platinum', 4: '💎 Diamond', 5: '👑 Royal'}

# ════════════════════════════════════════════════════════════════════════════
# JSON-ответ: единый конверт + корректная сериализация Decimal/date/NaN/кириллицы
# ════════════════════════════════════════════════════════════════════════════
def _clean(o):
    """Рекурсивно приводит значения ClickHouse к JSON-safe: Decimal→float,
    date/datetime→ISO, NaN/Inf→None, bytes→str."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, bool):
        return o
    if isinstance(o, decimal.Decimal):
        fv = float(o)
        return None if (math.isnan(fv) or math.isinf(fv)) else fv
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if isinstance(o, (bytes, bytearray)):
        return o.decode('utf-8', 'replace')
    return o


def api_json(data=None, code: int = 200, error: str | None = None,
             extra: dict | None = None) -> Response:
    """Единый конверт ответа: {ok, data} | {ok, error}. Кириллица без \\uXXXX.
    `extra` — доп-поля верхнего уровня (напр. error_code/error_params для i18n
    ошибок на фронте); мержатся в payload, не перетирая ok/data/error."""
    payload = {'ok': error is None}
    if error is None:
        payload['data'] = _clean(data)
    else:
        payload['error'] = error
    if extra:
        for k, v in extra.items():
            if k not in ('ok', 'data', 'error'):
                payload[k] = _clean(v)
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return Response(body, status=code, mimetype='application/json; charset=utf-8')


# ════════════════════════════════════════════════════════════════════════════
# JWT-middleware
# ════════════════════════════════════════════════════════════════════════════
def _truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _dev_mode() -> bool:
    """Явный dev-режим: FLASK_ENV=development или ALLOW_AUTH_OFF=1.
    Только в нём разрешён обход авторизации API_AUTH_OFF."""
    return (os.environ.get('FLASK_ENV', '').strip().lower() == 'development'
            or _truthy('ALLOW_AUTH_OFF'))


def _auth_off() -> bool:
    """Обход авторизации разрешён ТОЛЬКО в явном dev-режиме. В проде API_AUTH_OFF
    игнорируется (fail-closed): случайно выставленный флаг не должен снимать защиту."""
    if not _truthy('API_AUTH_OFF'):
        return False
    if _dev_mode():
        return True
    logger.error('API_AUTH_OFF задан, но НЕ dev-режим (нет FLASK_ENV=development / '
                 'ALLOW_AUTH_OFF=1) — флаг ИГНОРИРУЕТСЯ, авторизация остаётся включённой.')
    return False


def _jwt_secret() -> str:
    return os.environ.get('SUPABASE_JWT_SECRET', '')


def _supabase_url() -> str:
    return os.environ.get('SUPABASE_URL', '').strip().rstrip('/')


def _jwt_aud() -> str:
    # self-hosted Supabase по умолчанию 'authenticated'; пусто → проверку aud выключаем
    return os.environ.get('SUPABASE_JWT_AUD', 'authenticated')


def _jwt_issuer() -> str:
    """Ожидаемый iss токена. Supabase кладёт `{SUPABASE_URL}/auth/v1`.
    Переопределяется env SUPABASE_JWT_ISS; пусто → проверку iss не делаем."""
    override = os.environ.get('SUPABASE_JWT_ISS', '').strip()
    if override:
        return override
    url = _supabase_url()
    return f'{url}/auth/v1' if url else ''


# ── JWKS-клиент (кэшируется на процесс; не создаём на каждый запрос) ──────────────
_jwks_lock = threading.Lock()
_jwks_client: PyJWKClient | None = None
_ASYMMETRIC_ALGS = ('ES256', 'RS256', 'ES384', 'RS384', 'ES512', 'RS512')


def _get_jwks_client() -> PyJWKClient:
    """Ленивый синглтон PyJWKClient на JWKS-эндпоинт Supabase. JWKS кэшируется
    внутри клиента (lifespan), поэтому сеть дёргается редко, а не на каждый запрос."""
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                url = _supabase_url()
                if not url:
                    raise jwt.InvalidTokenError('SUPABASE_URL не задан — JWKS недоступен')
                _jwks_client = PyJWKClient(
                    f'{url}/auth/v1/.well-known/jwks.json',
                    cache_keys=True, lifespan=300)
    return _jwks_client


def _extract_role(claims: dict) -> str | None:
    """Роль приложения: app_metadata.role (авторитетно, кладёт auth-хук 0004) →
    user_metadata.role. Верхнеуровневый `role` (Postgres-роль 'authenticated')
    намеренно игнорируется."""
    for src in ('app_metadata', 'user_metadata'):
        meta = claims.get(src)
        if isinstance(meta, dict):
            role = meta.get('role')
            if role:
                return str(role)
    return None


def _decode(token: str) -> dict:
    """Верифицировать Supabase-JWT. Алгоритм — по заголовку токена:
      • ES256/RS256 (свежий Supabase) → ключ из JWKS по `kid`, проверка подписи;
      • HS256 (legacy) → общий секрет SUPABASE_JWT_SECRET (ЯВНЫЙ фолбэк).
    Всегда проверяем срок, audience и (если известен) issuer."""
    aud = _jwt_aud()
    iss = _jwt_issuer()
    kwargs: dict = {'audience': aud or None,
                    'options': {'verify_aud': bool(aud)}}
    if iss:
        kwargs['issuer'] = iss

    header = jwt.get_unverified_header(token)
    alg = str(header.get('alg', ''))

    if alg in _ASYMMETRIC_ALGS:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, algorithms=[alg], **kwargs)

    if alg == 'HS256':
        secret = _jwt_secret()
        if not secret:
            raise jwt.InvalidTokenError(
                'HS256-токен, но SUPABASE_JWT_SECRET не сконфигурирован')
        return jwt.decode(token, secret, algorithms=['HS256'], **kwargs)

    raise jwt.InvalidTokenError(f'неподдерживаемый alg токена: {alg!r}')


def require_auth(roles=None):
    """Декоратор аутентификации/авторизации.
      • нет/битый/просроченный токен → 401;
      • роль не входит в `roles` → 403;
      • API_AUTH_OFF=1 → пропуск без токена, роль super_admin (локальный dev).
    Резолвит g.api_user = {sub, role, claims}.
    """
    allowed = set(roles) if roles else None

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if _auth_off():
                g.api_user = {'sub': 'dev', 'role': 'super_admin', 'claims': {}}
            else:
                header = request.headers.get('Authorization', '')
                if not header.startswith('Bearer '):
                    return api_json(error='missing bearer token', code=401)
                token = header[7:].strip()
                try:
                    claims = _decode(token)
                except jwt.ExpiredSignatureError:
                    return api_json(error='token expired', code=401)
                except jwt.InvalidTokenError:
                    return api_json(error='invalid token', code=401)
                except Exception as e:  # JWKS-фетч/ключ и пр. инфраструктурные сбои
                    logger.warning('auth: не удалось верифицировать токен: %s', e)
                    return api_json(error='auth verification failed', code=401)
                role = _extract_role(claims)
                g.api_user = {'sub': claims.get('sub'), 'role': role, 'claims': claims}

            if allowed is not None and g.api_user.get('role') not in allowed:
                return api_json(error='forbidden: role not allowed', code=403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_role() -> str | None:
    user = getattr(g, 'api_user', None)
    return user.get('role') if user else None


def current_user_id() -> str | None:
    """Supabase sub (uuid crm_users) текущего пользователя из g.api_user."""
    user = getattr(g, 'api_user', None)
    return user.get('sub') if user else None


# ── язык оператора: заголовок X-Locale от SPA (lib/api.ts читает cookie crm_locale) ──
# Каталог акций (bonuses.json) приходит с бэкенда, поэтому названия/условия/причины
# подбора локализует Flask, а не словари SPA. Белый список берём из bonus_catalog —
# единый источник правды: иначе новый язык, добавленный в каталог, молча отваливался бы
# на 'ru' здесь. bonus_catalog не тянет player_board, поэтому цикла импорта нет.
from bonus_catalog import LOCALES as API_LOCALES, DEFAULT_LOCALE   # noqa: E402


def req_locale() -> str:
    """Локаль текущего запроса из X-Locale; не из белого списка/нет заголовка → 'ru'.

    Заголовок контролирует клиент, поэтому доверяем только значениям из белого
    списка: наружу это значение уходит лишь как ключ словарей переводов.
    """
    loc = (request.headers.get('X-Locale') or '').strip().lower()
    return loc if loc in API_LOCALES else DEFAULT_LOCALE


def _app_meta() -> dict:
    user = getattr(g, 'api_user', None) or {}
    claims = user.get('claims') or {}
    meta = claims.get('app_metadata') if isinstance(claims, dict) else None
    return meta if isinstance(meta, dict) else {}


def current_affiliate_code() -> str | None:
    """affiliate_code текущего пользователя (кладёт auth-хук 0004 в app_metadata)."""
    code = _app_meta().get('affiliate_code')
    return str(code) if code else None


# ════════════════════════════════════════════════════════════════════════════
# Владение игроком (anti-IDOR). Гейт ПОВЕРХ require_auth: operator/affiliate/
# vip_manager физически не читают чужого игрока (деньги/скоры). Логика зеркалит
# RLS (0001/0002) — «образцовые 37/37», но применяется в Flask, т.к. аналитика
# идёт из ClickHouse (не под RLS). Подключение — psycopg к SUPABASE_DB_URL
# (тот же приём, что tegsoft/store.py); postgres-суперюзер обходит RLS, поэтому
# фильтруем ЯВНО здесь.
# ════════════════════════════════════════════════════════════════════════════
# Роли, видящие ВЕСЬ каталог игроков (надзор/аналитика/справка) — зеркало
# crm.reads_all_players() из миграции 0001.
READS_ALL_PLAYERS = frozenset({
    'super_admin', 'head_retention', 'director', 'analyst', 'finance',
    'risk_officer', 'viewer', 'marketing_manager', 'affiliate_manager', 'support',
})
# Роли с УРЕЗАННОЙ карточкой (без денег казино/скоров — только для звонка).
# operator возвращён сюда по решению клиента (2026-07-29): полную карточку
# откатили — оператору карточка без денег/аналитики (только звонок/оффер/заметки);
# «бонус эффект» оператору открыт ОТДЕЛЬНО пунктом меню «Бонусы: эффект», а не в
# карточке. head_department остаётся с полной карточкой.
RESTRICTED_SUMMARY_ROLES = frozenset({'operator', 'support', 'affiliate'})


def _pg_dsn() -> str | None:
    dsn = os.environ.get('SUPABASE_DB_URL', '').strip()
    return dsn or None


def _pg_exists(sql: str, params: dict) -> bool:
    """True, если запрос вернул хотя бы одну строку. Fail-closed: при недоступности
    БД считаем, что доступа НЕТ (не отдаём чужие данные из-за инфраструктурного сбоя)."""
    dsn = _pg_dsn()
    if not dsn:
        logger.error('can_access_player: SUPABASE_DB_URL не задан — доступ закрыт (fail-closed)')
        return False
    try:
        import psycopg  # noqa: PLC0415
    except ImportError:
        logger.error("can_access_player: psycopg не установлен — доступ закрыт (fail-closed)")
        return False
    try:
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() is not None
    except Exception as e:  # noqa: BLE001
        logger.error('can_access_player: ошибка запроса к БД — доступ закрыт: %s', e)
        return False


def can_access_player(role: str | None, user_id: str | None,
                      affiliate_code: str | None, pid: int) -> bool:
    """Может ли пользователь роли `role` открыть карточку/аналитику игрока `pid`.
    Зеркалит RLS: reads_all — да; operator — назначенные; head_department — игроки
    отдела; vip_manager — назначенные ИЛИ vip_level>=порога; affiliate — свой код.
    Неизвестная роль/отсутствие user_id → fail-closed (False)."""
    if not role:
        return False
    if role in READS_ALL_PLAYERS:
        return True

    if role == 'operator':
        if not user_id:
            return False
        return _pg_exists(
            "SELECT 1 FROM crm.player_assignments "
            "WHERE operator_id = %(uid)s AND casino_player_id = %(pid)s LIMIT 1",
            {'uid': user_id, 'pid': pid})

    if role == 'affiliate':
        if not affiliate_code:
            return False
        return _pg_exists(
            "SELECT 1 FROM crm.player_directory "
            "WHERE casino_player_id = %(pid)s AND affiliate_code = %(code)s LIMIT 1",
            {'pid': pid, 'code': affiliate_code})

    if role == 'vip_manager':
        # назначенный ИЛИ vip_level >= порога (crm.vip_threshold из settings)
        return _pg_exists(
            "SELECT 1 WHERE EXISTS ("
            "  SELECT 1 FROM crm.player_assignments "
            "  WHERE operator_id = %(uid)s AND casino_player_id = %(pid)s) "
            "OR EXISTS ("
            "  SELECT 1 FROM crm.player_directory d "
            "  WHERE d.casino_player_id = %(pid)s AND d.vip_level >= crm.vip_threshold())",
            {'uid': user_id, 'pid': pid})

    if role == 'head_department':
        # игроки, назначенные операторам МОЕГО отдела (зеркало crm.dept_player_ids)
        if not user_id:
            return False
        return _pg_exists(
            "SELECT 1 FROM crm.player_assignments a "
            "JOIN crm.crm_users me ON me.id = %(uid)s "
            "JOIN crm.crm_users op ON op.id = a.operator_id "
            "WHERE a.casino_player_id = %(pid)s "
            "  AND op.department IS NOT NULL AND op.department = me.department LIMIT 1",
            {'uid': user_id, 'pid': pid})

    return False


def ensure_player_access(pid: int):
    """Гейт владения для эндпоинта. Возвращает Response(403) при отказе, иначе None.
    Использование:  denied = ensure_player_access(pid);  if denied: return denied"""
    if not can_access_player(current_role(), current_user_id(),
                             current_affiliate_code(), pid):
        return api_json(error='forbidden: no access to this player', code=403)
    return None


def _restrict_summary_by_role(summary: dict, role: str | None) -> dict:
    """Урезает карточку по роли (immutable — возвращает НОВЫЙ dict):
      • operator/support/affiliate — без денег казино (money) и P&L/скоров: только
        стадия/vip/сигнал/оффер/маск.контакт (то, что нужно для звонка);
      • vip_manager — без P&L казино (game.ggr/net/beats_casino), деньги игрока и
        скоры остаются (VIP-карточка полная, но без «денег казино»);
      • прочие (надзор/аналитика/финансы) — полная карточка."""
    if role in RESTRICTED_SUMMARY_ROLES:
        scores = summary.get('scores') or {}
        p_churn = scores.get('p_churn')
        # коарс-сигнал оттока (band), без раскрытия сырого скора
        churn_band = None
        if isinstance(p_churn, (int, float)):
            churn_band = 'high' if p_churn >= 0.6 else 'medium' if p_churn >= 0.3 else 'low'
        prof = summary.get('profile') or {}
        safe_profile = {k: prof.get(k) for k in (
            'account_type', 'status', 'country', 'reg_date', 'tenure_days',
            'affiliate_type', 'affiliate_code', 'activity_status', 'is_depositor',
            'phone_verified', 'email_verified')}
        return {
            'player_id': summary.get('player_id'),
            'stage': summary.get('stage'),
            'vip_level': summary.get('vip_level'),
            'vip_label': summary.get('vip_label'),
            'profile': safe_profile,
            'contact': summary.get('contact'),
            'signal': {'lifecycle': summary.get('stage'), 'churn_band': churn_band},
            'recommendation': summary.get('recommendation'),
            'meta': {**(summary.get('meta') or {}), 'restricted': True},
        }
    if role == 'vip_manager':
        game = {k: v for k, v in (summary.get('game') or {}).items()
                if k not in ('ggr', 'net')}
        return {**summary, 'game': game, 'beats_casino': None,
                'meta': {**(summary.get('meta') or {}), 'restricted': 'no_casino_pnl'}}
    return summary


# ════════════════════════════════════════════════════════════════════════════
# Ролевая фильтрация PII (телефон/email). Открытый вопрос №5 плана — маска по умолчанию.
# ════════════════════════════════════════════════════════════════════════════
# полный доступ к контактам (звонят / ведут VIP / управляют базой)
PII_FULL = {'super_admin', 'head_retention', 'head_department', 'vip_manager'}
# маскированный контакт (видят «хвост», звонят только click-to-call — защита от увода базы)
PII_MASKED = {'operator', 'affiliate', 'support', 'risk_officer', 'director'}
# director — masked: руководству нужна кнопка звонка (клик-ту-колл), но полный номер
# ему не нужен (набор идёт на бэкенде). Всем прочим (analyst, viewer, finance,
# marketing_manager, affiliate_manager, неизвестная роль) — контакты не отдаём (fail-closed).


def _pii_mode(role: str | None) -> str:
    if role in PII_FULL:
        return 'full'
    if role in PII_MASKED:
        return 'masked'
    return 'none'


def _mask_phone(cc: str, phone, mode: str):
    if phone in (None, ''):
        return phone
    s = str(phone)
    if mode == 'full':
        return s
    if mode == 'masked':
        digits = ''.join(ch for ch in s if ch.isdigit())
        tail = digits[-4:] if len(digits) >= 4 else digits
        return f"{cc or ''}•••••{tail}"          # маска по умолчанию: +90•••••1234
    return None


def _mask_email(email, mode: str):
    if email in (None, ''):
        return email
    s = str(email)
    if mode == 'full':
        return s
    if mode == 'masked':
        if '@' in s:
            local, _, domain = s.partition('@')
            head = local[:1] if local else ''
            return f"{head}•••@{domain}"
        return '•••'
    return None


def mask_pii(data, role):
    """Возвращает НОВУЮ структуру с замаскированными по роли phone/email
    (immutable — исходник не мутируется). Рекурсивно обходит dict/list;
    country-code берётся из соседнего ключа 'phone_country_code'."""
    mode = _pii_mode(role)
    return _mask_node(data, mode)


def _mask_node(node, mode):
    if isinstance(node, list):
        return [_mask_node(x, mode) for x in node]
    if not isinstance(node, dict):
        return node
    cc = node.get('phone_country_code') or ''
    out = {}
    for k, v in node.items():
        if k == 'phone':
            out[k] = _mask_phone(cc, v, mode)
        elif k == 'email':
            out[k] = _mask_email(v, mode)
        elif isinstance(v, (dict, list)):
            out[k] = _mask_node(v, mode)
        else:
            out[k] = v
    return out


# ════════════════════════════════════════════════════════════════════════════
# Выборки (переиспользуют pb.q — без дублирования SQL/формул)
# ════════════════════════════════════════════════════════════════════════════
def _features(pid: int) -> dict | None:
    cols, rows = pb.q("SELECT * FROM player_features WHERE casino_player_id={pid:UInt32}", {'pid': pid})
    if not rows:
        return None
    return dict(zip(cols, rows[0]))


def _favourite_name(pid: int, uuid: str) -> str:
    if not uuid:
        return uuid
    try:
        r = pb.q(f"SELECT {pb.GN('game_uuid')} FROM player_games "
                 "WHERE casino_player_id={pid:UInt32} AND game_uuid={g:String} LIMIT 1",
                 {'pid': pid, 'g': uuid})[1]
        return str(r[0][0]) if r else uuid
    except Exception:
        return uuid


# ── решение отдела по офферу (retention.player_offers) ────────────────────────
# Единый источник со СТАРЫМ бордом: он пишет сюда через POST /offer/<pid>, SPA —
# через POST /api/v1/players/<id>/offer. Раньше SPA писал решение только в
# crm.notes, и бейдж «✅ утверждён» на /desk (он читает player_offers) не видел
# того, что оператор утвердил в SPA.
OFFER_STATUSES = ('approved', 'edited', 'rejected', 'sent')

# Кто оформляет оффер: ретеншн-команда. Аффилиату/саппорту/аналитику — нельзя.
OFFER_ROLES = ['operator', 'vip_manager', 'head_department', 'head_retention',
               'director', 'super_admin']


def _saved_offer(pid: int) -> tuple[str, str, str, str]:
    """Последнее решение по офферу → (status, offer_text, note, date дд.мм.гггг).
    Пусто — если не оформляли. ReplacingMergeTree(ts) → argMax по ts, как HTML-карточка."""
    try:
        r = pb.q("SELECT argMax(status,ts), argMax(offer_text,ts), argMax(note,ts), "
                 "formatDateTime(max(ts), '%d.%m.%Y') "
                 "FROM player_offers WHERE casino_player_id={pid:UInt32}", {'pid': pid})[1]
    except Exception:
        return ('', '', '', '')
    if not r or not r[0][0]:
        return ('', '', '', '')
    return (str(r[0][0] or ''), str(r[0][1] or ''), str(r[0][2] or ''), str(r[0][3] or ''))


def _actions_row(pid: int, locale: str = 'ru') -> dict:
    r = pb.q("SELECT action, bonus, when_to, priority, value_try, early_tier, "
             "pred_ltv_d90, ltv_headroom, p_2nd_deposit, p_churn, lifecycle, dep_count "
             "FROM player_actions WHERE casino_player_id={pid:UInt32}", {'pid': pid})[1]
    if not r:
        return {}
    (action, bonus, when_to, priority, value_try, early_tier,
     pred_ltv_d90, ltv_headroom, p_2nd, p_churn, life, dc) = r[0]
    # bonus/when_to собирает SQL-витрина по-русски → переводим на язык оператора
    bonus = pb.bonus_label(bonus, locale)
    when_to = pb.when_to_label(when_to, locale)
    return {'action': action, 'bonus': bonus, 'when_to': when_to, 'priority': priority,
            'value_try': value_try, 'early_tier': early_tier, 'pred_ltv_d90': pred_ltv_d90,
            'ltv_headroom': ltv_headroom, 'p_2nd_deposit': p_2nd, 'p_churn': p_churn,
            'lifecycle': life, 'dep_count': dc}


def _score(table: str, col: str, pid: int):
    """Одиночный ML-скор из опциональной таблицы (если её нет — None)."""
    if not pb._has_table(table):
        return None
    try:
        r = pb.q(f"SELECT {col} FROM {table} WHERE casino_player_id={{pid:UInt32}}", {'pid': pid})[1]
        return float(r[0][0]) if r else None
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# Эндпоинты
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/players/<int:pid>/summary')
@require_auth()
def player_summary(pid: int):
    """Карточка 360: профиль, стадия, VIP, флаг «обыгрывает казино», деньги, игра,
    скоры моделей (в т.ч. VIP-модели) и рекомендация оффера из каталога."""
    denied = ensure_player_access(pid)   # anti-IDOR: чужого игрока — 403 (до раскрытия существования)
    if denied:
        return denied
    d = _features(pid)
    if d is None:
        return api_json(error='player not found', code=404)

    role = current_role()
    net = float(d.get('net') or 0.0)
    net_cash = float(d.get('net_cash') or 0.0)
    ggr = -net                                   # GGR казино = −net игрока (как в борде)
    # флаг «обыгрывает казино»: вывел кэша больше, чем внёс (net_cash<0) И выиграл в игре (net>0)
    beats_casino = (net_cash < 0) and (net > 0)

    act = _actions_row(pid, req_locale())
    # оффер из реального каталога (та же функция, что в HTML-карточке), на языке оператора
    try:
        offer_name, offer_terms, offer_reason = pb.offer_for({
            'lifecycle': d.get('lifecycle'), 'dep_count': d.get('dep_count'),
            'early_tier': act.get('early_tier'), 'pred_ltv_d90': act.get('pred_ltv_d90'),
            'p_churn': act.get('p_churn'), 'net': net, 'net_cash': net_cash}, req_locale())
    except Exception:
        offer_name, offer_terms, offer_reason = ('—', '', '')

    # Сохранённое решение отдела по офферу (player_offers) — 1-в-1 с HTML-карточкой:
    # ReplacingMergeTree, поэтому берём последнюю запись через argMax(...,ts).
    # Если оффер уже оформляли, в поле показывается ЕГО текст, а не подобранный.
    saved_status, saved_text, saved_note, saved_at = _saved_offer(pid)

    vip = int(d.get('vip_level') or 0)
    fav_uuid = str(d.get('favourite_game') or '')

    # контакты — из users; маскируются по роли ниже
    contact = {'phone': None, 'phone_country_code': None, 'email': None,
               'phone_verified': d.get('phone_verified'), 'email_verified': d.get('email_verified')}
    try:
        cu = pb.q("SELECT phone, phone_country_code, email FROM users "
                  "WHERE casino_player_id={pid:UInt32} LIMIT 1", {'pid': pid})[1]
        if cu:
            contact['phone'], contact['phone_country_code'], contact['email'] = cu[0]
    except Exception:
        pass

    summary = {
        'player_id': pid,
        'stage': d.get('lifecycle'),
        'vip_level': vip,
        'vip_label': VIP_LABELS.get(vip, str(vip)),
        'beats_casino': beats_casino,
        'profile': {
            'account_type': d.get('account_type'), 'status': d.get('status'),
            'country': d.get('country'), 'reg_date': d.get('reg_date'),
            'tenure_days': d.get('tenure_days'), 'affiliate_type': d.get('affiliate_type'),
            'affiliate_code': d.get('affiliate_code'), 'ftd_amount': d.get('ftd_amount'),
            'phone_verified': d.get('phone_verified'), 'email_verified': d.get('email_verified'),
            'balance': d.get('balance'), 'bonus_balance': d.get('bonus_balance'),
            'activity_status': d.get('activity_status'),
            'is_depositor': int(d.get('dep_count') or 0) > 0,
        },
        'contact': contact,
        'money': {
            'cash_deposits': d.get('cash_deposits'), 'withdrawals_abs': d.get('withdrawals_abs'),
            'net_cash': net_cash, 'bonus_cost': d.get('bonus_cost'),
            'dep_sum': d.get('dep_sum'), 'dep_count': d.get('dep_count'),
            'dep_failed': d.get('dep_failed'), 'wd_count': d.get('wd_count'),
            'wd_sum': d.get('wd_sum'), 'wd_rejected': d.get('wd_rejected'),
            'bonus_count': d.get('bonus_count'), 'bonus_sum': d.get('bonus_sum'),
            'primary_payment_method': d.get('primary_payment_method'),
            'deposit_recency_days': d.get('deposit_recency_days'),
        },
        'game': {
            'bets': d.get('bets'), 'turnover': d.get('turnover'), 'wins_sum': d.get('wins_sum'),
            'net': net, 'ggr': ggr, 'avg_bet': d.get('avg_bet'), 'max_bet': d.get('max_bet'),
            'distinct_games': d.get('distinct_games'), 'active_days': d.get('active_days'),
            'recency_days': d.get('recency_days'), 'primary_provider': d.get('primary_provider'),
            'favourite_game': fav_uuid, 'favourite_game_name': _favourite_name(pid, fav_uuid),
            'favourite_game_bets': d.get('favourite_game_bets'),
            'game_concentration': d.get('game_concentration'),
            'freespin_ratio': d.get('freespin_ratio'), 'night_share': d.get('night_share'),
            'bets_per_active_day': d.get('bets_per_active_day'),
            'activation_lag_days': d.get('activation_lag_days'),
        },
        'scores': {
            'p_churn': act.get('p_churn'), 'p_2nd_deposit': act.get('p_2nd_deposit'),
            'pred_ltv_d90': act.get('pred_ltv_d90'), 'ltv_headroom': act.get('ltv_headroom'),
            'early_tier': act.get('early_tier'), 'value_try': act.get('value_try'),
            'priority': act.get('priority'),
            'p_vip_churn': _score('player_vip_churn_ml', 'p_vip_churn', pid),
            'p_early_vip': _score('player_early_vip_ml', 'p_early_vip', pid),
            'p_non_promising': _score('player_non_promising_vip_ml', 'p_non_promising', pid),
        },
        'recommendation': {
            'action': act.get('action'), 'bonus': act.get('bonus'), 'when_to': act.get('when_to'),
            'offer_name': offer_name, 'offer_terms': offer_terms, 'offer_reason': offer_reason,
            # решение отдела (player_offers) — тот же источник, что у старого борда.
            # saved_text заполнен → карточка показывает ЕГО, а не подобранный оффер.
            'offer_status': saved_status or None,
            'offer_saved_text': saved_text or None,
            'offer_saved_note': saved_note or None,
            'offer_saved_at': saved_at or None,
        },
        'meta': {'role': role, 'pii': _pii_mode(role)},
    }
    # урезаем деньги/скоры по роли, затем маскируем PII (immutable-цепочка)
    return api_json(mask_pii(_restrict_summary_by_role(summary, role), role))


@bp.post('/players/<int:pid>/offer')
@require_auth(roles=OFFER_ROLES)
def save_player_offer(pid: int):
    """Решение отдела по офферу → retention.player_offers (ClickHouse).

    ЕДИНЫЙ ИСТОЧНИК со старым бордом (он пишет сюда же через POST /offer/<pid>),
    поэтому бейдж статуса на /desk и в HTML-карточке видит решение из SPA.
    Тело: {status: approved|edited|rejected|sent, offer_text, note}.
    """
    denied = ensure_player_access(pid)   # anti-IDOR: только свой игрок
    if denied:
        return denied

    body = request.get_json(silent=True) or {}
    status = str(body.get('status') or '')
    if status not in OFFER_STATUSES:
        return api_json(error=f'status: ожидается один из {", ".join(OFFER_STATUSES)}', code=422)
    offer_text = str(body.get('offer_text') or '')[:500]   # лимиты как в борде
    note = str(body.get('note') or '')[:500]

    u = getattr(g, 'api_user', None) or {}
    operator = str(u.get('sub') or 'spa')[:40]             # колонка String(40)
    try:
        pb._client().insert(
            'player_offers', [[pid, status, offer_text, note, operator]],
            column_names=['casino_player_id', 'status', 'offer_text', 'note', 'operator'])
    except Exception as e:
        logger.error('offer save failed (player=%s): %s', pid, e)
        return api_json(error='Не удалось сохранить решение по офферу', code=503)

    # аудит — тем же приёмом, что звонилка (crm.audit_log). Не критичен: сбой
    # аудита не должен отменять уже сохранённое решение.
    try:
        from tegsoft.store import write_audit
        write_audit(operator, 'offer_save', 'player', str(pid), {'status': status})
    except Exception as e:
        logger.warning('offer audit skipped (player=%s): %s', pid, e)

    return api_json({'player_id': pid, 'status': status})


@bp.get('/players/<int:pid>/heatmap')
@require_auth()
def player_heatmap(pid: int):
    """Тепловая карта час×день недели по ставкам (для автоподсказки времени звонка)."""
    denied = ensure_player_access(pid)   # anti-IDOR
    if denied:
        return denied
    if _features(pid) is None:
        return api_json(error='player not found', code=404)
    data, stats = pb._rhythm(
        "casino_player_id={pid:UInt32} AND transaction_type IN ('bet','freespins_bet')",
        {'pid': pid})
    return api_json({'player_id': pid, 'heatmap': data, 'stats': stats})


@bp.get('/queue/priorities')
@require_auth()
def queue_priorities():
    """По списку id (?ids=1,2,3) — приоритет/действие/бонус/когда из player_actions.
    Для очереди оператора (сортировка по priority). Максимум 500 id за запрос."""
    raw = request.args.get('ids', '')
    ids = []
    for part in raw.split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    ids = ids[:500]
    if not ids:
        return api_json({'items': []})
    id_list = ','.join(str(i) for i in ids)     # значения уже провалидированы в int
    rows = pb.q(
        "SELECT casino_player_id, priority, action, bonus, when_to, value_try, "
        "p_churn, p_2nd_deposit, lifecycle "
        f"FROM player_actions WHERE casino_player_id IN ({id_list}) "
        "ORDER BY priority DESC, value_try DESC")[1]
    loc = req_locale()   # bonus/when_to витрина отдаёт по-русски → переводим
    items = [{
        'player_id': r[0], 'priority': r[1], 'action': r[2],
        'bonus': pb.bonus_label(r[3], loc), 'when_to': pb.when_to_label(r[4], loc),
        'value_try': r[5], 'p_churn': r[6],
        'p_2nd_deposit': r[7], 'lifecycle': r[8],
    } for r in rows]
    return api_json({'items': items})


# УДАЛЁН: GET /players/search — поиск по префиксу id.
#
# Стоял под @require_auth() БЕЗ ролей и БЕЗ фильтра доступа, т.е. отдавал
# turnover/net/vip_level по любому игроку любой авторизованной роли — включая
# affiliate/marketing/operator, которым тот же список через GET /players закрыт
# (LIST_ROLES). Для affiliate это был обход привязки к своему affiliate_code:
# перебор базы по префиксу id с финансовыми полями.
#
# Функционально не нужен: SPA ищет через GET /players?q= (players_analytics.py),
# который режет и по роли, и по _players_filter. Восстанавливать — только с
# require_auth(roles=LIST_ROLES) и тем же фильтром.
