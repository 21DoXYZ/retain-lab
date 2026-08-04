"""api/directory_sync.py — наполнение crm.player_directory из ClickHouse.

Оперативные экраны /pool (пул нераспределённых) и /affiliate (кабинет аффилиата),
а также RLS-хелперы crm.affiliate_player_ids()/vip_player_ids()/dept_player_ids()
читают Postgres-таблицу crm.player_directory. В деве её наполняет seed (0003), в
проде — этот sync: берём срез игроков из ClickHouse (player_features + users) и
UPSERT-им в Postgres. Запускать периодически (run_loop.sh / cron) или разово
через POST /api/v1/admin/sync-directory (super_admin).

Переиспользуем pb.q (тот же ClickHouse-клиент борда, БД retention) и psycopg к
SUPABASE_DB_URL (как can_access_player). Никакие формулы не дублируются — берём
готовые поля витрины (vip_level/recency→lifecycle/country/affiliate_code).
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint

from .core import api_json, require_auth
import player_board as pb

logger = logging.getLogger("api.directory_sync")

bp = Blueprint("api_directory", __name__, url_prefix="/api/v1")

# Срез каталога игроков: тот же lifecycle-маппинг по recency, что в /analytics и карточке.
_DIR_QUERY = """
SELECT pf.casino_player_id,
       u.affiliate_code,
       u.country_iso_estimated,
       toInt16(pf.vip_level),
       multiIf(pf.recency_days IS NULL,'never',
               pf.recency_days<=7,'active',
               pf.recency_days<=30,'cooling',
               pf.recency_days<=60,'at_risk',
               pf.recency_days<=90,'dormant','churned')
FROM player_features pf
INNER JOIN users u USING(casino_player_id)
WHERE pf.account_type='normal'
"""


def sync_player_directory(*, batch: int = 5000) -> dict:
    """Прочитать каталог игроков из ClickHouse и UPSERT в crm.player_directory.
    Возвращает {'synced': N}. Бросает RuntimeError при отсутствии SUPABASE_DB_URL."""
    dsn = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not dsn:
        raise RuntimeError("SUPABASE_DB_URL не задан — некуда писать crm.player_directory")
    try:
        import psycopg  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("psycopg (v3) не установлен — sync недоступен") from e

    rows = pb.q(_DIR_QUERY)[1]
    data = [
        (int(pid), f"P-{int(pid)}", (aff or None), (country or None), int(vip or 0), str(life))
        for pid, aff, country, vip, life in rows
    ]

    upsert = """
        INSERT INTO crm.player_directory
            (casino_player_id, display_id, affiliate_code, country, vip_level, lifecycle, synced_at)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (casino_player_id) DO UPDATE SET
            display_id=EXCLUDED.display_id, affiliate_code=EXCLUDED.affiliate_code,
            country=EXCLUDED.country, vip_level=EXCLUDED.vip_level,
            lifecycle=EXCLUDED.lifecycle, is_valid=true, synced_at=now()
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for i in range(0, len(data), batch):
                cur.executemany(upsert, data[i:i + batch])
        conn.commit()
    logger.info("player_directory sync: %d игроков", len(data))
    return {"synced": len(data)}


@bp.post("/admin/sync-directory")
@require_auth(roles=["super_admin"])
def sync_directory_endpoint():
    """Разовый ручной sync каталога (super_admin). Периодический — через run_loop.sh."""
    try:
        result = sync_player_directory()
    except RuntimeError as e:
        return api_json(error=str(e), code=503)
    return api_json(result)


if __name__ == "__main__":
    # Standalone-режим для cron/run_loop: `python -m api.directory_sync`
    # (env SUPABASE_DB_URL + доступ к ClickHouse должны быть в окружении).
    print(sync_player_directory())
