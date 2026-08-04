"""api/reports_store.py — слой доступа к сохранённым отчётам (Postgres, W5-T3).

Здесь живёт ВЕСЬ SQL для таблицы ``automation.saved_reports`` (миграция 0015):
список видимых пользователю отчётов, CRUD и «дублирование». Ручки (RBAC + форма
ответа) — в api/reports.py; здесь только выборки и запись.

Почему отдельный модуль (а не в api/reports.py):
  • «много маленьких файлов»: чистый компилятор spec→SQL (report_builder.py) и
    исполнитель ClickHouse (reports.py) не смешиваются с Postgres-доступом;
  • браузер сюда не ходит — схема ``automation`` НЕ экспонируется через PostgREST
    (0013/0014/0015), доступ только через Flask с ролевым гейтом.

Правила слоя (зеркало api/call_analysis_store.py):
  • psycopg (v3), подключение ленивое (импорт внутри connect) — модуль грузится
    даже без установленного драйвера, авто-регистрация пакета api не падает;
  • ВСЕ запросы параметризованы (%(name)s) — защита от инъекций;
  • функции возвращают простые dict/list (dict_row), без Flask-объектов;
  • доступ (personal/shared/roles) собирается здесь SQL-ом; ролевой гейт модуля и
    право ставить is_official — в ручке (api/reports.py).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger('api.reports_store')

# Значения crm.user_role (зеркало миграции 0001) — whitelist для visibility='roles'.
# Совпадение с БД проверяется тестом/смоком; при расхождении ручка вернёт 422 на
# неизвестную роль (fail-fast вместо DB-ошибки на вставке в crm.user_role[]).
USER_ROLES: frozenset[str] = frozenset({
    'super_admin', 'director', 'head_retention', 'head_department', 'operator',
    'vip_manager', 'affiliate_manager', 'marketing_manager', 'analyst', 'finance',
    'risk_officer', 'support', 'affiliate', 'viewer',
})

VISIBILITIES: frozenset[str] = frozenset({'personal', 'shared', 'roles'})

# Колонки строки отчёта, отдаваемые наружу (spec включён — нужен UI, чтобы «открыть»).
# roles приводим к text[]: для кастомного enum crm.user_role[] у psycopg нет
# зарегистрированного загрузчика, и массив вернулся бы СТРОКОЙ-литералом ('{analyst}'),
# а не списком. Каст к text[] даёт нативный список Python (['analyst']).
_ROW_COLS = ("r.report_id, r.name, r.spec, r.owner_id, r.visibility, "
             "r.roles::text[] AS roles, r.is_official, r.created_at, r.updated_at, "
             "u.full_name AS owner_name")


class ReportStoreError(RuntimeError):
    """Ошибка доступа к данным сохранённых отчётов (нет DSN / драйвера / сбой запроса)."""


class DuplicateName(ReportStoreError):
    """Нарушение UNIQUE (owner_id, name): у автора уже есть отчёт с таким именем."""


# ════════════════════════════════════════════════════════════════════════════
# Подключение (ленивое, dict_row — как call_analysis_store)
# ════════════════════════════════════════════════════════════════════════════
def _dsn() -> str:
    dsn = os.environ.get('SUPABASE_DB_URL', '').strip()
    if not dsn:
        raise ReportStoreError('SUPABASE_DB_URL не задан — база сохранённых отчётов недоступна')
    return dsn


def connect():
    """Ленивое psycopg-подключение с dict_row. Контекст-менеджер коммитит на выходе."""
    try:
        import psycopg                        # noqa: PLC0415
        from psycopg.rows import dict_row      # noqa: PLC0415
    except ImportError as e:                   # pragma: no cover
        raise ReportStoreError(
            "Драйвер 'psycopg' (v3) не установлен — сохранённые отчёты недоступны "
            "(pip install 'psycopg[binary]')."
        ) from e
    return psycopg.connect(_dsn(), row_factory=dict_row)


def _json(value: Any):
    """Обёртка значения для параметра jsonb-колонки (psycopg Json-адаптер)."""
    from psycopg.types.json import Json        # noqa: PLC0415
    return Json(value)


def _norm_row(row: dict, user_id: str | None) -> dict:
    """Нормализует строку БД в форму ответа: roles/owner_id → str, добавляет mine."""
    out = dict(row)
    out['owner_id'] = str(out['owner_id']) if out.get('owner_id') is not None else None
    out['report_id'] = str(out['report_id']) if out.get('report_id') is not None else None
    out['roles'] = list(out.get('roles') or [])
    out['mine'] = bool(user_id) and out['owner_id'] == str(user_id)
    return out


# ════════════════════════════════════════════════════════════════════════════
# DEV-фолбэк владельца (только API_AUTH_OFF; см. api/reports.py)
# ════════════════════════════════════════════════════════════════════════════
def first_super_admin_id() -> str | None:
    """DEV-ONLY: id первого super_admin из crm.crm_users.

    Нужен ТОЛЬКО для smoke при API_AUTH_OFF: require_auth кладёт sub='dev' (не UUID),
    который не является реальным crm_users.id и не прошёл бы FK owner_id. В проде НЕ
    используется — там sub всегда реальный uuid пользователя (см. _effective_user_id
    в api/reports.py, где фолбэк включается только при _auth_off()).
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM crm.crm_users WHERE role = 'super_admin' "
                    "ORDER BY created_at LIMIT 1")
        row = cur.fetchone()
    return str(row['id']) if row else None


