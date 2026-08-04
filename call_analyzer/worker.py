"""Celery-воркер + beat (dev spec §2, §7, §10).

Один надёжный таск analyze_call прогоняет весь пайплайн process_call: сбой звонка
там ловится и уводит его в верный статус, очередь не падает (dev spec §7).
Партиционирование по call_id обеспечивается тем, что задача идемпотентна (upsert
аудита) и звонок обрабатывается целиком в одном воркере.

Beat:
  • discover_calls  — каждые 60с: новые дозвоны crm.calls → analyzer.calls → очередь.
  • daily_random_sample — ежедневно: контрольная случайная выборка (интерфейс §7).

REDIS_URL — брокер. ClickHouse-DDL создаётся при старте воркера.
"""
from __future__ import annotations

import logging
import os

from celery import Celery
from celery.signals import worker_ready

from call_analyzer import authenticity, clickhouse, db
from call_analyzer.config import load_config
from call_analyzer.pipeline import process_call

logger = logging.getLogger("call_analyzer.worker")

_BROKER = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("call_analyzer", broker=_BROKER, backend=_BROKER)
celery_app.conf.update(
    task_acks_late=True,               # звонок не теряется при падении воркера
    worker_prefetch_multiplier=1,      # честное распределение долгих задач
    task_default_queue="analyzer",
    timezone="UTC",
    beat_schedule={
        "discover-calls": {"task": "call_analyzer.discover_calls", "schedule": 60.0},
        "daily-random-sample": {"task": "call_analyzer.daily_random_sample",
                                 "schedule": 24 * 60 * 60.0},
    },
)


@worker_ready.connect
def _on_ready(**_kwargs):
    """DDL call_audits_flat при старте воркера (dev spec §4.2)."""
    try:
        clickhouse.ensure_schema()
    except Exception as e:  # noqa: BLE001
        logger.warning("CH ensure_schema при старте не выполнен: %s", e)


@celery_app.task(name="call_analyzer.analyze_call", bind=True, max_retries=0)
def analyze_call(self, call_id: str) -> dict:
    """Разобрать один звонок (dev spec §2). Ошибки звонка не поднимаются наверх."""
    result = process_call(call_id)
    return {"call_id": result.call_id, "status": result.status,
            "overall_score_100": result.overall_score_100, "pass_fail": result.pass_fail}


@celery_app.task(name="call_analyzer.discover_calls")
def discover_calls() -> int:
    """Новые дозвоны crm.calls → analyzer.calls + очередь (dev spec §10)."""
    created = 0
    for row in db.discover_new_crm_calls(limit=200):
        try:
            call_id = db.create_call({
                "crm_call_id": row["crm_call_id"], "operator_id": row["operator_id"],
                "casino_player_id": row["casino_player_id"], "audio_ref": row["audio_ref"],
                "duration_s": row["duration_s"], "started_at": row["started_at"],
                "source": "tegsoft",
            })
            analyze_call.delay(call_id)
            created += 1
        except Exception as e:  # noqa: BLE001 — один битый звонок не роняет discover
            logger.warning("discover: пропущен crm_call %s: %s", row.get("crm_call_id"), e)
    if created:
        logger.info("discover_calls: поставлено в очередь %d звонков", created)
    return created


@celery_app.task(name="call_analyzer.daily_random_sample")
def daily_random_sample(casino_id: str = "default") -> int:
    """Контрольная случайная выборка дня (интерфейс §7). Учитывает уже отобранных."""
    cfg = load_config(casino_id=casino_id)
    target = cfg.random_sample_per_day
    if target <= 0:
        return 0  # выборка выключена
    already = db.count_random_reviews_today(casino_id)
    need = max(0, target - already)
    picked = db.pick_random_sample(casino_id=casino_id, n=need)
    for cid in picked:
        db.add_flag(cid, authenticity.RANDOM_REVIEW)
    return len(picked)
