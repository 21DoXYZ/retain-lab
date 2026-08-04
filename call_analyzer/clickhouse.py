"""ClickHouse: аналитический приёмник аудитов (dev spec §4.2).

Таблица call_audits_flat — append-only витрина по операторам. DDL создаётся при
старте воркера (CREATE TABLE IF NOT EXISTS), запись — после шага score. Клиент
живёт на серверах казино; тут — только DDL и writer. clickhouse_connect тянем
лениво. Нет CH в окружении (CH_HOST пуст) → запись best-effort пропускается:
сбой аналитики НЕ должен ронять пайплайн (dev spec §7).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from call_analyzer.scoring import CRITERIA

logger = logging.getLogger("call_analyzer.clickhouse")

_TABLE = "call_audits_flat"
# score_open_identify … score_tone — по одному столбцу на критерий (dev spec §4.2)
_SCORE_COLS = [f"score_{c}" for c in CRITERIA]


class CHError(RuntimeError):
    """Ошибка записи в ClickHouse (best-effort — не терминальна для звонка)."""


def ddl(database: str = "retention") -> str:
    """CREATE TABLE IF NOT EXISTS call_audits_flat (dev spec §4.2)."""
    score_defs = ",\n  ".join(f"{c} Nullable(Int8)" for c in _SCORE_COLS)
    return f"""CREATE TABLE IF NOT EXISTS {database}.{_TABLE} (
  call_id String,
  operator_id String,
  casino_id String,
  created_at DateTime,
  duration_s Nullable(Int32),
  overall_score_100 Nullable(Int32),
  pass_fail LowCardinality(String),
  {score_defs},
  offer_outcome LowCardinality(String),
  top_objection LowCardinality(String),
  audit_json String
) ENGINE = MergeTree
ORDER BY (operator_id, created_at)
PARTITION BY toYYYYMM(created_at)"""


def get_client():
    """clickhouse_connect по env CH_HOST/CH_PORT/CH_USER/CH_PASSWORD (база retention).

    CH_HOST не задан → None (CH необязателен в dev). Ошибку соединения пробрасываем.
    """
    host = os.environ.get("CH_HOST", "").strip()
    if not host:
        return None
    try:
        import clickhouse_connect  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise CHError("пакет 'clickhouse_connect' не установлен") from e
    return clickhouse_connect.get_client(
        host=host,
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )


def ensure_schema(client=None, database: str | None = None) -> None:
    """Создать таблицу, если её нет (старт воркера). Нет клиента → тихо выходим."""
    client = client or get_client()
    if client is None:
        logger.info("CH_HOST не задан — DDL call_audits_flat пропущен")
        return
    client.command(ddl(database or os.environ.get("CH_DB", "retention")))


def _top_objection(objections: list[dict]) -> str:
    """Самый частый тип возражения в звонке (для быстрой аналитики §4.2)."""
    if not objections:
        return ""
    counts: dict[str, int] = {}
    for o in objections:
        t = o.get("type")
        if t:
            counts[t] = counts.get(t, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def write_audit_flat(row: dict, *, client=None) -> bool:
    """Записать один аудит в call_audits_flat. best-effort: сбой логируем, не бросаем.

    row: call_id, operator_id, casino_id, created_at(datetime|None), duration_s,
         overall_score_100, pass_fail, dimensions[], objections[], offer_outcome,
         audit_json(str).
    """
    client = client or get_client()
    if client is None:
        return False
    try:
        scores = {f"score_{d.get('name')}": d.get("score")
                  for d in row.get("dimensions", []) if d.get("name") in CRITERIA}
        created = row.get("created_at") or datetime.now(timezone.utc)
        if isinstance(created, datetime) and created.tzinfo is not None:
            created = created.astimezone(timezone.utc).replace(tzinfo=None)
        col_names = (["call_id", "operator_id", "casino_id", "created_at", "duration_s",
                      "overall_score_100", "pass_fail"] + _SCORE_COLS +
                     ["offer_outcome", "top_objection", "audit_json"])
        record = [
            str(row.get("call_id", "")), str(row.get("operator_id", "")),
            str(row.get("casino_id", "default")), created,
            row.get("duration_s"), row.get("overall_score_100"),
            row.get("pass_fail", ""),
            *[scores.get(c) for c in _SCORE_COLS],
            row.get("offer_outcome") or "", _top_objection(row.get("objections", [])),
            row.get("audit_json", ""),
        ]
        client.insert(_TABLE, [record], column_names=col_names)
        return True
    except Exception as e:  # noqa: BLE001 — аналитика не критична для звонка
        logger.warning("CH write_audit_flat failed for %s: %s", row.get("call_id"), e)
        return False
