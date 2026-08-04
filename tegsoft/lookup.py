"""Серверные справочные хелперы звонилки:
  - телефон игрока из ClickHouse `retention.users` (НЕ приходит с фронта);
  - маскирование номера для ответа/лога;
  - маппинг оператор↔extension (Tegsoft ext);
  - нормализация исхода звонка (событие Tegsoft → enum crm.call_outcome).

Телефон берётся строго на бэкенде: фронт присылает только casino_player_id.
`do_not_contact` уважаем — не даём звонить в стоп-лист.
"""
from __future__ import annotations

import json
import logging
import os
import threading

logger = logging.getLogger("tegsoft.lookup")

CH_HOST = os.environ.get("CH_HOST", "127.0.0.1")
CH_PORT = int(os.environ.get("CH_PORT", "8123"))
CH_USER = os.environ.get("CH_USER", "default")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "")
CH_DB = os.environ.get("CH_DB", "retention")

_local = threading.local()


class PlayerLookupError(RuntimeError):
    """Не удалось получить телефон игрока."""


class DoNotContactError(PlayerLookupError):
    """Игрок в стоп-листе (do_not_contact) — звонок запрещён."""


def _ch_client():
    """Ленивое thread-local подключение к ClickHouse (по env CH_*).
    Прямое подключение вместо импорта player_board — чтобы не поднимать Flask-приложение."""
    c = getattr(_local, "ch", None)
    if c is None:
        try:
            import clickhouse_connect  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover
            raise PlayerLookupError("clickhouse_connect не установлен") from e
        c = clickhouse_connect.get_client(
            host=CH_HOST, port=CH_PORT, username=CH_USER, password=CH_PASSWORD, database=CH_DB
        )
        _local.ch = c
    return c


def get_player_phone(casino_player_id: int, *, client_factory=_ch_client) -> str:
    """Полный E.164-ish номер игрока для набора провайдером. Уважает do_not_contact.
    `client_factory` инжектируется в тестах."""
    client = client_factory()
    res = client.query(
        """
        SELECT phone, phone_country_code, do_not_contact
        FROM users
        WHERE casino_player_id = {pid:UInt32}
        LIMIT 1
        """,
        parameters={"pid": int(casino_player_id)},
    )
    if not res.result_rows:
        raise PlayerLookupError(f"Игрок {casino_player_id} не найден в users")
    phone, cc, dnc = res.result_rows[0]
    if str(dnc).strip().lower() in ("1", "true", "yes"):
        raise DoNotContactError(f"Игрок {casino_player_id} в стоп-листе (do_not_contact)")
    number = _compose_e164(str(phone or "").strip(), str(cc or "").strip())
    if not number:
        raise PlayerLookupError(f"У игрока {casino_player_id} нет телефона")
    return number


def _compose_e164(phone: str, country_code: str) -> str:
    """Склеить код страны и номер в набираемый вид. Если номер уже с '+' — как есть."""
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if not digits:
        return ""
    if digits.startswith("+"):
        return digits
    cc = "".join(ch for ch in country_code if ch.isdigit())
    if cc and not digits.startswith(cc):
        # ведущий 0 — межгородской (trunk) префикс локального формата; при коде
        # страны его убираем, иначе выйдет +90 0 5xx (ненабираемо). ~19 игроков.
        local = digits.lstrip("0") or digits
        if local.startswith(cc):     # был префикс 00<cc> — номер уже международный
            return f"+{local}"
        return f"+{cc}{local}"
    return f"+{digits}" if cc else digits


def mask_phone(number: str) -> str:
    """`+905551234567` → `+90•••••4567`. Полный номер оператору не показываем
    (анти-увод базы, см. открытый вопрос №5 SPA_BUILD_PLAN.md — маска по умолчанию)."""
    if not number:
        return ""
    digits = number.lstrip("+")
    if len(digits) <= 6:
        return "•" * len(digits)
    prefix = ("+" if number.startswith("+") else "") + digits[:2]
    return f"{prefix}{'•' * 5}{digits[-4:]}"


# ── маппинг оператор ↔ extension ────────────────────────────────────────────────
# TODO(client): боевой источник — таблица-заглушка `crm.operator_extensions(operator_id, tegsoft_ext)`
#   (создаёт A1/B1 при заведении операторов). До неё — env `TEGSOFT_EXT_MAP` (JSON) + default ext.
def _ext_map() -> dict[str, str]:
    raw = os.environ.get("TEGSOFT_EXT_MAP", "").strip()
    if not raw:
        return {}
    try:
        m = json.loads(raw)
        return {str(k): str(v) for k, v in m.items()}
    except (ValueError, AttributeError):
        logger.warning("TEGSOFT_EXT_MAP не JSON — игнорирую")
        return {}


def operator_ext(operator_id: str | None) -> str:
    """extension оператора для originate. Порядок: env-карта → таблица
    crm.operator_extensions (экран «Внутренние номера») → TEGSOFT_DEFAULT_EXT."""
    m = _ext_map()
    if operator_id and operator_id in m:
        return m[operator_id]
    # таблица управляется в CRM (без редеплоя); импорт мягкий — Mock/тесты без psycopg
    if operator_id:
        try:
            from . import store  # noqa: PLC0415
            ext = store.get_operator_ext(operator_id)
            if ext:
                return ext
        except Exception:  # noqa: BLE001 — нет psycopg/БД → падаем на DEFAULT_EXT
            pass
    default = os.environ.get("TEGSOFT_DEFAULT_EXT", "").strip()
    if not default:
        raise PlayerLookupError(
            "Не найден extension оператора: сопоставьте его на экране «Внутренние "
            "номера» (или задайте TEGSOFT_EXT_MAP / TEGSOFT_DEFAULT_EXT)"
        )
    return default


def operator_id_for_ext(ext: str | None) -> str | None:
    """Обратный маппинг ext→operator_id для webhook. None если не найден (API решит fallback)."""
    if not ext:
        return None
    for oid, e in _ext_map().items():
        if e == str(ext):
            return oid
    return None


# ── нормализация исхода звонка (событие Tegsoft → enum crm.call_outcome) ──────────
# enum: 'answered','no_answer','busy','wrong_number'
_OUTCOME_ALIASES = {
    "answered": "answered", "answer": "answered", "connected": "answered", "connect": "answered",
    # Tegsoft-статусы состоявшегося разговора (из доков ECR: агент/клиент положил трубку)
    "completeagent": "answered", "completecaller": "answered", "completehangup": "answered",
    "complete": "answered", "hangup": "answered",
    "no_answer": "no_answer", "noanswer": "no_answer", "ringnoanswer": "no_answer",
    "timeout": "no_answer", "abandon": "no_answer", "missed": "no_answer",
    "offer": "no_answer",   # звонок предложен агенту, но разговор не состоялся
    "busy": "busy", "congestion": "busy",
    "wrong_number": "wrong_number", "wrongnumber": "wrong_number", "invalid": "wrong_number",
    "chanunavail": "wrong_number", "unallocated": "wrong_number",
}
VALID_OUTCOMES = frozenset({"answered", "no_answer", "busy", "wrong_number"})


def normalize_outcome(raw: str | None) -> str:
    """Привести исход из webhook-события к enum. Неизвестное → 'no_answer' (безопасный дефолт)."""
    if not raw:
        return "no_answer"
    key = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    return _OUTCOME_ALIASES.get(key, "no_answer")
