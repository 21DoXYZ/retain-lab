"""api/chains_store.py — слой доступа к данным цепочек автоматизации (Postgres).

Здесь живёт ВЕСЬ SQL модуля «Цепочки» (схема ``automation``, миграция 0014):
цепочки, версии definition, enrollments (членство игроков), шаблоны сообщений.
Ручки (RBAC + валидатор definition + форма ответа) — в api/chains.py.

Почему отдельный модуль (как call_analysis_store):
  • «много маленьких файлов»: SQL отделён от ручек;
  • схема ``automation`` НЕ экспонируется через PostgREST (0014) — доступ только
    через Flask с ролевым гейтом; браузер сюда не ходит.

Правила слоя (зеркалят call_analysis_store):
  • psycopg (v3), подключение ленивое (импорт внутри connect) — модуль грузится
    даже без установленного драйвера, авто-регистрация пакета api не падает;
  • ВСЕ запросы параметризованы (%(name)s) — защита от инъекций;
  • функции возвращают простые dict/list (dict_row), без Flask-объектов;
  • UUID-колонки отдаём как ::text (json.dumps не умеет uuid.UUID);
  • версионирование: активная версия «заморожена» — активные enrollments доходят
    по своей version_id; правка активной цепочки создаёт НОВУЮ версию (ТЗ §2.5).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger('api.chains_store')


class ChainsStoreError(RuntimeError):
    """Ошибка доступа к данным цепочек (нет DSN / драйвера / сбой запроса)."""


# ════════════════════════════════════════════════════════════════════════════
# Подключение
# ════════════════════════════════════════════════════════════════════════════
def _dsn() -> str:
    dsn = os.environ.get('SUPABASE_DB_URL', '').strip()
    if not dsn:
        raise ChainsStoreError('SUPABASE_DB_URL не задан — база цепочек недоступна')
    return dsn


def connect():
    """Ленивое psycopg-подключение с dict_row. Контекст-менеджер коммитит на выходе."""
    try:
        import psycopg                        # noqa: PLC0415
        from psycopg.rows import dict_row      # noqa: PLC0415
    except ImportError as e:                   # pragma: no cover
        raise ChainsStoreError(
            "Драйвер 'psycopg' (v3) не установлен — доступ к цепочкам недоступен "
            "(pip install 'psycopg[binary]')."
        ) from e
    return psycopg.connect(_dsn(), row_factory=dict_row)


def _json(value: Any):
    """Обёртка значения для параметра jsonb-колонки (psycopg Json-адаптер)."""
    from psycopg.types.json import Json        # noqa: PLC0415
    return Json(value)


# ════════════════════════════════════════════════════════════════════════════
# Цепочки: список / чтение / создание / правка шапки
# ════════════════════════════════════════════════════════════════════════════
def list_chains() -> list[dict]:
    """Список цепочек со статусами, числом версий, активной версией и живыми enrollments."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.chain_id::text AS chain_id, c.name, c.description, c.status, "
            "c.created_at, c.updated_at, c.activated_at, "
            "(SELECT count(*) FROM automation.chain_versions v "
            "   WHERE v.chain_id = c.chain_id) AS versions_count, "
            "(SELECT max(version_no) FROM automation.chain_versions v "
            "   WHERE v.chain_id = c.chain_id AND v.activated_at IS NOT NULL) AS active_version_no, "
            "EXISTS (SELECT 1 FROM automation.chain_versions v "
            "        WHERE v.chain_id = c.chain_id AND v.activated_at IS NULL) AS has_draft, "
            "(SELECT count(*) FROM automation.chain_enrollments e "
            "   WHERE e.chain_id = c.chain_id AND e.state = 'active') AS active_enrollments "
            "FROM automation.chains c ORDER BY c.created_at DESC")
        return cur.fetchall()


def get_chain(chain_id: str, with_versions: bool = True) -> dict | None:
    """Одна цепочка. with_versions → добавляет список версий (version_no, activated_at, definition)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT chain_id::text AS chain_id, name, description, status, "
            "created_by::text AS created_by, created_at, updated_at, activated_at, archived_at "
            "FROM automation.chains WHERE chain_id = %(id)s",
            {'id': chain_id})
        chain = cur.fetchone()
        if chain is None:
            return None
        if with_versions:
            cur.execute(
                "SELECT version_id::text AS version_id, version_no, definition, "
                "created_at, activated_at FROM automation.chain_versions "
                "WHERE chain_id = %(id)s ORDER BY version_no",
                {'id': chain_id})
            chain['versions'] = cur.fetchall()
    return chain


def create_chain(name: str, description: str, created_by: str | None) -> str | None:
    """Создать цепочку-черновик. None = имя занято (UNIQUE)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO automation.chains (name, description, created_by) "
            "VALUES (%(n)s, %(d)s, %(by)s) "
            "ON CONFLICT (name) DO NOTHING RETURNING chain_id::text AS chain_id",
            {'n': name, 'd': description, 'by': created_by})
        row = cur.fetchone()
    return row['chain_id'] if row else None


