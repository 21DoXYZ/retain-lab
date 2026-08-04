#!/usr/bin/env bash
# IP-allowlist для внешнего Kafka-порта Redpanda (19092).
# Список разрешённых IP берётся из .env -> KAFKA_ALLOWED_IPS (через запятую).
# Пусто = разрешено всем (только для теста!).
#
# Docker обходит ufw, поэтому правила ставим в цепочку DOCKER-USER.
# Запуск:  sudo ./kafka_firewall.sh
# Правила НЕ переживают перезагрузку — повесь на запуск (systemd/cron @reboot) или iptables-persistent.
set -euo pipefail
cd "$(dirname "$0")"

PORT=19092
CHAIN=RP_ALLOWLIST
ALLOWED=$(sed -n 's/^KAFKA_ALLOWED_IPS=//p' .env | tr -d ' ')

if [ "$(id -u)" -ne 0 ]; then echo "нужен root (sudo)"; exit 1; fi

# своя цепочка + хук из DOCKER-USER именно для нашего порта
iptables -N "$CHAIN" 2>/dev/null || true
iptables -C DOCKER-USER -p tcp --dport "$PORT" -j "$CHAIN" 2>/dev/null \
  || iptables -I DOCKER-USER 1 -p tcp --dport "$PORT" -j "$CHAIN"

# пересобираем цепочку с нуля
iptables -F "$CHAIN"
if [ -z "$ALLOWED" ]; then
  echo "KAFKA_ALLOWED_IPS пуст -> разрешаю ВСЕМ (порт $PORT открыт всему интернету)"
  iptables -A "$CHAIN" -j RETURN
else
  IFS=',' read -ra IPS <<< "$ALLOWED"
  for ip in "${IPS[@]}"; do
    echo "allow $ip -> :$PORT"
    iptables -A "$CHAIN" -s "$ip" -j RETURN
  done
  # всё остальное на этот порт — drop
  iptables -A "$CHAIN" -j DROP
fi
echo "готово. Текущая цепочка $CHAIN:"
iptables -L "$CHAIN" -n -v --line-numbers
