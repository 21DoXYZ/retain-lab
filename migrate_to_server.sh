#!/usr/bin/env bash
# ============================================================================
# Перенос данных из ЛОКАЛЬНОГО ClickHouse → в СЕРВЕРНЫЙ через SSH.
# Идёт напрямую (Native-формат), без CSV-промежутка. game_transactions сжимается.
#
# Запуск с локальной машины (где лежат данные):
#   ./migrate_to_server.sh user@server
#
# Требования: на сервере установлен clickhouse client, SSH-доступ настроен,
#             на сервере уже запущен clickhouse-server.
# ============================================================================
set -euo pipefail

SERVER="${1:?Использование: ./migrate_to_server.sh user@server}"
LOCAL="clickhouse client --host 127.0.0.1"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> 1/3  Создаю схему (база + 4 таблицы) на сервере"
ssh "$SERVER" "clickhouse client --multiquery" < "$DIR/schema.sql"
echo "    ✓ схема готова"

echo "==> 2/3  Переливаю таблицы напрямую (local → server)"
for t in users money_transactions game_sessions; do
  echo "    → $t"
  $LOCAL --query "SELECT * FROM retention.$t FORMAT Native" \
    | ssh "$SERVER" "clickhouse client --query 'INSERT INTO retention.$t FORMAT Native'"
done

echo "    → game_transactions (большой ~15ГБ, через gzip)"
$LOCAL --query "SELECT * FROM retention.game_transactions FORMAT Native" \
  | gzip \
  | ssh "$SERVER" "gunzip | clickhouse client --query 'INSERT INTO retention.game_transactions FORMAT Native'"

echo "==> 3/5  Собираю витрину player_features на сервере"
ssh "$SERVER" "clickhouse client --multiquery" < "$DIR/player_features.sql"

echo "==> 4/5  Аналитический слой (marts.sql: вьюхи + player_games + ML-таблицы)"
ssh "$SERVER" "clickhouse client --multiquery" < "$DIR/marts.sql"

echo "==> 5/5  Обучение моделей на сервере (если есть .venv с ML-зависимостями)"
ssh "$SERVER" 'cd retention-board 2>/dev/null && [ -x .venv/bin/python ] && \
  for m in ltv_model ltv_quantiles repeat_model churn_model deposit_ladder_model bonus_model; do \
    echo "    → $m"; .venv/bin/python $m.py >/dev/null; done && echo "    ✓ модели обучены" \
  || echo "    ⚠ .venv не найден на сервере — обучи модели вручную: pip install -r requirements-ml.txt && ./train_all.sh"'

echo "✓ Готово. На сервере: retention = 4 таблицы + player_features + marts (вьюхи/ML) + модели."
echo "  Проверка:  ssh $SERVER \"clickhouse client -q 'SELECT count() FROM retention.player_actions'\""
