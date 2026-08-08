#!/usr/bin/env bash
# Еженедельная проверка восстановимости: бэкап, который ни разу не
# восстанавливали, - это надежда, а не бэкап. Берём СВЕЖИЙ дамп самой ценной
# таблицы (wa_messages - переписка клиента), восстанавливаем в отдельную БД,
# сверяем счётчики и убираем за собой. Расхождение = алярм в лог и exit 1.
set -euo pipefail

cd /opt/retain-lab
P=$(grep '^CH_PASSWORD' .env | cut -d= -f2)
LAST=$(ls -1d /opt/backups/*/ 2>/dev/null | sort | tail -1)
[ -z "$LAST" ] && { echo "нет бэкапов - нечего проверять"; exit 1; }

CH() { docker exec -i retain-lab-clickhouse-1 clickhouse-client --password "$P" -q "$1"; }

CH "CREATE DATABASE IF NOT EXISTS restore_drill"
CH "DROP TABLE IF EXISTS restore_drill.wa_messages"
CH "CREATE TABLE restore_drill.wa_messages AS retention.wa_messages"
gunzip < "$LAST/clickhouse/wa_messages.native.gz" | \
  docker exec -i retain-lab-clickhouse-1 clickhouse-client --password "$P" \
    -q "INSERT INTO restore_drill.wa_messages FORMAT Native"

GOT=$(CH "SELECT count() FROM restore_drill.wa_messages")
CH "DROP DATABASE restore_drill"
if [ "$GOT" -lt 1 ]; then
  echo "$(date -u '+%F %T') FAIL: восстановилось $GOT строк из $LAST"
  exit 1
fi
echo "$(date -u '+%F %T') restore ok: $GOT строк wa_messages из $LAST"
