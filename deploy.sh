#!/usr/bin/env bash
# Деплой на VPS. ЕДИНСТВЕННЫЙ правильный способ синхронизации: один источник
# на один вызов rsync. Дважды за проект «rsync -az api/ stripe_sync/ host:/opt/»
# вываливал содержимое stripe_sync в КОРЕНЬ репозитория на сервере, перезаписывал
# корневой Dockerfile - и борд собирался как stripe-вебхук и падал в цикле.
set -euo pipefail

HOST="root@187.77.157.6"
KEY="$HOME/.ssh/retainlab-vps"
DEST=/opt/retain-lab
SVC="${*:-board}"

sync() {   # sync <локальный каталог|файл> <путь на сервере>
  rsync -az -e "ssh -i $KEY" --exclude __pycache__/ --exclude node_modules/ \
        --exclude .next/ "$1" "$HOST:$DEST/$2"
}

sync api/         api/
sync stripe_sync/ stripe_sync/
sync ingest/      ingest/
sync snippet/     snippet/
sync crm-spa/     crm-spa/
sync demo-site/   demo-site/
rsync -az -e "ssh -i $KEY" Dockerfile requirements.txt docker-compose.yml \
      docker-compose.vps.yml saas_schema.sql "$HOST:$DEST/"

ssh -i "$KEY" "$HOST" "cd $DEST && docker compose -f docker-compose.yml \
  -f docker-compose.vps.yml up -d --build $SVC"

# Проверка, что не собралось не тем Dockerfile: борд обязан отвечать.
sleep 8
code=$(curl -s -o /dev/null -w '%{http_code}' https://retivo.digital/api/v1/saas/onboarding)
echo "борд отвечает: $code (401 = живой, требует вход)"
[ "$code" = "000" ] && { echo "БОРД НЕ ОТВЕЧАЕТ - смотри docker logs"; exit 1; }
exit 0
