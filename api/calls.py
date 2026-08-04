"""Blueprint звонилки: originate / webhook-приёмник / стрим записи.

Звонилка работает ТОЛЬКО через бэкенд (раздел 2 SPA_BUILD_PLAN.md):
секреты Tegsoft и телефон игрока не покидают сервер, фронт присылает лишь
casino_player_id.

Регистрация: пакет `api/` (ядро — агент A3) авто-подхватывает любой `api/*.py`,
где определена переменная `bp = Blueprint(...)`. Ядро (api/core.py) может быть ещё
не готово — авторизацию импортируем мягко (см. ниже).
"""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, Response, g, jsonify, request

from tegsoft import get_provider
from tegsoft.adapter import CallProviderError
from tegsoft import lookup, store
from tegsoft.lookup import DoNotContactError, PlayerLookupError

logger = logging.getLogger("api.calls")

# ── авторизация ядра (api/core.py) ───────────────────────────────────────────────
# require_auth — ФАБРИКА декоратора: @require_auth() или @require_auth({роли}).
# Ставит g.api_user = {'sub','role','claims'}.
#
# Импорт ЖЁСТКИЙ и это осознанно (fail-closed). Раньше здесь стоял try/except
# ImportError с dev-заглушкой, где can_access_player() возвращала True: если бы
# ядро не импортировалось (например, на VPS не встал PyJWT — core.py тянет jwt
# на верхнем уровне), звонилка молча поднялась бы БЕЗ авторизации и позволила
# звонить на реальные номера без токена. Теперь при сбое ядра register_api
# просто не зарегистрирует домен (эндпоинты отдадут 404) и запишет ошибку в лог.
import re  # noqa: E402
from api.core import require_auth, current_role, current_user_id, can_access_player  # noqa: E402

bp = Blueprint("calls", __name__)

# Кто управляет маппингом «оператор → extension» (экран «Внутренние номера»).
EXT_ADMIN_ROLES = frozenset({"super_admin", "head_retention", "head_department"})
# extension — только цифры/*/#/- , 1..12 символов (SIP-номер; защита от инъекции в originate)
_EXT_RE = re.compile(r"^[0-9*#\-]{1,12}$")

# ── матрица ролей на звонок / прослушивание (раздел 1 SPA_BUILD_PLAN.md) ──────────
CALL_ROLES = frozenset({
    "operator", "head_department", "head_retention", "vip_manager", "affiliate", "super_admin",
    "director",   # руководство тоже может инициировать звонок (паритет с бордом, где всё доступно)
})
RECORDING_ROLES = frozenset({
    "risk_officer", "head_department", "head_retention", "director", "super_admin",
})


