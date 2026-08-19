#!/usr/bin/env bash
# Ночной бэкап (хост, cron 03:30): ClickHouse + секреты тенантов.
#
# ЛОКАЛЬНЫЙ бэкап защищает от порчи данных и кривой мутации - НЕ от смерти
# диска. Оффсайт (B2/S3) - отдельное решение владельца; когда цель появится,
# сюда добавляется одна строка rclone.
#
# Установка (однократно):
#   cp /opt/retain-lab/retain_backup.sh /usr/local/bin/ && chmod +x /usr/local/bin/retain_backup.sh
#   echo '30 3 * * * root /usr/local/bin/retain_backup.sh >> /var/log/retain_backup.log 2>&1' \
#     > /etc/cron.d/retain-backup
set -u

CH=retain-lab-clickhouse-1
ENVFILE=/opt/retain-lab/.env
DEST=/opt/backups
STAMP=$(date +%Y%m%d)
KEEP_CH_DAYS=7
KEEP_SECRETS_DAYS=14

mkdir -p "$DEST/clickhouse" "$DEST/secrets"
CH_PASSWORD=$(grep -m1 '^CH_PASSWORD=' "$ENVFILE" | cut -d= -f2-)
chq() { docker exec "$CH" clickhouse-client --password "$CH_PASSWORD" -q "$1"; }

journal() {
  chq "INSERT INTO retention.pipeline_runs
       (tenant_id, stage, status, detail, input_fresh, skipped_reason, rows,
        duration_s, started_at)
       VALUES ('hubcontent', 'backup', '$1', '$2', 1, '', 0, 0, now64(3))" || true
}

# 1. ClickHouse: консистентный снимок средствами самого сервера
if chq "BACKUP DATABASE retention TO File('/backups/retention_${STAMP}')" >/dev/null; then
  SIZE=$(du -sh "$DEST/clickhouse/retention_${STAMP}" 2>/dev/null | cut -f1)
  echo "$(date -Is) backup: clickhouse ok (${SIZE:-?})"
else
  echo "$(date -Is) backup: CLICKHOUSE FAILED"
  journal error "clickhouse_backup_failed"
  exit 1
fi

# 2. Секреты и конфиги тенантов (маленькие, но невосстановимые)
tar czf "$DEST/secrets/secrets_${STAMP}.tgz" \
    -C /opt/retain-lab secrets .env ch_users.d ch_config.d 2>/dev/null

# 3. Ротация
find "$DEST/clickhouse" -maxdepth 1 -name 'retention_*' -mtime +$KEEP_CH_DAYS \
     -exec rm -rf {} + 2>/dev/null
find "$DEST/secrets" -name 'secrets_*.tgz' -mtime +$KEEP_SECRETS_DAYS \
     -delete 2>/dev/null

journal ok "ch_${STAMP}_${SIZE:-na}"
echo "$(date -Is) backup: done"
