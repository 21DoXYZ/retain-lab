"""Запись звонков в Postgres (`crm.calls`) — приёмник webhook пишет сюда.

Отдельный модуль (не тащим psycopg в adapter): подключение ленивое, чтобы
tegsoft.adapter/MockProvider работали даже без установленного psycopg.

Выбор драйвера: **psycopg (v3)** — актуальный, connection-string дружелюбен к
self-hosted Supabase (`SUPABASE_DB_URL`), контекст-менеджеры коммитят транзакцию,
именованные плейсхолдеры `%(name)s` защищают от SQL-инъекций. (Сверено через Context7.)

`recording_ref` — поле добавляет агент A1 в миграции. Пишем его ТОЛЬКО если колонка
реально есть (интроспекция information_schema); иначе пропускаем с warning — не роняем
вставку (совместимость с параллельной волной 1).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("tegsoft.store")

# кэш наличия опциональной колонки recording_ref (интроспекция один раз на процесс)
_recording_ref_col: bool | None = None


class CrmStoreError(RuntimeError):
    """Ошибка записи звонка в Postgres."""


def _dsn() -> str:
    dsn = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not dsn:
        raise CrmStoreError("SUPABASE_DB_URL не задан — некуда писать crm.calls")
    return dsn


def _connect():
    """Ленивое подключение psycopg (v3). Изолируем импорт, чтобы отсутствие драйвера
    не ломало загрузку adapter/тестов Mock."""
    try:
        import psycopg  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - зависит от окружения
        raise CrmStoreError(
            "Драйвер 'psycopg' (v3) не установлен — запись crm.calls недоступна "
            "(pip install 'psycopg[binary]')."
        ) from e
    return psycopg.connect(_dsn())


def _has_recording_ref(conn) -> bool:
    global _recording_ref_col
    if _recording_ref_col is not None:
        return _recording_ref_col
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'crm' AND table_name = 'calls'
              AND column_name = 'recording_ref'
            """
        )
        _recording_ref_col = cur.fetchone() is not None
    if not _recording_ref_col:
        logger.warning("crm.calls.recording_ref отсутствует — поле пропущено (A1 добавит миграцией)")
    return _recording_ref_col


def reset_schema_cache() -> None:
    """Сбросить кэш интроспекции (после применения миграции A1 / в тестах)."""
    global _recording_ref_col
    _recording_ref_col = None


# ── маппинг оператор → extension (crm.operator_extensions, экран «Внутренние номера») ──
_CALL_ROLES_SQL = ("'operator','vip_manager','head_department','head_retention',"
                   "'affiliate','director','super_admin'")