def update_chain(chain_id: str, name: str | None, description: str | None) -> str | None:
    """Правка имени/описания. Возвращает 'not_found' | 'not_draft' | 'name_taken' | None (успех).

    Меняется только у draft (шапка активной цепочки не редактируется — ТЗ §2.5).
    """
    sets, params = [], {'id': chain_id}
    if name is not None:
        sets.append('name = %(n)s')
        params['n'] = name
    if description is not None:
        sets.append('description = %(d)s')
        params['d'] = description
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM automation.chains WHERE chain_id = %(id)s", {'id': chain_id})
        row = cur.fetchone()
        if row is None:
            return 'not_found'
        if row['status'] != 'draft':
            return 'not_draft'
        if not sets:
            return None
        sets.append('updated_at = now()')
        try:
            cur.execute(f"UPDATE automation.chains SET {', '.join(sets)} WHERE chain_id = %(id)s",
                        params)
        except Exception:                     # UniqueViolation — имя занято
            conn.rollback()
            return 'name_taken'
    return None


# ════════════════════════════════════════════════════════════════════════════
# Версии definition: сохранение черновика / ввод в бой / чтение активной
# ════════════════════════════════════════════════════════════════════════════
def _latest_draft(cur, chain_id: str) -> dict | None:
    """Последняя версия-черновик (activated_at IS NULL)."""
    cur.execute(
        "SELECT version_id::text AS version_id, version_no FROM automation.chain_versions "
        "WHERE chain_id = %(id)s AND activated_at IS NULL ORDER BY version_no DESC LIMIT 1",
        {'id': chain_id})
    return cur.fetchone()


def save_definition(chain_id: str, definition: dict, created_by: str | None) -> dict | str | None:
    """Сохранить черновик definition. Обновляет существующий черновик ЛИБО создаёт
    новую версию version_no = max+1 (правка активной цепочки = новая версия).

    Возвращает {'version_id', 'version_no', 'created'} | 'not_found' | 'archived'.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM automation.chains WHERE chain_id = %(id)s", {'id': chain_id})
        row = cur.fetchone()
        if row is None:
            return 'not_found'
        if row['status'] == 'archived':
            return 'archived'
        draft = _latest_draft(cur, chain_id)
        if draft:
            cur.execute(
                "UPDATE automation.chain_versions SET definition = %(def)s, created_at = now(), "
                "created_by = %(by)s WHERE version_id = %(vid)s",
                {'def': _json(definition), 'by': created_by, 'vid': draft['version_id']})
            version_id, version_no, created = draft['version_id'], draft['version_no'], False
        else:
            cur.execute("SELECT COALESCE(max(version_no), 0) + 1 AS n "
                        "FROM automation.chain_versions WHERE chain_id = %(id)s", {'id': chain_id})
            version_no = int(cur.fetchone()['n'])
            cur.execute(
                "INSERT INTO automation.chain_versions (chain_id, version_no, definition, created_by) "
                "VALUES (%(id)s, %(vn)s, %(def)s, %(by)s) RETURNING version_id::text AS version_id",
                {'id': chain_id, 'vn': version_no, 'def': _json(definition), 'by': created_by})
            version_id, created = cur.fetchone()['version_id'], True
        cur.execute("UPDATE automation.chains SET updated_at = now() WHERE chain_id = %(id)s",
                    {'id': chain_id})
    return {'version_id': version_id, 'version_no': version_no, 'created': created}


def activate(chain_id: str) -> dict | str | None:
    """Ввести цепочку в бой. Черновик → активная версия (activated_at + статус active);
    старые версии НЕ трогаются (активные enrollments доходят по своей version_id).
    Пауза без черновика → просто возобновление (resume).

    Возвращает {'version_no', 'resumed'} | 'not_found' | 'no_draft'.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM automation.chains WHERE chain_id = %(id)s", {'id': chain_id})
        row = cur.fetchone()
        if row is None:
            return 'not_found'
        draft = _latest_draft(cur, chain_id)
        if draft:
            cur.execute("UPDATE automation.chain_versions SET activated_at = now() "
                        "WHERE version_id = %(vid)s", {'vid': draft['version_id']})
            cur.execute("UPDATE automation.chains SET status = 'active', activated_at = now(), "
                        "updated_at = now() WHERE chain_id = %(id)s", {'id': chain_id})
            return {'version_no': int(draft['version_no']), 'resumed': False}
        # черновика нет: возобновляем паузу, иначе активировать нечего
        if row['status'] == 'paused':
            cur.execute("UPDATE automation.chains SET status = 'active', updated_at = now() "
                        "WHERE chain_id = %(id)s", {'id': chain_id})
            cur.execute("SELECT max(version_no) AS n FROM automation.chain_versions "
                        "WHERE chain_id = %(id)s AND activated_at IS NOT NULL", {'id': chain_id})
            n = cur.fetchone()['n']
            return {'version_no': int(n) if n is not None else None, 'resumed': True}
        return 'no_draft'