# ════════════════════════════════════════════════════════════════════════════
# Чтение
# ════════════════════════════════════════════════════════════════════════════
def list_visible(user_id: str | None, role: str | None) -> list[dict]:
    """Отчёты, видимые пользователю (user_id роли role):
      • личные владельца (owner_id = user_id);
      • общие (visibility='shared') — все роли с доступом к модулю;
      • по ролям (visibility='roles' AND roles @> [role]).
    Порядок: официальные сверху, затем по свежести (updated_at DESC).
    """
    conds: list[str] = []
    params: dict[str, Any] = {}
    if user_id:
        conds.append('r.owner_id = %(uid)s')
        params['uid'] = user_id
    conds.append("r.visibility = 'shared'")
    if role:
        conds.append("(r.visibility = 'roles' "
                     "AND r.roles @> ARRAY[%(role)s]::crm.user_role[])")
        params['role'] = role
    where = ' OR '.join(conds)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_ROW_COLS} FROM automation.saved_reports r "
            "LEFT JOIN crm.crm_users u ON u.id = r.owner_id "
            f"WHERE {where} "
            "ORDER BY r.is_official DESC, r.updated_at DESC",
            params)
        rows = cur.fetchall()
    return [_norm_row(r, user_id) for r in rows]


def get(report_id: str, user_id: str | None = None) -> dict | None:
    """Одна строка отчёта по id (или None). owner_id/roles нормализованы, mine выставлен."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_ROW_COLS} FROM automation.saved_reports r "
            "LEFT JOIN crm.crm_users u ON u.id = r.owner_id "
            "WHERE r.report_id = %(id)s",
            {'id': report_id})
        row = cur.fetchone()
    return _norm_row(row, user_id) if row else None


def is_visible(row: dict, user_id: str | None, role: str | None) -> bool:
    """Виден ли отчёт `row` пользователю (те же правила, что list_visible) —
    для проверки доступа к duplicate/open на уже прочитанной строке."""
    if not row:
        return False
    if user_id and row.get('owner_id') == str(user_id):
        return True
    vis = row.get('visibility')
    if vis == 'shared':
        return True
    if vis == 'roles' and role:
        return role in (row.get('roles') or [])
    return False


# ════════════════════════════════════════════════════════════════════════════
# Запись
# ════════════════════════════════════════════════════════════════════════════
def create(owner_id: str, name: str, spec: dict, visibility: str,
           roles: list[str], is_official: bool) -> str:
    """Создать отчёт → report_id. UNIQUE(owner_id, name) → DuplicateName."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO automation.saved_reports "
                "(name, spec, owner_id, visibility, roles, is_official) "
                "VALUES (%(name)s, %(spec)s, %(owner)s, %(vis)s, "
                "        %(roles)s::crm.user_role[], %(official)s) "
                "RETURNING report_id",
                {'name': name, 'spec': _json(spec), 'owner': owner_id,
                 'vis': visibility, 'roles': list(roles), 'official': is_official})
            return str(cur.fetchone()['report_id'])
    except Exception as e:                      # noqa: BLE001
        _reraise_unique(e)
        raise


