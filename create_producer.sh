#!/usr/bin/env bash
# Создаёт producer-only SASL-аккаунт для отправки событий в топик casino.events.
# Аккаунт может ТОЛЬКО писать в casino.events (не читать, не удалять, не трогать другие топики).
#
# Использование:  ./create_producer.sh <username>
# Пример:         ./create_producer.sh casino_prod
set -euo pipefail
cd "$(dirname "$0")"

USER_NAME="${1:?Использование: ./create_producer.sh <username>}"
ADMIN_PASS=$(sed -n 's/^KAFKA_ADMIN_PASS=//p' .env)
[ -z "${ADMIN_PASS:-}" ] && { echo "ERROR: нет KAFKA_ADMIN_PASS в .env"; exit 1; }

PASS=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)
RX="docker exec retention-board-redpanda-1 rpk"
AUTH="-X user=admin -X pass=$ADMIN_PASS -X sasl.mechanism=SCRAM-SHA-256 -X brokers=localhost:9092"

echo "Создаю пользователя '$USER_NAME'..."
$RX security user create "$USER_NAME" -p "$PASS" --mechanism SCRAM-SHA-256

echo "Выдаю producer-only ACL на топик casino.events..."
$RX acl create --allow-principal "User:$USER_NAME" --operation write,describe --topic casino.events $AUTH >/dev/null
$RX acl create --allow-principal "User:$USER_NAME" --operation idempotent-write --cluster      $AUTH >/dev/null

cat <<EOF

================== ВЫДАТЬ КАЗИНО (передавать безопасным каналом) ==================
BROKER (bootstrap):  cas.21do.xyz:19092
SECURITY_PROTOCOL:   SASL_SSL
SASL_MECHANISM:      SCRAM-SHA-256
SASL_USER:           $USER_NAME
SASL_PASS:           $PASS
TOPIC:               casino.events
(ca-файл НЕ нужен — TLS Let's Encrypt доверяется системно)
==================================================================================

Отозвать доступ позже:  docker exec retention-board-redpanda-1 rpk security user delete $USER_NAME
EOF