def list_operator_extensions(*, conn_factory=_connect) -> list[dict]:
    """Активные call-роли из crm_users + их ext, логин и признаки наличия пароля/
    токена (LEFT JOIN). Пароль и токен НАРУЖУ не отдаём — только has_password/has_token."""
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT u.id, u.full_name, u.role::text, e.ext, e.usercode,
                   (e.password IS NOT NULL), (e.token IS NOT NULL), e.updated_at
            FROM crm.crm_users u
            LEFT JOIN crm.operator_extensions e ON e.operator_id = u.id
            WHERE u.is_active AND u.role IN ({_CALL_ROLES_SQL})
            ORDER BY (e.ext IS NULL), u.role::text, u.full_name
            """
        )
        rows = cur.fetchall()
    return [{'operator_id': str(r[0]), 'full_name': r[1], 'role': r[2],
             'ext': r[3], 'usercode': r[4], 'has_password': bool(r[5]),
             'has_token': bool(r[6]),
             'updated_at': r[7].isoformat() if r[7] else None} for r in rows]


def get_operator_ext(operator_id: str, *, conn_factory=_connect) -> str | None:
    """Extension оператора (None если не задан)."""
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT ext FROM crm.operator_extensions WHERE operator_id = %(id)s",
                    {'id': operator_id})
        row = cur.fetchone()
    return row[0] if row else None


def get_operator_creds(operator_id: str, *, conn_factory=_connect) -> dict:
    """Креды оператора для originate от его имени: {usercode, password, token}.
    Секреты — НЕ логировать, наружу (в list) не отдаём."""
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT usercode, password, token FROM crm.operator_extensions "
                    "WHERE operator_id = %(id)s", {'id': operator_id})
        row = cur.fetchone()
    if not row:
        return {'usercode': None, 'password': None, 'token': None}
    return {'usercode': row[0], 'password': row[1], 'token': row[2]}


# обратная совместимость: originate раньше звал get_operator_token
def get_operator_token(operator_id: str, *, conn_factory=_connect) -> str | None:
    return get_operator_creds(operator_id, conn_factory=conn_factory)['token']


def delete_operator_creds(operator_id: str, *, conn_factory=_connect) -> None:
    """Полный сброс кредов оператора (удалить строку) — ext/логин/пароль/токен."""
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM crm.operator_extensions WHERE operator_id = %(id)s",
                    {'id': operator_id})
        conn.commit()


def set_operator_creds(operator_id: str, ext: str | None, usercode: str | None = None,
                       password: str | None = None, token: str | None = None,
                       updated_by: str | None = None, *, conn_factory=_connect) -> None:
    """Upsert кредов. ext/usercode — как есть (пусто → NULL). password/token —
    write-only: непустой → обновить, None/пусто → НЕ трогать (blank = не менять).
    Если в итоге все креды пустые — строку удаляем."""
    ext = (ext or '').strip() or None
    usercode = (usercode or '').strip() or None
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT password, token FROM crm.operator_extensions WHERE operator_id = %(id)s",
                    {'id': operator_id})
        row = cur.fetchone()
        cur_pw, cur_tok = (row[0], row[1]) if row else (None, None)
        new_pw = (password.strip() if password else '') or cur_pw     # blank → сохранить текущий
        new_tok = (token.strip() if token else '') or cur_tok
        if not (ext or usercode or new_pw or new_tok):
            cur.execute("DELETE FROM crm.operator_extensions WHERE operator_id = %(id)s",
                        {'id': operator_id})
        else:
            cur.execute(
                """
                INSERT INTO crm.operator_extensions
                    (operator_id, ext, usercode, password, token, updated_by, updated_at)
                VALUES (%(id)s, %(ext)s, %(uc)s, %(pw)s, %(tok)s, %(by)s, now())
                ON CONFLICT (operator_id) DO UPDATE
                  SET ext = EXCLUDED.ext, usercode = EXCLUDED.usercode,
                      password = EXCLUDED.password, token = EXCLUDED.token,
                      updated_by = EXCLUDED.updated_by, updated_at = now()
                """, {'id': operator_id, 'ext': ext, 'uc': usercode,
                      'pw': new_pw, 'tok': new_tok, 'by': updated_by})
        conn.commit()


def upsert_call(record: dict[str, Any], *, conn_factory=_connect) -> str:
    """Идемпотентно записать/обновить звонок в crm.calls по `provider_ref`.

    `record` — уже провалидированный на слое API dict:
        casino_player_id (int, обяз.), operator_id (uuid-str, обяз.),
        outcome (crm.call_outcome, обяз.), provider_ref (str),
        started_at (ISO|None), duration_sec (int|None),
        result (crm.call_result|None), recording_ref (str|None).

    Один звонок = одно событие может прийти дважды (start/end) → если строка с таким
    provider_ref уже есть, обновляем длительность/исход/запись, иначе вставляем.
    Возвращает id строки (uuid). `conn_factory` инжектируется в тестах.
    """
    provider_ref = record.get("provider_ref")
    cols = {
        "casino_player_id": record["casino_player_id"],
        "operator_id": record["operator_id"],
        "outcome": record["outcome"],
        "result": record.get("result"),
        "provider_ref": provider_ref,
        "started_at": record.get("started_at"),
        "duration_sec": record.get("duration_sec"),
    }
    with conn_factory() as conn:
        include_rec = record.get("recording_ref") is not None and _has_recording_ref(conn)
        if include_rec:
            cols["recording_ref"] = record["recording_ref"]

        with conn.cursor() as cur:
            existing_id = None
            if provider_ref:
                cur.execute(
                    "SELECT id FROM crm.calls WHERE provider_ref = %(provider_ref)s LIMIT 1",
                    {"provider_ref": provider_ref},
                )
                row = cur.fetchone()
                existing_id = row[0] if row else None

            if existing_id is not None:
                # обновляем только пришедшие непустые поля (start-событие не затирает исход end-события)
                sets = ["outcome = %(outcome)s"]
                for f in ("result", "started_at", "duration_sec"):
                    if cols.get(f) is not None:
                        sets.append(f"{f} = %({f})s")
                if include_rec:
                    sets.append("recording_ref = %(recording_ref)s")
                cur.execute(
                    f"UPDATE crm.calls SET {', '.join(sets)} WHERE id = %(id)s RETURNING id",
                    {**cols, "id": existing_id},
                )
                return str(cur.fetchone()[0])

            field_names = [k for k, v in cols.items() if v is not None or k in ("outcome", "casino_player_id", "operator_id")]
            placeholders = ", ".join(f"%({f})s" for f in field_names)
            cur.execute(
                f"INSERT INTO crm.calls ({', '.join(field_names)}) VALUES ({placeholders}) RETURNING id",
                cols,
            )
            return str(cur.fetchone()[0])


def fetch_call(call_id: str, *, conn_factory=_connect) -> dict | None:
    """Прочитать звонок по id: refs для стрима записи + владелец (для аудита/проверок).
    Возвращает {provider_ref, recording_ref, casino_player_id, operator_id} или None."""
    with conn_factory() as conn:
        has_rec = _has_recording_ref(conn)
        rec_col = "recording_ref" if has_rec else "NULL AS recording_ref"
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT provider_ref, {rec_col}, casino_player_id, operator_id
                    FROM crm.calls WHERE id = %(id)s LIMIT 1""",
                {"id": call_id},
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "provider_ref": row[0],
                "recording_ref": row[1],
                "casino_player_id": row[2],
                "operator_id": str(row[3]) if row[3] is not None else None,
            }