# ── идентичность пользователя (из g.api_user, проставляет require_auth ядра A3) ────
def _current_user() -> dict:
    """role/id/ext из g.api_user. operator_id = Supabase sub (uuid crm_users);
    ext — из app_metadata.tegsoft_ext (если задан в токене), иначе маппинг по id."""
    u = getattr(g, "api_user", None) or {}
    claims = u.get("claims") or {}
    meta = claims.get("app_metadata") if isinstance(claims, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    ext = meta.get("tegsoft_ext")
    aff = meta.get("affiliate_code")
    return {"role": u.get("role"), "id": u.get("sub"), "ext": ext,
            "affiliate_code": str(aff) if aff else None}


def _err(message: str, code: int, **extra):
    return jsonify({"ok": False, "data": None, "error": message, **extra}), code


def _ok(data, code: int = 200):
    return jsonify({"ok": True, "data": data, "error": None}), code


# ── POST /api/v1/calls/originate ────────────────────────────────────────────────
@bp.post("/api/v1/calls/originate")
@require_auth(CALL_ROLES)
def originate():
    """Инициировать звонок игроку. Тело: {casino_player_id}. Телефон берётся на бэкенде;
    в ответе номер НЕ отдаём (только маска). Доступ гейтит require_auth(CALL_ROLES)."""
    user = _current_user()
    body = request.get_json(silent=True) or {}
    raw_id = body.get("casino_player_id")
    try:
        casino_player_id = int(raw_id)
    except (TypeError, ValueError):
        return _err("casino_player_id обязателен и должен быть числом", 422)

    operator_id = user.get("id")
    if not operator_id:
        return _err("Не определён оператор (нет id в токене)", 401)

    # anti-IDOR: звонить можно ТОЛЬКО назначенному игроку (operator/vip — свои,
    # head_department — свой отдел, affiliate — свой код; super_admin/head_retention —
    # без скоупа). Иначе можно было бы инициировать звонок любому игроку по id.
    if not can_access_player(user.get("role"), operator_id,
                             user.get("affiliate_code"), casino_player_id):
        return _err("Игрок не назначен звонящему (или вне вашего скоупа)", 403)

    # телефон игрока — строго на бэкенде (ClickHouse), уважаем do_not_contact
    try:
        phone = lookup.get_player_phone(casino_player_id)
    except DoNotContactError as e:
        return _err(str(e), 409)
    except PlayerLookupError as e:
        return _err(str(e), 404)

    try:
        ext = user.get("ext") or lookup.operator_ext(operator_id)
    except PlayerLookupError as e:
        return _err(str(e), 422)

    provider = _provider_for_operator(operator_id)
    try:
        call_ref = provider.originate(ext, phone)
    except CallProviderError as e:
        logger.warning("originate failed (player=%s): %s", casino_player_id, e)
        return _err(f"Не удалось инициировать звонок: {e}", 502)

    store.write_audit(
        operator_id, "call_originate", "player", str(casino_player_id),
        {"provider_ref": call_ref, "provider": provider.name},
    )
    # номер в ответе замаскирован — защита от увода базы (открытый вопрос №5 плана)
    return _ok({"call_ref": call_ref, "player_phone_masked": lookup.mask_phone(phone)})


# ── POST /api/v1/webhooks/tegsoft[/<секрет>] ─────────────────────────────────────
# Два пути к одному обработчику:
#   /api/v1/webhooks/tegsoft            — секрет в заголовке X-Tegsoft-Secret;
#   /api/v1/webhooks/tegsoft/<секрет>   — секрет в URL-пути (форма Tegsoft «Управление
#                                         веб-перехватчиком» умеет URL, но не кастомный
#                                         заголовок — тогда кладём секрет в путь).
# Оба варианта валидируются constant-time против TEGSOFT_WEBHOOK_SECRET (fail-closed).
@bp.post("/api/v1/webhooks/tegsoft")
@bp.post("/api/v1/webhooks/tegsoft/<path:path_secret>")
def webhook(path_secret: str | None = None):
    """Приёмник событий Tegsoft: валидирует shared-secret, пишет/обновляет crm.calls.
    Не под require_auth: аутентификация — по shared-secret (машина-машина).

    Формат тела Tegsoft-вебхука заранее не фиксирован (ECR JSON vs форма
    «Управление веб-перехватчиком» с PARAMETER-полями), поэтому поля читаем
    ВСЕЯДНО: JSON-тело ∪ form-body ∪ query, а имена — по набору алиасов."""
    if not _valid_secret(request, path_secret):
        return _err("Неверный или отсутствующий shared-secret", 401)

    payload = _merged_payload(request)
    provider_ref = _pick(payload, "provider_ref", "CALLID", "callId",
                         "UNIQUEID", "uniqueId", "callRef")

    # Боевой Tegsoft-ECR обычно шлёт только CALLID (=provider_ref) + исход + длительность,
    # без нашего casino_player_id/operator_id. Восстанавливаем их из связки, записанной
    # при originate() в audit_log (store.lookup_originate) — сквозная фиксация звонка
    # без зависимости от того, умеет ли их ECR подставлять наши id в webhook.
    casino_player_id = _coerce_int(_pick(payload, "casino_player_id"))
    operator_ext = _pick(payload, "operator_ext", "EXTEN", "CALLERID", "agent_ext")
    operator_id = _pick(payload, "operator_id") or lookup.operator_id_for_ext(operator_ext)

    if (casino_player_id is None or not operator_id) and provider_ref:
        try:
            origin = store.lookup_originate(provider_ref)
        except store.CrmStoreError as e:
            logger.warning("webhook: lookup_originate(%s) не удался: %s", provider_ref, e)
            origin = None
        if origin:
            if casino_player_id is None:
                casino_player_id = origin.get("casino_player_id")
            if not operator_id:
                operator_id = origin.get("operator_id")

    if casino_player_id is None:
        return _err("webhook: casino_player_id не задан и не найден по provider_ref", 422)
    if not operator_id:
        return _err("webhook: не удалось определить operator_id (нет operator_id/operator_ext/связки)", 422)

    record = {
        "casino_player_id": casino_player_id,
        "operator_id": operator_id,
        # исход: наш outcome ИЛИ Tegsoft status (OFFER/ANSWERED/RINGNOANSWER/HANGUP…)
        "outcome": lookup.normalize_outcome(_pick(payload, "outcome", "status", "DISPOSITION")),
        "result": _valid_result(_pick(payload, "result")),
        "provider_ref": provider_ref,
        # время старта: наш started_at ИЛИ Tegsoft CALLDATE ("dd/MM/yyyy HH:mm:ss")
        "started_at": _coerce_started_at(_pick(payload, "started_at", "CALLDATE", "callDate")),
        # длительность: наш duration_sec / Tegsoft BILLSEC (сек) / *Millis (мс → сек)
        "duration_sec": _duration_seconds(payload),
        "recording_ref": _pick(payload, "recording_ref", "recordingFile", "MONITOR"),
    }

    try:
        call_id = store.upsert_call(record)
    except store.CrmStoreError as e:
        logger.error("webhook: запись crm.calls не удалась: %s", e)
        return _err(f"Запись звонка не удалась: {e}", 503)

    store.write_audit(
        operator_id, "call_webhook", "call", call_id,
        {"provider_ref": record["provider_ref"], "outcome": record["outcome"]},
    )
    return _ok({"call_id": call_id, "outcome": record["outcome"]})


# ── GET /api/v1/calls/<id>/recording ────────────────────────────────────────────
@bp.get("/api/v1/calls/<call_id>/recording")
@require_auth(RECORDING_ROLES)
def recording(call_id: str):
    """Стрим записи звонка через провайдера. Роли: risk_officer / главы / director / super_admin
    (гейтит require_auth(RECORDING_ROLES))."""
    user = _current_user()
    try:
        call = store.fetch_call(call_id)
    except store.CrmStoreError as e:
        return _err(f"Не удалось прочитать звонок: {e}", 503)
    if not call:
        return _err("Звонок не найден", 404)

    ref = call.get("recording_ref") or call.get("provider_ref")
    if not ref:
        return _err("У звонка нет записи", 404)

    provider = get_provider()
    try:
        stream = provider.stream_recording(ref)
        first = next(stream, b"")
    except CallProviderError as e:
        return _err(f"Запись недоступна: {e}", 502)

    store.write_audit(
        user.get("id"), "recording_listen", "call", call_id,
        {"ref": ref, "provider": provider.name},
    )

    def _body():
        if first:
            yield first
        yield from stream

    return Response(_body(), mimetype="audio/mpeg")


# ── GET/PUT /api/v1/calls/extensions — маппинг оператор → extension ───────────────
@bp.get("/api/v1/calls/extensions")
@require_auth(EXT_ADMIN_ROLES)
def list_extensions():
    """Список активных операторов (call-роли) + их Tegsoft extension. Для экрана
    «Внутренние номера» (super_admin / главы). Без extension originate падает."""
    try:
        rows = store.list_operator_extensions()
    except Exception as e:  # noqa: BLE001 — БД/psycopg
        return _err(f"Не удалось загрузить операторов: {e}", 503)
    return _ok({"operators": rows})


@bp.put("/api/v1/calls/extensions/<operator_id>")
@require_auth(EXT_ADMIN_ROLES)
def set_extension(operator_id: str):
    """Задать креды TG-Soft оператора. Тело: {ext, token?}. ext — как есть (пусто →
    сброс), валидируется (цифры/*/#/-, ≤12). token — персональный токен оператора
    (write-only): непустой → обновить, пустой/нет → не менять. ext+token пустые →
    строка удаляется."""
    body = request.get_json(silent=True) or {}
    ext = str(body.get("ext") or "").strip()
    usercode = str(body.get("usercode") or "").strip()
    password = str(body.get("password") or "").strip()
    token = str(body.get("token") or "").strip()
    if ext and not _EXT_RE.match(ext):
        return _err("extension: допустимы только цифры, * # - (до 12 символов)", 422)
    # updated_by — только валидный UUID (в dev sub='dev' → пишем NULL, чтобы не упасть на FK)
    uid = current_user_id()
    by = str(uid) if _is_uuid(uid) else None
    try:
        store.set_operator_creds(operator_id, ext, usercode=usercode,
                                 password=password or None, token=token or None, updated_by=by)
    except Exception as e:  # noqa: BLE001 — БД/psycopg/валидация
        return _err(f"Не удалось сохранить креды: {e}", 503)
    return _ok({"operator_id": operator_id, "ext": ext or None})


@bp.delete("/api/v1/calls/extensions/<operator_id>")
@require_auth(EXT_ADMIN_ROLES)
def clear_extension(operator_id: str):
    """Полный сброс кредов оператора (ext/логин/пароль/токен) — например, если
    завели не тому. Пароль/токен иначе не очистить (они write-only)."""
    try:
        store.delete_operator_creds(operator_id)
    except Exception as e:  # noqa: BLE001 — БД/psycopg
        return _err(f"Не удалось сбросить креды: {e}", 503)
    return _ok({"operator_id": operator_id, "cleared": True})


def _provider_for_operator(operator_id):
    """Провайдер для originate. На боевом кластере f81o27 ПОДТВЕРЖДЕНО тестом:
    API-звонок (ServicesGateway/RemotePBX) проходит ТОЛЬКО под интеграционным
    аккаунтом `entegreapi`; операторские токены/логины дают 401 (нет прав на API),
    performLogin отвергается (Code:898). Поэтому originate всегда идёт под общим
    провайдером, а «кто звонит» задаёт EXTENSION оператора.

    Персональный токен оператора используем ТОЛЬКО если у его учётки включён
    API-доступ (env CALL_USE_OPERATOR_TOKEN=1) — для кластеров/учёток, где это
    разрешено. По умолчанию выключено (иначе 401)."""
    if os.environ.get("CALL_USE_OPERATOR_TOKEN", "").strip() in ("1", "true", "yes"):
        try:
            creds = store.get_operator_creds(operator_id)
        except Exception:                   # noqa: BLE001
            creds = {}
        if creds.get("token"):
            from tegsoft.adapter import TegsoftProvider  # noqa: PLC0415
            # agent_call=True: звонок «от имени агента» (ContactCenterServices/agentCall)
            # → БЕЗ попапа «ответить» (WebRTC-трубка соединяется сразу, как ручной набор).
            return TegsoftProvider(token=creds["token"], agent_call=True)
        if creds.get("usercode") and creds.get("password"):
            from tegsoft.adapter import TegsoftProvider  # noqa: PLC0415
            return TegsoftProvider(usercode=creds["usercode"], password=creds["password"],
                                   token="", agent_call=True)
    return get_provider()


# номер назначения теста: цифры/+, 3..20 символов (защита от инъекции в originate)
_DEST_RE = re.compile(r"^\+?[0-9]{3,20}$")


@bp.post("/api/v1/calls/test")
@require_auth(EXT_ADMIN_ROLES)
def test_call():
    """Тестовый звонок: поднять плечо ВЫБРАННОГО оператора (его ext + креды) и
    соединить с ПРОИЗВОЛЬНЫМ номером. Только для админов — проверить телефонию до
    боевых звонков. Тело: {operator_id, destination}."""
    body = request.get_json(silent=True) or {}
    operator_id = str(body.get("operator_id") or "").strip()
    destination = str(body.get("destination") or "").strip().replace(" ", "")
    if not _is_uuid(operator_id):
        return _err("operator_id обязателен (UUID оператора)", 422)
    if not _DEST_RE.match(destination):
        return _err("Номер: только цифры и + (3–20 знаков), напр. 905551234567", 422)
    try:
        ext = lookup.operator_ext(operator_id)
    except PlayerLookupError as e:
        return _err(str(e), 422)
    provider = _provider_for_operator(operator_id)
    try:
        call_ref = provider.originate(ext, destination)
    except CallProviderError as e:
        logger.warning("test originate failed (op=%s): %s", operator_id, e)
        return _err(f"Не удалось инициировать тест-звонок: {e}", 502)
    store.write_audit(_current_user().get("id"), "call_test", "operator", operator_id,
                      {"provider_ref": call_ref, "ext": ext})
    return _ok({"call_ref": call_ref, "ext": ext, "destination_masked": lookup.mask_phone(destination)})


# ── утилиты ──────────────────────────────────────────────────────────────────────
def _is_uuid(v) -> bool:
    import uuid  # noqa: PLC0415
    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _pick(data: dict, *keys):
    """Первое непустое значение по набору имён-алиасов (форматы Tegsoft разнятся)."""
    for k in keys:
        v = data.get(k)
        if v not in (None, ""):
            return v
    return None


def _duration_seconds(payload: dict):
    """Длительность звонка в СЕКУНДАХ. Наш duration_sec / Tegsoft BILLSEC (сек)
    приоритетны; из *Millis (talkDurationMillis — в ДОКАХ Tegsoft в миллисекундах)
    переводим мс→сек, иначе записали бы значение в 1000× больше."""
    sec = _coerce_int(_pick(payload, "duration_sec", "BILLSEC", "TALKDURATION",
                            "duration", "waitDurationSeconds"))
    if sec is not None:
        return sec
    ms = _coerce_int(_pick(payload, "talkDurationMillis", "billMillis", "durationMillis"))
    return None if ms is None else ms // 1000


def _merged_payload(req) -> dict:
    """Всеядный разбор тела вебхука: JSON ∪ form ∪ query.

    Tegsoft в зависимости от механизма (ECR-роутер / форма «Управление
    веб-перехватчиком») шлёт то JSON-объект, то form/query-параметры —
    сливаем все источники в один плоский dict (JSON приоритетнее)."""
    merged: dict = {}
    try:
        merged.update(req.args.to_dict())            # query-строка
    except Exception:  # noqa: BLE001
        pass
    try:
        if req.form:
            merged.update(req.form.to_dict())        # form-encoded тело
    except Exception:  # noqa: BLE001
        pass
    body = req.get_json(silent=True)
    if isinstance(body, dict):
        merged.update(body)                          # JSON-тело — высший приоритет
    return merged


def _valid_secret(req, path_secret: str | None = None) -> bool:
    """Constant-time сверка shared-secret. Fail-closed: если секрет не сконфигурирован —
    отказ (как REQUIRE_AUTH в player_board).

    Секрет принимаем из HTTP-заголовка ЛИБО из URL-пути. Причина двух путей:
    форма Tegsoft «Управление веб-перехватчиком» умеет задать URL, но не всегда —
    кастомный заголовок; тогда секрет кладём сегментом пути. Из query-строки
    секрет НЕ берём (утекает в логи прокси/истории)."""
    configured = os.environ.get("TEGSOFT_WEBHOOK_SECRET", "")
    if not configured:
        logger.error("TEGSOFT_WEBHOOK_SECRET не задан — webhook отклонён (fail-closed)")
        return False
    provided = (
        path_secret
        or req.headers.get("X-Tegsoft-Secret")
        or req.headers.get("X-Webhook-Secret")
        or ""
    )
    return bool(provided) and hmac.compare_digest(str(provided), configured)


_VALID_RESULTS = frozenset({"interested", "offer_declined", "callback_requested", "refused"})


def _valid_result(val):
    return val if val in _VALID_RESULTS else None


def _coerce_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _coerce_started_at(val):
    """Привести started_at к ISO-строке (принимаем ISO-строку или epoch-секунды)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(float(val), tz=timezone.utc).isoformat()
    return str(val)
