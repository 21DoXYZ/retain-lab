#!/usr/bin/env bash
# Ночной бэкап боевых данных (VPS, cron 03:30 UTC - тихие часы аудитории Дубая).
#
# Что спасаем и почему:
#   • ClickHouse retention.* (MergeTree-таблицы) - события, identity, переписка
#     WhatsApp, логи кампаний. Вьюхи/словари/Kafka НЕ дампим: их пересоздаёт
#     saas_schema.sql из git, а SELECT из Kafka-таблицы ещё и съел бы очередь.
#   • secrets/ - tenants/tokens/overrides (в git не попадают принципиально).
#   • waha_sessions - авторизация личного WhatsApp: потеря = клиент заново
#     сканирует QR и теряет доверие («опять вотсап поломался»).
#   • .env - пароли CH и ключи платформы.
#
# Формат: Native+gzip (посвайплайнно, без изменения конфига CH). Восстановление:
#   gunzip < t.native.gz | clickhouse-client -q "INSERT INTO retention.t FORMAT Native"
# Ротация 14 суток. Прогон восстановления - restore_drill.sh (гоняется тем же
# кроном раз в неделю: бэкап, который ни разу не восстанавливали, - не бэкап).
set -euo pipefail

cd /opt/retain-lab
P=$(grep '^CH_PASSWORD' .env | cut -d= -f2)
STAMP=$(date -u +%Y%m%d-%H%M%S)
DEST="/opt/backups/$STAMP"
mkdir -p "$DEST/clickhouse"

TABLES=$(docker exec retain-lab-clickhouse-1 clickhouse-client --password "$P" \
  -q "SELECT name FROM system.tables WHERE database='retention' AND engine LIKE '%MergeTree%'")
for t in $TABLES; do
  docker exec retain-lab-clickhouse-1 clickhouse-client --password "$P" \
    -q "SELECT * FROM retention.$t FORMAT Native" | gzip > "$DEST/clickhouse/$t.native.gz"
done

tar -czf "$DEST/secrets.tar.gz" -C /opt/retain-lab secrets
cp /opt/retain-lab/.env "$DEST/env.backup" && chmod 600 "$DEST/env.backup"
docker run --rm -v retain-lab_waha_sessions:/v -v "$DEST":/b alpine \
  tar -czf /b/waha_sessions.tar.gz -C /v .

find /opt/backups -maxdepth 1 -mindepth 1 -type d -mtime +14 -exec rm -rf {} +
echo "$(date -u '+%F %T') ok: $DEST ($(du -sh "$DEST" | cut -f1), таблиц: $(echo "$TABLES" | wc -w))"
