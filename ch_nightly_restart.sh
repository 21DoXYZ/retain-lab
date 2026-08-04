#!/bin/sh
# Ночной рестарт ClickHouse — сбрасывает дрейф глобального memory-трекера.
# Инцидент 2026-07-29: system.metrics.MemoryTracking залипал у лимита сервера
# (~14 ГБ) за несколько дней аптайма, хотя реальный RSS ~1 ГБ → OvercommitTracker
# валил ЛЮБОЙ новый запрос (code 241 MEMORY_LIMIT_EXCEEDED) → спонтанные 500 на
# тяжёлых страницах (/affiliates, /ltv, /traffic/verdicts). Данные на диске
# (volume ch_data) — рестарт безопасен, даунтайм ~10с.
cd /home/retention-board || exit 1
echo "=== $(date -u '+%Y-%m-%d %H:%M:%S UTC') restart clickhouse ==="
docker compose restart clickhouse
echo "done: $(date -u '+%H:%M:%S UTC')"
