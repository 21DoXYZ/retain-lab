"""materialize_segments.py — пересчёт членства сегментов (Postgres → ClickHouse).

Читает активные (archived_at IS NULL) определения из automation.segments (Supabase),
компилирует каждое через api/segment_compiler в CH-WHERE и наполняет
retention.segment_members. Вызывается из run_loop.sh (шаг 2d) после пересборки
player_features. По образцу load_exports.py (CH-подключение из env).

СТРАТЕГИЯ ПЕРЕЗАПИСИ (задокументировано — план W4-T1): для каждого сегмента
  1) ALTER TABLE ... DELETE WHERE sys_name = X   (mutations_sync=1 — СИНХРОННО)
  2) INSERT INTO ... SELECT <скомпилированный охват>
Таблица маленькая (≤ ~42k игроков × число сегментов), лёгкая мутация быстра.
DELETE-перед-INSERT гарантирует: (а) повторный прогон НЕ дублирует; (б) игроки,
вышедшие из сегмента, исчезают (в отличие от чистого ReplacingMergeTree, который
по ключу (sys_name,id) не удалил бы «пропавшие» строки). В конце — уборка
sys_name, которых больше нет среди активных (архивированные/удалённые сегменты).

ОГРАНИЧЕНИЕ v1: not_segment ссылается на segment_members «как есть на момент
прогона» — если сегмент A исключает сегмент B (ещё не пересчитанный в этом
прогоне), A увидит прошлую материализацию B. Для устойчивости к следующему
прогону всё сходится; критичных цепочек исключений в v1 не предполагается.

Запуск:  .venv/bin/python materialize_segments.py
"""
from __future__ import annotations

import os
import sys
import time

from api.segment_compiler import compile_definition, base_query
from api.segment_fields import JOINS

TABLE = 'retention.segment_members'


def _ch_client():
    import clickhouse_connect
    return clickhouse_connect.get_client(
        host=os.environ.get('CH_HOST', '127.0.0.1'),
        port=int(os.environ.get('CH_PORT', '8123')),
        username=os.environ.get('CH_USER', 'default'),
        password=os.environ.get('CH_PASSWORD', ''),
        database=os.environ.get('CH_DB', 'retention'))


def _active_segments() -> list[dict]:
    dsn = os.environ.get('SUPABASE_DB_URL', '').strip()
    if not dsn:
        raise SystemExit('materialize: SUPABASE_DB_URL не задан — нечего материализовать')
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT sys_name, definition FROM automation.segments "
                    "WHERE archived_at IS NULL ORDER BY sys_name")
        return cur.fetchall()


def _insert_sql(sys_name: str, definition: dict) -> tuple[str, dict]:
    """INSERT ... SELECT для одного сегмента + параметры (значения + sys_name)."""
    where, params, joins = compile_definition(definition)
    base = base_query(where, joins)
    params = {**params, 's': sys_name}
    sql = (f"INSERT INTO {TABLE} (sys_name, casino_player_id) "
           f"SELECT {{s:String}}, casino_player_id FROM ({base})")
    return sql, params


def materialize(client, sys_name: str, definition: dict) -> int:
    # 1) синхронно очищаем прежних участников сегмента
    client.command(f"ALTER TABLE {TABLE} DELETE WHERE sys_name = {{s:String}}",
                   parameters={'s': sys_name}, settings={'mutations_sync': 1})
    # 2) вставляем свежий охват
    sql, params = _insert_sql(sys_name, definition)
    client.command(sql, parameters=params)
    n = client.query(f"SELECT count() FROM {TABLE} WHERE sys_name = {{s:String}}",
                     parameters={'s': sys_name}).result_rows[0][0]
    return int(n)


def cleanup_stale(client, active_names: list[str]) -> None:
    """Удаляем участников сегментов, которых больше нет среди активных."""
    if active_names:
        client.command(f"ALTER TABLE {TABLE} DELETE WHERE sys_name NOT IN {{a:Array(String)}}",
                       parameters={'a': active_names}, settings={'mutations_sync': 1})
    else:
        client.command(f"ALTER TABLE {TABLE} DELETE WHERE 1", settings={'mutations_sync': 1})


def main() -> int:
    t0 = time.time()
    segments = _active_segments()
    if not segments:
        print('materialize: активных сегментов нет — пропуск')
        return 0
    client = _ch_client()
    ok = 0
    for seg in segments:
        sys_name = seg['sys_name']
        try:
            n = materialize(client, sys_name, seg['definition'])
            print(f'materialize: {sys_name:32s} → {n:>7} игроков')
            ok += 1
        except Exception as e:                       # один кривой сегмент не рушит остальные
            print(f'materialize: {sys_name:32s} ОШИБКА — {e}', file=sys.stderr)
    cleanup_stale(client, [s['sys_name'] for s in segments])
    print(f'materialize: готово — {ok}/{len(segments)} сегментов за {time.time() - t0:.1f}с')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
