#!/usr/bin/env bash
# ============================================================================
# Выгрузка ОБУЧЕННЫХ ML-таблиц из ClickHouse в каталог ml_dump/.
# Нужно, чтобы перенести результат обучения на другой сервер БЕЗ переобучения
# (на VPS не понадобится CatBoost / sklearn — только восстановить таблицы).
#
# Что выгружается: 7 таблиц-выходов train_all.sh (это дорого считается на CatBoost).
# player_features / marts (в т.ч. bonus_effectiveness_t) НЕ дампим — они
# пересобираются на VPS чистым SQL (player_features.sql + marts.sql).
#
# Формат: на каждую таблицу 2 файла —
#   <table>.sql     — DDL (SHOW CREATE TABLE), чтобы пересоздать 1:1
#   <table>.native  — данные в бинарном ClickHouse Native (точные типы)
#
# Конфиг ИСТОЧНИКА через env (дефолты = локальный CH):
#   CH_HOST (127.0.0.1) CH_PORT (8123) CH_DB (retention) CH_USER (default) CH_PASSWORD
#
# Запуск:   ./dump_ml_tables.sh
# Перенос:  scp -r ml_dump/  user@vps:/path/retention-board/
# Заливка:  на VPS  ->  ./restore_ml_tables.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

CH_HOST="${CH_HOST:-127.0.0.1}"
CH_PORT="${CH_PORT:-8123}"
CH_DB="${CH_DB:-retention}"
CH_USER="${CH_USER:-default}"
CH_PASSWORD="${CH_PASSWORD:-}"
OUT="${OUT:-ml_dump}"

TABLES=(
  player_ltv_ml
  player_ltv_quantiles
  player_repeat_ml
  player_churn_ml
  player_next_deposit_ml
  player_bonus_ml
  bonus_uplift
)

BASE="http://${CH_HOST}:${CH_PORT}/"
hdr=(-H "X-ClickHouse-User: ${CH_USER}" -H "X-ClickHouse-Key: ${CH_PASSWORD}")

chq() { # query -> stdout (fail on HTTP error)
  curl -sS --fail-with-body --max-time 120 "${hdr[@]}" \
    "${BASE}?database=${CH_DB}" --data-binary "$1"
}

echo "==> Источник: ${CH_HOST}:${CH_PORT}  db=${CH_DB}"
curl -sS --fail --max-time 5 "${BASE}ping" >/dev/null || { echo "!! ClickHouse недоступен"; exit 1; }
mkdir -p "$OUT"
: > "${OUT}/MANIFEST.txt"

total=0
for t in "${TABLES[@]}"; do
  exists=$(chq "SELECT count() FROM system.tables WHERE database='${CH_DB}' AND name='${t}'")
  if [ "$exists" != "1" ]; then
    echo "   ⚠ пропуск (нет таблицы): ${t}"
    echo "SKIP ${t}" >> "${OUT}/MANIFEST.txt"
    continue
  fi
  # DDL
  chq "SHOW CREATE TABLE ${CH_DB}.${t} FORMAT TabSeparatedRaw" > "${OUT}/${t}.sql"
  # данные
  chq "SELECT * FROM ${CH_DB}.${t} FORMAT Native" > "${OUT}/${t}.native"
  rows=$(chq "SELECT count() FROM ${CH_DB}.${t}")
  sz=$(wc -c < "${OUT}/${t}.native" | tr -d ' ')
  printf "   ✓ %-26s rows=%-8s native=%s B\n" "$t" "$rows" "$sz"
  echo "${t} rows=${rows} bytes=${sz}" >> "${OUT}/MANIFEST.txt"
  total=$((total+1))
done

echo ""
echo "✓ Готово: ${total} таблиц в ./${OUT}/"
echo "  Дальше:  scp -r ${OUT}/ user@vps:/path/retention-board/  &&  ./restore_ml_tables.sh"
