#!/usr/bin/env bash
# ============================================================================
# Восстановление ML-таблиц из каталога ml_dump/ в ClickHouse (на VPS).
# Парный скрипт к dump_ml_tables.sh — заливает обученные таблицы БЕЗ переобучения.
#
# Предполагается, что на VPS уже:
#   1) поднят ClickHouse (docker compose up -d) — применился schema.sql
#   2) загружены данные и собраны витрины: player_features.sql + marts.sql
# После этого restore наполняет ML-таблицы, и дашборд показывает прогнозы.
#
# Для каждой таблицы из ml_dump/: DROP -> CREATE (из <t>.sql) -> INSERT (<t>.native).
# Повторный запуск безопасен (перезатирает таблицы).
#
# Конфиг ЦЕЛИ через env (дефолты = локальный CH / проброшенный порт compose):
#   CH_HOST (127.0.0.1) CH_PORT (8123) CH_DB (retention) CH_USER (default) CH_PASSWORD
#
# Запуск на VPS:   ./restore_ml_tables.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

CH_HOST="${CH_HOST:-127.0.0.1}"
CH_PORT="${CH_PORT:-8123}"
CH_DB="${CH_DB:-retention}"
CH_USER="${CH_USER:-default}"
CH_PASSWORD="${CH_PASSWORD:-}"
IN="${IN:-ml_dump}"

BASE="http://${CH_HOST}:${CH_PORT}/"
hdr=(-H "X-ClickHouse-User: ${CH_USER}" -H "X-ClickHouse-Key: ${CH_PASSWORD}")

chq() { # query (текст) -> выполнить
  curl -sS --fail-with-body --max-time 120 "${hdr[@]}" \
    "${BASE}?database=${CH_DB}" --data-binary "$1"
}
chq_file() { # query, file -> выполнить с телом из файла (для INSERT ... Native)
  curl -sS --fail-with-body --max-time 600 "${hdr[@]}" \
    "${BASE}?database=${CH_DB}&query=$(_urlenc "$1")" --data-binary "@$2"
}
chq_admin() { # query без привязки к ${CH_DB} (для CREATE DATABASE на свежем сервере)
  curl -sS --fail-with-body --max-time 30 "${hdr[@]}" "${BASE}" --data-binary "$1"
}
_urlenc() { # минимальный url-encode для query-параметра
  local s="$1" o="" c i
  for ((i=0;i<${#s};i++)); do c="${s:$i:1}"
    case "$c" in [a-zA-Z0-9._~-]) o+="$c";; *) printf -v c '%%%02X' "'$c"; o+="$c";; esac
  done
  printf '%s' "$o"
}

[ -d "$IN" ] || { echo "!! Нет каталога ${IN}/ — сначала dump_ml_tables.sh + scp"; exit 1; }
echo "==> Цель: ${CH_HOST}:${CH_PORT}  db=${CH_DB}"
curl -sS --fail --max-time 5 "${BASE}ping" >/dev/null || { echo "!! ClickHouse недоступен"; exit 1; }
chq_admin "CREATE DATABASE IF NOT EXISTS ${CH_DB}" >/dev/null

shopt -s nullglob
done_n=0
for ddl in "${IN}"/*.sql; do
  t="$(basename "${ddl}" .sql)"
  native="${IN}/${t}.native"
  [ -f "$native" ] || { echo "   ⚠ нет данных для ${t} (.native) — пропуск"; continue; }

  chq "DROP TABLE IF EXISTS ${CH_DB}.${t}" >/dev/null
  # DDL из дампа содержит явное «<src_db>.<t>» — ретаргетим на целевую ${CH_DB}
  ddl_sql="$(sed -E "s/^CREATE (TABLE|MATERIALIZED VIEW|VIEW) [^ (]+\.${t}/CREATE \1 ${CH_DB}.${t}/" "$ddl")"
  chq "$ddl_sql" >/dev/null
  chq_file "INSERT INTO ${CH_DB}.${t} FORMAT Native" "$native" >/dev/null
  rows=$(chq "SELECT count() FROM ${CH_DB}.${t}")
  printf "   ✓ %-26s rows=%s\n" "$t" "$rows"
  done_n=$((done_n+1))
done

echo ""
echo "✓ Восстановлено таблиц: ${done_n}"
echo "  Проверка дашборда: ML-страницы (LTV-квантили, next-deposit, бонусы) должны ожить."