def pause(chain_id: str) -> str | None:
    """Пауза активной цепочки. 'not_found' | 'not_active' | None (успех)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM automation.chains WHERE chain_id = %(id)s", {'id': chain_id})
        row = cur.fetchone()
        if row is None:
            return 'not_found'
        if row['status'] != 'active':
            return 'not_active'
        cur.execute("UPDATE automation.chains SET status = 'paused', updated_at = now() "
                    "WHERE chain_id = %(id)s", {'id': chain_id})
    return None


def archive(chain_id: str) -> str | None:
    """В архив (из любого статуса). 'not_found' | 'already' | None (успех)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM automation.chains WHERE chain_id = %(id)s", {'id': chain_id})
        row = cur.fetchone()
        if row is None:
            return 'not_found'
        if row['status'] == 'archived':
            return 'already'
        cur.execute("UPDATE automation.chains SET status = 'archived', archived_at = now(), "
                    "updated_at = now() WHERE chain_id = %(id)s", {'id': chain_id})
    return None


def clone(chain_id: str, new_name: str, created_by: str | None) -> str | None:
    """Копия последней версии definition в НОВУЮ цепочку-черновик.
    'src_not_found' | 'no_version' | 'name_taken' | <new chain_id> (успех)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT description FROM automation.chains WHERE chain_id = %(id)s",
                    {'id': chain_id})
        src = cur.fetchone()
        if src is None:
            return 'src_not_found'
        cur.execute("SELECT definition FROM automation.chain_versions "
                    "WHERE chain_id = %(id)s ORDER BY version_no DESC LIMIT 1", {'id': chain_id})
        ver = cur.fetchone()
        if ver is None:
            return 'no_version'
        cur.execute(
            "INSERT INTO automation.chains (name, description, created_by) "
            "VALUES (%(n)s, %(d)s, %(by)s) "
            "ON CONFLICT (name) DO NOTHING RETURNING chain_id::text AS chain_id",
            {'n': new_name, 'd': src['description'], 'by': created_by})
        row = cur.fetchone()
        if row is None:
            return 'name_taken'
        new_id = row['chain_id']
        cur.execute(
            "INSERT INTO automation.chain_versions (chain_id, version_no, definition, created_by) "
            "VALUES (%(id)s, 1, %(def)s, %(by)s)",
            {'id': new_id, 'def': _json(ver['definition']), 'by': created_by})
    return new_id


# ════════════════════════════════════════════════════════════════════════════
# Шаблоны сообщений (CRUD)
# ════════════════════════════════════════════════════════════════════════════
def list_templates() -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT template_id::text AS template_id, name, channel_kind, texts, "
            "created_at, updated_at FROM automation.templates ORDER BY name")
        return cur.fetchall()


def get_template(template_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT template_id::text AS template_id, name, channel_kind, texts, "
            "created_at, updated_at FROM automation.templates WHERE template_id = %(id)s",
            {'id': template_id})
        return cur.fetchone()


def create_template(name: str, channel_kind: str, texts: dict,
                    created_by: str | None) -> str | None:
    """Создать шаблон. None = имя занято."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO automation.templates (name, channel_kind, texts, created_by) "
            "VALUES (%(n)s, %(ck)s, %(t)s, %(by)s) "
            "ON CONFLICT (name) DO NOTHING RETURNING template_id::text AS template_id",
            {'n': name, 'ck': channel_kind, 't': _json(texts), 'by': created_by})
        row = cur.fetchone()
    return row['template_id'] if row else None


def update_template(template_id: str, name: str | None, channel_kind: str | None,
                    texts: dict | None) -> str | None:
    """Частичное обновление. 'not_found' | 'name_taken' | None (успех)."""
    sets, params = [], {'id': template_id}
    if name is not None:
        sets.append('name = %(n)s')
        params['n'] = name
    if channel_kind is not None:
        sets.append('channel_kind = %(ck)s')
        params['ck'] = channel_kind
    if texts is not None:
        sets.append('texts = %(t)s')
        params['t'] = _json(texts)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM automation.templates WHERE template_id = %(id)s",
                    {'id': template_id})
        if cur.fetchone() is None:
            return 'not_found'
        if not sets:
            return None
        sets.append('updated_at = now()')
        try:
            cur.execute(f"UPDATE automation.templates SET {', '.join(sets)} "
                        "WHERE template_id = %(id)s", params)
        except Exception:                     # UniqueViolation — имя занято
            conn.rollback()
            return 'name_taken'
    return None


def delete_template(template_id: str) -> bool:
    """Удалить шаблон. True, если строка найдена и удалена."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM automation.templates WHERE template_id = %(id)s "
                    "RETURNING template_id", {'id': template_id})
        return cur.fetchone() is not None