def lookup_originate(provider_ref: str, *, conn_factory=_connect) -> dict | None:
    """Восстановить связку (casino_player_id, operator_id) по `provider_ref`.

    Боевой Tegsoft-ECR по завершении звонка обычно присылает только CALLID звонка
    (= provider_ref), исход и длительность — БЕЗ нашего casino_player_id. Но при
    инициации звонка `api/calls.py:originate()` уже записал в crm.audit_log событие
    `call_originate` с entity_id=casino_player_id, actor_id=operator_id и
    meta.provider_ref=CALLID. Отсюда и берём связку — сквозная фиксация звонка
    работает независимо от того, умеет ли их ECR подставлять наши id в webhook.

    Возвращает {'casino_player_id': int|None, 'operator_id': str|None} или None.
    """
    if not provider_ref:
        return None
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT actor_id, entity_id FROM crm.audit_log
               WHERE action = 'call_originate'
                 AND meta->>'provider_ref' = %(ref)s
               ORDER BY created_at DESC LIMIT 1""",
            {"ref": provider_ref},
        )
        row = cur.fetchone()
    if not row:
        return None
    operator_id, entity_id = row[0], row[1]
    try:
        casino_player_id = int(entity_id) if entity_id is not None else None
    except (TypeError, ValueError):
        casino_player_id = None
    return {
        "casino_player_id": casino_player_id,
        "operator_id": str(operator_id) if operator_id is not None else None,
    }


def write_audit(actor_id: str | None, action: str, entity: str, entity_id: str | None,
                meta: dict | None = None, *, conn_factory=_connect) -> None:
    """Запись действия в crm.audit_log (каждое действие — в аудит, раздел 0 п.5).
    Best-effort: сбой аудита не должен ронять основную операцию."""
    try:
        import json  # noqa: PLC0415
        with conn_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO crm.audit_log (actor_id, action, entity, entity_id, meta)
                   VALUES (%(actor_id)s, %(action)s, %(entity)s, %(entity_id)s, %(meta)s)""",
                {
                    "actor_id": actor_id,
                    "action": action,
                    "entity": entity,
                    "entity_id": entity_id,
                    "meta": json.dumps(meta or {}),
                },
            )
    except Exception as e:  # noqa: BLE001 - аудит не критичен для операции
        logger.warning("audit_log write failed (%s %s): %s", action, entity_id, e)
