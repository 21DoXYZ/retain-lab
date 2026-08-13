#!/usr/bin/env bash
# Сторожок инфраструктуры (хост, cron каждые 10 минут).
#
# ЗАЧЕМ. 2026-08-13 ClickHouse 4 дня копил дрейф memory-трекера (насчитал
# 14.4 GiB при реальных 924 MB), упёрся в потолок и начал отбивать ВСЕ
# запросы - продукт стоял с пустыми экранами, пока никто не смотрел.
# Джобы внутри контейнеров это не лечат: им нечем перезапустить CH.
#
# ЧТО ДЕЛАЕТ. Три проверки, итог пишется в retention.pipeline_runs
# (stage='ops_guard') - виден на /pipeline, красный статус роняет вердикт
# «конвейер здоров», то есть владелец УЗНАЕТ, а не догадывается:
#   1. CH отвечает на запрос? Нет два прогона подряд -> restart.
#   2. Дрейф трекера: MemoryTracking > 8 GiB при реальном RSS < 2 GiB ->
#      restart (данные на диске, ReplacingMergeTree, рестарт безопасен).
#   3. Диск > 85% -> строка error в журнале (сам ничего не удаляет).
#
# Установка (однократно, на VPS):
#   cp /opt/retain-lab/ops_guard.sh /usr/local/bin/ && chmod +x /usr/local/bin/ops_guard.sh
#   echo '*/10 * * * * root /usr/local/bin/ops_guard.sh >> /var/log/ops_guard.log 2>&1' \
#     > /etc/cron.d/retain-ops-guard
set -u

CH=retain-lab-clickhouse-1
ENVFILE=/opt/retain-lab/.env
STAMP=/var/tmp/ops_guard_ch_fail       # флажок «прошлый прогон CH не ответил»
DRIFT_LIMIT=$((8 * 1024 * 1024 * 1024))  # трекер > 8 GiB
RSS_LIMIT=$((2 * 1024 * 1024 * 1024))    # при реальном RSS < 2 GiB
DISK_LIMIT=85

CH_PASSWORD=$(grep -m1 '^CH_PASSWORD=' "$ENVFILE" | cut -d= -f2-)
chq() {  # запрос к CH изнутри контейнера, TSV
  docker exec "$CH" clickhouse-client --password "$CH_PASSWORD" -q "$1" 2>/dev/null
}

journal() {  # status detail  -> pipeline_runs (не падаем, если CH лежит)
  local st="$1" detail="$2"
  chq "INSERT INTO retention.pipeline_runs
       (tenant_id, stage, status, detail, input_fresh, skipped_reason, rows,
        duration_s, started_at)
       VALUES ('hubcontent', 'ops_guard', '${st}', '${detail}', 1, '', 0, 0, now64(3))" \
    || true
}

restart_ch() {
  echo "$(date -Is) ops_guard: RESTART clickhouse ($1)"
  docker restart "$CH" >/dev/null
  # дождаться готовности, затем оставить след в журнале
  for _ in $(seq 1 30); do
    sleep 5
    chq "SELECT 1" >/dev/null && break
  done
  journal ok "auto_restart:$1"
  rm -f "$STAMP"
}

# ── 1. живость ────────────────────────────────────────────────────────────────
if ! chq "SELECT 1" >/dev/null; then
  if [ -f "$STAMP" ]; then
    restart_ch "unresponsive_twice"
  else
    touch "$STAMP"                      # один сбой терпим: может быть мердж
    echo "$(date -Is) ops_guard: CH не ответил, жду следующий прогон"
  fi
  exit 0
fi
rm -f "$STAMP"

# ── 2. дрейф memory-трекера ──────────────────────────────────────────────────
TRACK=$(chq "SELECT toInt64(value) FROM system.metrics WHERE metric='MemoryTracking'")
RSS=$(chq "SELECT toInt64(value) FROM system.asynchronous_metrics WHERE metric='MemoryResident'")
if [ -n "${TRACK:-}" ] && [ -n "${RSS:-}" ] \
   && [ "$TRACK" -gt "$DRIFT_LIMIT" ] && [ "$RSS" -lt "$RSS_LIMIT" ]; then
  restart_ch "tracker_drift_track=${TRACK}_rss=${RSS}"
  exit 0
fi

# ── 3. диск ──────────────────────────────────────────────────────────────────
DISK=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "${DISK:-0}" -ge "$DISK_LIMIT" ]; then
  journal error "disk_${DISK}pct"
  echo "$(date -Is) ops_guard: ДИСК ${DISK}% - нужно чистить руками"
  exit 0
fi

journal ok "track=$((TRACK / 1024 / 1024))MB_rss=$((RSS / 1024 / 1024))MB_disk=${DISK}pct"