def update(report_id: str, name: str, spec: dict, visibility: str,
           roles: list[str], is_official: bool) -> bool:
    """Полностью обновить отчёт (updated_at=now()). False — если не найден.
    UNIQUE(owner_id, name) при переименовании → DuplicateName.
    Возвращает флаг «нашёлся»; актуальную строку ручка перечитывает через get()."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE automation.saved_reports SET "
                "name = %(name)s, spec = %(spec)s, visibility = %(vis)s, "
                "roles = %(roles)s::crm.user_role[], is_official = %(official)s, "
                "updated_at = now() "
                "WHERE report_id = %(id)s RETURNING report_id",
                {'name': name, 'spec': _json(spec), 'vis': visibility,
                 'roles': list(roles), 'official': is_official, 'id': report_id})
            return cur.fetchone() is not None
    except Exception as e:                      # noqa: BLE001
        _reraise_unique(e)
        raise


def delete(report_id: str) -> bool:
    """Удалить отчёт. True — если строка была."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM automation.saved_reports WHERE report_id = %(id)s "
                    "RETURNING report_id", {'id': report_id})
        return cur.fetchone() is not None


def duplicate(report_id: str, new_owner_id: str) -> str | None:
    """Копия отчёта во владение new_owner_id: имя + « (копия)», visibility=personal,
    is_official=false. None — исходник не найден. Имя разводится суффиксом при
    конфликте UNIQUE(owner_id, name) у нового владельца."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, spec FROM automation.saved_reports "
                    "WHERE report_id = %(id)s", {'id': report_id})
        src = cur.fetchone()
        if not src:
            return None
        new_name = _free_copy_name(cur, new_owner_id, str(src['name']))
        cur.execute(
            "INSERT INTO automation.saved_reports "
            "(name, spec, owner_id, visibility, roles, is_official) "
            "VALUES (%(name)s, %(spec)s, %(owner)s, 'personal', '{}', false) "
            "RETURNING report_id",
            {'name': new_name, 'spec': _json(src['spec']), 'owner': new_owner_id})
        return str(cur.fetchone()['report_id'])


# ════════════════════════════════════════════════════════════════════════════
# Помощники
# ════════════════════════════════════════════════════════════════════════════
def _free_copy_name(cur, owner_id: str, base: str) -> str:
    """Свободное имя копии: «X (копия)», затем «X (копия 2)», … (UNIQUE у владельца)."""
    for i in range(0, 100):
        candidate = f'{base} (копия)' if i == 0 else f'{base} (копия {i + 1})'
        candidate = candidate[:200]
        cur.execute("SELECT 1 FROM automation.saved_reports "
                    "WHERE owner_id = %(owner)s AND name = %(name)s",
                    {'owner': owner_id, 'name': candidate})
        if cur.fetchone() is None:
            return candidate
    # предохранитель: 100 копий одного имени — крайне маловероятно
    return f'{base} (копия {os.urandom(2).hex()})'[:200]


def _reraise_unique(e: Exception) -> None:
    """UniqueViolation (owner_id, name) → DuplicateName; прочее — не трогаем."""
    try:
        import psycopg                          # noqa: PLC0415
    except ImportError:                          # pragma: no cover
        return
    if isinstance(e, psycopg.errors.UniqueViolation):
        raise DuplicateName('Отчёт с таким именем уже есть') from e
