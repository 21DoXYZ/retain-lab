#!/usr/bin/env bash
# Цикл ДЕМО-СТЕНДА: поток demo.live_events -> сырые таблицы -> витрина.
#
# Урезанная копия run_loop.sh: без скоринга каждые 5 минут (демо-скоры статичны,
# пересчитываются вручную) и БЕЗ отправки в казино — у демо её нет в принципе.
# Работает в базе `demo` под demo_user, до retention доступа не имеет.
set -euo pipefail
cd "$(dirname "$0")"

exec 9>/tmp/demo_loop.lock
flock -n 9 || exit 0

PASS=$(sed -n 's/^CH_PASSWORD=//p' .env)
CHQ() { docker exec retention-board-clickhouse-1 clickhouse client --password "$PASS" -q "$1"; }
CHM() { docker exec -i retention-board-clickhouse-1 clickhouse client --password "$PASS" --multiquery; }
ts() { date '+%F %T'; }

CHQ "CREATE TABLE IF NOT EXISTS demo.sync_state
     (key String, wm DateTime64(3), updated_at DateTime64(3) DEFAULT now64(3))
     ENGINE = ReplacingMergeTree(updated_at) ORDER BY key"

WM=$(CHQ "SELECT toString(max(wm)) FROM demo.sync_state WHERE key='live_events'")
case "$WM" in ""|"1970-01-01"*) WM="2026-01-01 00:00:00.000";; esac
UPPER=$(CHQ "SELECT toString(now64(3) - INTERVAL 30 SECOND)")

CHM <<SQL
INSERT INTO demo.game_transactions
  (transaction_row_id, casino_player_id, session_id, aggregator, game_uuid, game_name,
   transaction_type, bet_amount, win_amount, amount, currency, status, created_at)
SELECT event_id, casino_player_id, session_id, provider, game_uuid, game_name,
  multiIf(event_type='bet' AND is_freespin=1, 'freespins_bet', event_type='bet', 'bet',
          event_type='win' AND is_freespin=1, 'freespins_win', 'win'),
  bet_amount, win_amount, if(event_type='bet', bet_amount, win_amount), currency, 'completed', ts
FROM demo.live_events FINAL
WHERE event_type IN ('bet','win')
  AND ingested_at > toDateTime64('$WM',3) AND ingested_at <= toDateTime64('$UPPER',3)
  AND event_id NOT IN (SELECT transaction_row_id FROM demo.game_transactions
                       WHERE created_at > now() - INTERVAL 2 DAY);

INSERT INTO demo.money_transactions
  (transaction_row_id, transaction_id, casino_player_id, type, status, amount, currency,
   payment_method, is_manual, description, created_at)
SELECT event_id, transaction_id, casino_player_id, event_type, status, amount, currency,
   payment_method, is_manual, description, ts
FROM demo.live_events FINAL
WHERE event_type IN ('deposit','withdrawal','bonus')
  AND ingested_at > toDateTime64('$WM',3) AND ingested_at <= toDateTime64('$UPPER',3)
  AND event_id NOT IN (SELECT transaction_row_id FROM demo.money_transactions
                       WHERE created_at > now() - INTERVAL 2 DAY);

INSERT INTO demo.game_names (game_uuid, game_name, provider)
SELECT game_uuid, argMax(game_name, ts), argMax(provider, ts) FROM demo.live_events
WHERE game_name != '' AND game_uuid != ''
  AND ingested_at > toDateTime64('$WM',3) AND ingested_at <= toDateTime64('$UPPER',3)
GROUP BY game_uuid;

-- Генератор шлёт самоописательные id (pragmatic/gates-of-olympus) без game_name.
-- Выводим читаемое название и провайдера из самого id, иначе в интерфейсе
-- висели бы «id pragmatic/…» вместо названий игр.
INSERT INTO demo.game_names (game_uuid, game_name, provider)
SELECT DISTINCT game_uuid,
       initcap(replaceAll(splitByChar('/', game_uuid)[2], '-', ' ')),
       initcap(splitByChar('/', game_uuid)[1])
FROM demo.game_transactions
WHERE game_uuid LIKE '%/%'
  AND game_uuid NOT IN (SELECT game_uuid FROM demo.game_names);

INSERT INTO demo.sync_state (key, wm) VALUES ('live_events', toDateTime64('$UPPER',3));
SQL

CHM < /tmp/demo_features.sql 2>/dev/null || sed 's/retention\./demo./g' player_features.sql | CHM
echo "[$(ts)] demo: синк ок · игроков в витрине $(CHQ 'SELECT count() FROM demo.player_features')"
