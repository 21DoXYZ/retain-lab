"""chains/store.py — лёгкий psycopg-слой к automation.* ДЛЯ runner-а.

Отдельный от api/chains_store.py намеренно: тот заточен под Flask-ручки (короткие
транзакции per-request, форма ответа). Здесь — долгоживущий сервис: одно
переиспользуемое соединение с авто-переподключением, батч-вставки enrollments,
выборка «кого будить», продвижение состояния. Схема automation НЕ в PostgREST —
ходим под postgres напрямую (как materialize_segments.py).

Всё параметризовано (%(name)s). Время wake считаем в Python в явном UTC и кладём
tz-aware timestamptz — сравнение next_wake_at <= now() в Postgres корректно при
любом server tz (гочи Asia/Makassar: никаких наивных локальных дат).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterable

# Postgres лимит параметров на запрос — 65535; режем батч enrollments с запасом.
_INSERT_CHUNK = 4000


class Store:
    """Обёртка над одним psycopg-соединением с ленивым (пере)подключением."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = (dsn or os.environ.get('SUPABASE_DB_URL', '')).strip()
        self._conn = None

    def _c(self):
        if not self._dsn:
            raise RuntimeError('SUPABASE_DB_URL не задан — база цепочек недоступна')
        if self._conn is None or self._conn.closed:
            import psycopg
            from psycopg.rows import dict_row
            self._conn = psycopg.connect(self._dsn, row_factory=dict_row, autocommit=True)
        return self._conn

    def reset(self) -> None:
        """Уронить соединение (после ошибки тика) — следующий вызов переподключится."""
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    # ── цепочки в бою ─────────────────────────────────────────────────────────
    def active_chains(self) -> list[dict]:
        """Активные цепочки со СВЕЖЕЙ активированной версией (definition замороженной)."""
        with self._c().cursor() as cur:
            cur.execute(
                "SELECT c.chain_id::text AS chain_id, c.name, "
                "       v.version_id::text AS version_id, v.version_no, v.definition "
                "FROM automation.chains c "
                "JOIN LATERAL ("
                "   SELECT version_id, version_no, definition "
                "   FROM automation.chain_versions "
                "   WHERE chain_id = c.chain_id AND activated_at IS NOT NULL "
                "   ORDER BY version_no DESC LIMIT 1) v ON true "
                "WHERE c.status = 'active'")
            return cur.fetchall()

    # ── вход в цепочку ────────────────────────────────────────────────────────
    def enrolled_recently(self, chain_id: str, reentry_days: int) -> set[int]:
        """Игроки, кого нельзя заводить снова: активные ИЛИ вошедшие < reentry_days назад."""
        with self._c().cursor() as cur:
            cur.execute(
                "SELECT DISTINCT casino_player_id FROM automation.chain_enrollments "
                "WHERE chain_id = %(id)s AND (state = 'active' "
                "   OR entered_at > now() - make_interval(days => %(r)s))",
                {'id': chain_id, 'r': int(reentry_days)})
            return {int(r['casino_player_id']) for r in cur.fetchall()}

    def insert_enrollments(self, chain_id: str, version_id: str, first_node: str,
                           rows: list[tuple[int, str]]) -> list[tuple[int, str]]:
        """Батч-вставка enrollments (чанками). rows = [(player_id, ab_group)].

        Возвращает реально вставленные (pid, ab_group) — с учётом анти-дубль индекса
        (гонка: кто-то уже активен → ON CONFLICT DO NOTHING). По ним runner пишет
        chain_events 'enter'.
        """
        inserted: list[tuple[int, str]] = []
        conn = self._c()
        for i in range(0, len(rows), _INSERT_CHUNK):
            chunk = rows[i:i + _INSERT_CHUNK]
            params: dict[str, Any] = {'chain': chain_id, 'ver': version_id, 'node': first_node}
            values = []
            for j, (pid, ab) in enumerate(chunk):
                values.append(f"(%(chain)s, %(ver)s, %(pid{j})s, %(node)s, %(ab{j})s)")
                params[f'pid{j}'] = int(pid)
                params[f'ab{j}'] = ab
            sql = ("INSERT INTO automation.chain_enrollments "
                   "(chain_id, version_id, casino_player_id, current_node, ab_group) VALUES "
                   + ", ".join(values) +
                   " ON CONFLICT (chain_id, casino_player_id) WHERE state = 'active' "
                   "DO NOTHING RETURNING casino_player_id, ab_group")
            with conn.cursor() as cur:
                cur.execute(sql, params)
                inserted.extend((int(r['casino_player_id']), r['ab_group']) for r in cur.fetchall())
        return inserted

    # ── продвижение ───────────────────────────────────────────────────────────
    def due_enrollments(self, limit: int) -> list[dict]:
        """Активные enrollments, кого пора будить (next_wake_at пуст или наступил),
        только у активных цепочек (пауза замораживает прогон). С definition версии."""
        with self._c().cursor() as cur:
            cur.execute(
                "SELECT e.enrollment_id::text AS enrollment_id, e.chain_id::text AS chain_id, "
                "       e.casino_player_id, e.current_node, e.ab_group, e.entered_at, "
                "       e.next_wake_at, v.version_no, v.definition "
                "FROM automation.chain_enrollments e "
                "JOIN automation.chain_versions v ON v.version_id = e.version_id "
                "JOIN automation.chains c ON c.chain_id = e.chain_id "
                "WHERE e.state = 'active' AND c.status = 'active' "
                "  AND (e.next_wake_at IS NULL OR e.next_wake_at <= now()) "
                "ORDER BY e.next_wake_at NULLS FIRST LIMIT %(lim)s",
                {'lim': int(limit)})
            return cur.fetchall()

    def update_enrollment(self, enrollment_id: str, current_node: str, state: str,
                          wake_at: datetime | None, exit_reason: str | None) -> None:
        """Записать новое состояние enrollment. wake_at — tz-aware UTC (или None)."""
        with self._c().cursor() as cur:
            cur.execute(
                "UPDATE automation.chain_enrollments SET "
                "  current_node = %(node)s, state = %(state)s, next_wake_at = %(wake)s, "
                "  exited_at = CASE WHEN %(state)s IN ('done','converted','exited') "
                "                   THEN now() ELSE exited_at END, "
                "  exit_reason = COALESCE(%(reason)s, exit_reason) "
                "WHERE enrollment_id = %(id)s",
                {'node': current_node, 'state': state, 'wake': wake_at,
                 'reason': exit_reason, 'id': enrollment_id})

    # ── шаблоны сообщений (кэш на тик) ────────────────────────────────────────
    def templates(self) -> dict[str, dict]:
        """Все шаблоны по template_id (для рендера send_message). texts — jsonb→dict."""
        with self._c().cursor() as cur:
            cur.execute(
                "SELECT template_id::text AS template_id, name, channel_kind, texts "
                "FROM automation.templates")
            return {r['template_id']: r for r in cur.fetchall()}

    # ── действие desk_task: задача менеджеру в Пульт ──────────────────────────
    def add_assignment(self, player_id: int, operator_id: str) -> bool:
        """INSERT в crm.player_assignments (статус по умолчанию 'not_touched').
        ON CONFLICT (player, operator) DO NOTHING. True — если строка создана."""
        with self._c().cursor() as cur:
            cur.execute(
                "INSERT INTO crm.player_assignments "
                "  (casino_player_id, operator_id, assigned_by, status) "
                "VALUES (%(pid)s, %(op)s, NULL, 'not_touched') "
                "ON CONFLICT (casino_player_id, operator_id) DO NOTHING "
                "RETURNING id",
                {'pid': int(player_id), 'op': operator_id})
            return cur.fetchone() is not None
