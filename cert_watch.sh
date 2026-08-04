#!/usr/bin/env bash
# Страховка авто-продления TLS: если сертификат, который отдаёт брокер Redpanda (:19092),
# отстал от свежего серта Caddy (:443, обновляется Let's Encrypt) — перезапускаем Redpanda,
# чтобы он перечитал новый сертификат. Если совпадают — ничего не делаем.
#
# Ставится в cron (см. установку ниже). Логи -> cert_watch.log.
set -euo pipefail
cd "$(dirname "$0")"

DOMAIN=cas.21do.xyz
DOCKER=/usr/bin/docker
ts() { date '+%Y-%m-%d %H:%M:%S'; }

fp() {  # отпечаток серта, который отдаёт host:port
  echo | openssl s_client -connect "$1" -servername "$DOMAIN" 2>/dev/null \
    | openssl x509 -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2
}

caddy_fp=$(fp "$DOMAIN:443")
broker_fp=$(fp "$DOMAIN:19092")

if [ -z "$caddy_fp" ]; then
  echo "$(ts) cert_watch: не смог прочитать серт Caddy (:443) — пропускаю"; exit 0
fi
if [ "$caddy_fp" = "$broker_fp" ]; then
  echo "$(ts) cert_watch: ок, серты совпадают — рестарт не нужен"; exit 0
fi

echo "$(ts) cert_watch: серт брокера устарел (broker=${broker_fp:-none} caddy=$caddy_fp) -> рестарт redpanda"
$DOCKER compose restart redpanda
echo "$(ts) cert_watch: redpanda перезапущен"
