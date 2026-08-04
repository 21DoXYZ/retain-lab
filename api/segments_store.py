"""api/segments_store.py — слой доступа к определениям сегментов (Postgres).

Весь SQL схемы ``automation.segments`` (миграция 0013) живёт здесь. Ручки
(api/segments.py) держат RBAC и форму ответа, компиляция definition — в
api/segment_compiler.py; SQL — только тут. Приём 1-в-1 с api/call_analysis_store.py:
  • psycopg (v3), ленивый импорт внутри connect (пакет грузится без драйвера);
  • ВСЕ запросы параметризованы (%(name)s);
  • функции возвращают простые dict/list (dict_row);
  • схема automation НЕ экспонируется через PostgREST (0013) — гейт в Flask.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger('api.segments_store')

_UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                      r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

_COLS = ("segment_id, name, sys_name, description, definition, is_trigger, "
         "schedule_at, created_by, created_at, updated_at, archived_at")


class SegmentStoreError(RuntimeError):
    """Ошибка доступа к определениям сегментов (нет DSN / драйвера / сбой запроса)."""


def _dsn() -> str:
    dsn = os.environ.get('SUPABASE_DB_URL', '').strip()
    if not dsn:
        raise SegmentStoreError('SUPABASE_DB_URL не задан — база сегментов недоступна')
    return dsn


def connect():
    """Ленивое psycopg-подключение с dict_row (контекст-менеджер коммитит на выходе)."""
    try:
        import psycopg                       # noqa: PLC0415
        from psycopg.rows import dict_row     # noqa: PLC0415
    except ImportError as e:                  # pragma: no cover
        raise SegmentStoreError(
            "Драйвер 'psycopg' (v3) не установлен (pip install 'psycopg[binary]').") from e
    return psycopg.connect(_dsn(), row_factory=dict_row)


def _json(value: Any):
    from psycopg.types.json import Json       # noqa: PLC0415
    return Json(value)


def _coerce_creator(user_id: str | None) -> str | None:
    """created_by кладём только если это валидный UUID (в dev sub='dev' → NULL,
    иначе нарушение FK на crm.crm_users)."""
    return user_id if (user_id and _UUID_RE.match(str(user_id))) else None


# ── чтение ────────────────────────────────────────────────────────────────────
def list_segments(include_archived: bool = False) -> list[dict]:
    where = '' if include_archived else ' WHERE archived_at IS NULL'
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLS} FROM automation.segments{where} "
                    "ORDER BY archived_at IS NOT NULL, created_at DESC")
        return cur.fetchall()


def get_segment(segment_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLS} FROM automation.segments WHERE segment_id = %(id)s",
                    {'id': segment_id})
        return cur.fetchone()


def get_by_sys_name(sys_name: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLS} FROM automation.segments WHERE sys_name = %(s)s",
                    {'s': sys_name})
        return cur.fetchone()


def active_for_materialize() -> list[dict]:
    """sys_name + definition активных (не архивных) сегментов — для materialize_segments."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT sys_name, definition FROM automation.segments "
                    "WHERE archived_at IS NULL ORDER BY sys_name")
        return cur.fetchall()


# ── запись ────────────────────────────────────────────────────────────────────
def create_segment(name: str, sys_name: str, description: str, definition: dict,
                    is_trigger: bool, schedule_at: str, created_by: str | None) -> dict:
    """Новый сегмент. UniqueViolation по sys_name пробрасываем как SegmentStoreError."""
    with connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO automation.segments "
                "(name, sys_name, description, definition, is_trigger, schedule_at, created_by) "
                "VALUES (%(name)s, %(sys)s, %(desc)s, %(def)s, %(trig)s, %(sched)s, %(by)s) "
                f"RETURNING {_COLS}",
                {'name': name, 'sys': sys_name, 'desc': description, 'def': _json(definition),
                 'trig': is_trigger, 'sched': schedule_at, 'by': _coerce_creator(created_by)})
            return cur.fetchone()
        except Exception as e:                # UniqueViolation / CheckViolation → человекочитаемо
            conn.rollback()
            raise SegmentStoreError(_pg_reason(e, sys_name)) from e


def update_segment(segment_id: str, *, name=None, description=None, definition=None,
                   is_trigger=None, schedule_at=None) -> dict | None:
    """Точечное обновление (меняет только переданные поля). None-поля не трогаем."""
    sets, params = [], {'id': segment_id}
    if name is not None:
        sets.append('name = %(name)s'); params['name'] = name
    if description is not None:
        sets.append('description = %(desc)s'); params['desc'] = description
    if definition is not None:
        sets.append('definition = %(def)s'); params['def'] = _json(definition)
    if is_trigger is not None:
        sets.append('is_trigger = %(trig)s'); params['trig'] = is_trigger
    if schedule_at is not None:
        sets.append('schedule_at = %(sched)s'); params['sched'] = schedule_at
    if not sets:
        return get_segment(segment_id)
    sets.append('updated_at = now()')
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE automation.segments SET {', '.join(sets)} "
                    f"WHERE segment_id = %(id)s RETURNING {_COLS}", params)
        return cur.fetchone()


def archive_segment(segment_id: str) -> dict | None:
    """Архив (не удаление — история и материализация чистятся отдельно)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE automation.segments SET archived_at = now(), updated_at = now() "
                    f"WHERE segment_id = %(id)s AND archived_at IS NULL RETURNING {_COLS}",
                    {'id': segment_id})
        return cur.fetchone()


def clone_segment(segment_id: str, new_name: str, new_sys_name: str,
                  created_by: str | None) -> dict | None:
    """Копия определения под новым именем/sys_name. None — исходник не найден."""
    src = get_segment(segment_id)
    if src is None:
        return None
    return create_segment(new_name, new_sys_name, src['description'], src['definition'],
                          bool(src['is_trigger']), str(src['schedule_at']), created_by)


def _pg_reason(exc: Exception, sys_name: str) -> str:
    msg = str(exc).lower()
    if 'unique' in msg or 'duplicate' in msg:
        return f"Системное имя '{sys_name}' уже занято"
    if 'check' in msg and 'sys_name' in msg:
        return (f"Недопустимое системное имя '{sys_name}' "
                "(латиница, цифры, _; начинается с буквы; 3–64 символа)")
    return f"Не удалось сохранить сегмент: {exc}"
