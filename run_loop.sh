#!/usr/bin/env bash
# ============================================================================
# ПЕТЛЯ (одна итерация): стрим -> сырые таблицы -> витрина -> скоринг -> сигналы.
#
#   1) SYNC     инкрементально переносит события из live_events/users_stream
#               в сырые таблицы (watermark в retention.sync_state, дедуп по
#               event_id -> transaction_row_id, повторный запуск безопасен)
#   2) FEATURES пересборка player_features
#   3) SCORE    SCORE_ONLY-скоринг всех моделей из .cbm (без обучения)
#   4) PUSH     отправка сигналов на колбэк казино (CALLBACK_URL из .env)
#
# Запуск руками:  ./run_loop.sh
# Cron (каждый час):  0 * * * * /home/retention-board/run_loop.sh >> /home/retention-board/loop.log 2>&1
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

exec 9>/tmp/retention_loop.lock
flock -n 9 || { echo "[$(date '+%F %T')] loop: уже идёт другая итерация — выходим"; exit 0; }

PASS=$(sed -n 's/^CH_PASSWORD=//p' .env)
CHQ() { docker exec retention-board-clickhouse-1 clickhouse client --password "$PASS" -q "$1"; }
CHM() { docker exec -i retention-board-clickhouse-1 clickhouse client --password "$PASS" --multiquery; }
ts() { date '+%F %T'; }

echo "[$(ts)] loop: старт"

# ---------------------------------------------------------------- 0) ЗАМОРОЗКА при тишине в потоке
# Если казино молчит, витрину пересобирать НЕЛЬЗЯ: lifecycle считается от today(),
# и все игроки сползут в «отток» → ложные SAVE-сигналы и лишние бонусы.
# Держим последнее хорошее состояние, пока поток не оживёт.
MAX_SILENCE=$(sed -n 's/^MONITOR_STREAM_MAX_SILENCE=//p' .env); MAX_SILENCE="${MAX_SILENCE:-900}"
SILENCE=$(CHQ "SELECT toInt64(ifNull(dateDiff('second', max(ingested_at), now64(3)), 999999)) FROM retention.live_events")
SILENCE="${SILENCE:-999999}"
if [ "$SILENCE" -gt "$MAX_SILENCE" ]; then
  echo "[$(ts)] loop: ЗАМОРОЗКА — событий нет $((SILENCE/60)) мин (порог $((MAX_SILENCE/60)) мин)."
  echo "[$(ts)] loop: витрина, скоринг и сигналы НЕ обновляются, состояние сохранено. Жду восстановления потока."
  exit 0
fi

# ---------------------------------------------------------------- 1) SYNC
CHQ "CREATE TABLE IF NOT EXISTS retention.sync_state
     (key String, wm DateTime64(3), updated_at DateTime64(3) DEFAULT now64(3))
     ENGINE = ReplacingMergeTree(updated_at) ORDER BY key"

# Справочник игр (game_uuid -> название) + словарь поверх него: дашборд резолвит
# названия через dictGet, поэтому объекты обязаны существовать даже после пересоздания
# БД из schema.sql. Пароль берём из .env — в репозиторий он не попадает.
CHQ "CREATE TABLE IF NOT EXISTS retention.game_names
     (game_uuid String, game_name String, provider String,
      updated_at DateTime64(3) DEFAULT now64(3))
     ENGINE = ReplacingMergeTree(updated_at) ORDER BY game_uuid"
CHQ "CREATE DICTIONARY IF NOT EXISTS retention.dict_game_names
     (game_uuid String, game_name String, provider String)
     PRIMARY KEY game_uuid
     SOURCE(CLICKHOUSE(TABLE 'game_names' DB 'retention' USER 'default' PASSWORD '$PASS'))
     LAYOUT(COMPLEX_KEY_HASHED())
     LIFETIME(MIN 300 MAX 600)"

# Справочники ставок для /ggr (NGR): наполняет load_reference_rates.py из архива казино.
# Пустыми создаём здесь, чтобы страница не падала 500 до заливки CSV и после пересоздания БД.
CHQ "CREATE TABLE IF NOT EXISTS retention.provider_rates
     (provider String, engr_percent Float64, infra_percent Float64, revshare_percent Float64,
      fixed_fee Float64, minimum_guarantee Float64, period String)
     ENGINE = MergeTree ORDER BY provider"
CHQ "CREATE TABLE IF NOT EXISTS retention.affiliate_rates
     (affiliate_db_id UInt32, affiliate_code String, username String, account_type String,
      status String, currency String, commission_rate_percent Float64, created_at String, updated_at String)
     ENGINE = MergeTree ORDER BY affiliate_db_id"

WM=$(CHQ "SELECT toString(max(wm)) FROM retention.sync_state WHERE key='live_events'")
# первый запуск: стартуем сразу после конца исторических данных (иначе дедуп-окно = вся таблица)
case "$WM" in ""|"1970-01-01"*) WM="2026-06-05 00:00:00.000";; esac
# верхняя граница окна: 60с назад — дать доехать хвосту из Kafka
UPPER=$(CHQ "SELECT toString(now64(3) - INTERVAL 60 SECOND)")
# Самое старое СОБЫТИЙНОЕ время в партии: дедуп ищем от него, а не от watermark.
# Иначе досланные из outbox события (ts недельной давности) прошли бы мимо дедупа.
MINTS=$(CHQ "SELECT toString(ifNull(min(ts), toDateTime64('$UPPER',3))) FROM retention.live_events
             WHERE ingested_at > toDateTime64('$WM',3) AND ingested_at <= toDateTime64('$UPPER',3)")
MINTS="${MINTS:-$UPPER}"
echo "[$(ts)] sync: окно приёма ($WM .. $UPPER] · события от $MINTS"

CHM <<SQL
-- игровые события -> game_transactions (event_id пишем в transaction_row_id для дедупа)
INSERT INTO retention.game_transactions
  (transaction_row_id, casino_player_id, session_id, aggregator, game_uuid, game_name,
   transaction_type, bet_amount, win_amount, amount, currency, status, created_at)
SELECT event_id, casino_player_id, session_id, provider, game_uuid, game_name,
  multiIf(event_type='bet' AND is_freespin=1, 'freespins_bet',
          event_type='bet',                    'bet',
          event_type='win' AND is_freespin=1, 'freespins_win', 'win'),
  bet_amount, win_amount, if(event_type='bet', bet_amount, win_amount),
  currency, 'completed', ts
FROM retention.live_events FINAL
WHERE event_type IN ('bet','win')
  AND ingested_at > toDateTime64('$WM', 3) AND ingested_at <= toDateTime64('$UPPER', 3)
  AND event_id NOT IN (SELECT transaction_row_id FROM retention.game_transactions
                       WHERE created_at > toDateTime64('$MINTS', 3) - INTERVAL 1 DAY);

-- денежные события -> money_transactions (со статусом, способом оплаты, ручным
-- признаком, бизнес-id казино и комментарием оператора)
INSERT INTO retention.money_transactions
  (transaction_row_id, transaction_id, casino_player_id, type, status, amount, currency,
   payment_method, is_manual, description, created_at)
SELECT event_id, transaction_id, casino_player_id, event_type, status, amount, currency,
   payment_method, is_manual, description, ts
FROM retention.live_events FINAL
WHERE event_type IN ('deposit','withdrawal','bonus')
  AND ingested_at > toDateTime64('$WM', 3) AND ingested_at <= toDateTime64('$UPPER', 3)
  AND event_id NOT IN (SELECT transaction_row_id FROM retention.money_transactions
                       WHERE created_at > toDateTime64('$MINTS', 3) - INTERVAL 1 DAY);

-- завершённые сессии -> game_sessions (когда session_end попал в окно)
INSERT INTO retention.game_sessions
  (session_row_id, session_id, casino_player_id, aggregator, game_uuid,
   currency, status, is_active, duration_minutes, created_at)
SELECT session_id, session_id, casino_player_id, any(provider), any(game_uuid),
  any(currency), 'closed', 'false',
  toFloat64(dateDiff('minute', min(ts), max(ts))), min(ts)
FROM retention.live_events FINAL
WHERE session_id != '' AND event_type IN ('bet','win','session_start','session_end')
GROUP BY casino_player_id, session_id
HAVING countIf(event_type='session_end' AND ingested_at > toDateTime64('$WM',3) AND ingested_at <= toDateTime64('$UPPER',3)) > 0
   AND session_id NOT IN (SELECT session_id FROM retention.game_sessions
                          WHERE created_at > now() - INTERVAL 7 DAY);

-- новые игроки из потока -> users (существующим профиль обновляет дамп казино)
INSERT INTO retention.users
  (casino_player_id, account_type, activity_status, country_iso_estimated, currency,
   reg_date, ftd_date, ftd_amount, affiliate_account_type, affiliate_code,
   phone_verified, email_verified, status, is_active, last_login, last_active,
   balance, bonus_balance)
SELECT casino_player_id, account_type, activity_status, country, currency,
  reg_date, ftd_date, ftd_amount, affiliate_type, affiliate_code,
  phone_verified, email_verified, account_status, is_active, last_login, last_active,
  balance, bonus_balance
FROM retention.users_stream FINAL
WHERE casino_player_id NOT IN (SELECT casino_player_id FROM retention.users);

-- справочник игр (game_uuid -> название): копится из потока, покрывает и старый дамп,
-- где названий не было. Словарь dict_game_names перечитывает его сам (LIFETIME 5 мин).
INSERT INTO retention.game_names (game_uuid, game_name, provider)
SELECT game_uuid, argMax(game_name, ts), argMax(provider, ts)
FROM retention.live_events
WHERE game_name != '' AND game_uuid != ''
  AND ingested_at > toDateTime64('$WM', 3) AND ingested_at <= toDateTime64('$UPPER', 3)
GROUP BY game_uuid;

-- сдвигаем watermark только после успешных вставок
INSERT INTO retention.sync_state (key, wm) VALUES ('live_events', toDateTime64('$UPPER', 3));
SQL
echo "[$(ts)] sync: готово · игр в справочнике: $(CHQ 'SELECT count() FROM (SELECT DISTINCT game_uuid FROM retention.game_names)')"

# ---------------------------------------------------------------- 2) FEATURES
CHM < player_features.sql
echo "[$(ts)] features: player_features пересобрана ($(CHQ 'SELECT count() FROM retention.player_features') строк)"

# ---------------------------------------------------------------- 2b) CRM DIRECTORY
# Наполняем crm.player_directory (Postgres/Supabase) свежим срезом игроков — из него
# живут /pool и /affiliate + RLS-хелперы (affiliate/vip/dept_player_ids). Не критично
# для потока казино: сбой логируем, но цикл НЕ рушим (в отличие от score с exit 1).
# DSN берём из .env, а не из окружения: под cron'ом переменных шелла нет, и sync
# молча пропускался бы каждый тик. Здесь нужен ХОСТОВОЙ адрес (127.0.0.1:54322) —
# в отличие от контейнера борда, который ходит через host.docker.internal.
SUPABASE_DB_URL="${SUPABASE_DB_URL:-$(sed -n 's/^SUPABASE_DB_URL=//p' .env)}"
if [ -z "$SUPABASE_DB_URL" ]; then
  echo "[$(ts)] directory: SUPABASE_DB_URL не задан — sync каталога пропущен"
else
  # Запускаем В КОНТЕЙНЕРЕ борда, а не на хосте: там уже есть flask/psycopg/
  # clickhouse_connect и весь пакет api/, и там же правильные адреса
  # (SUPABASE_DB_URL -> host.docker.internal, CH_HOST -> clickhouse).
  # На хосте системный python3 этих зависимостей не имеет, а держать ради
  # одного скрипта отдельный .venv — лишняя сущность.
  if docker exec retention-board-board-1 python -m api.directory_sync \
       > /tmp/dir_sync.json 2>/tmp/dir_sync.err; then
    echo "[$(ts)] directory: $(cat /tmp/dir_sync.json)"
  else
    echo "[$(ts)] directory: sync НЕ удался (см. /tmp/dir_sync.err) — пропускаю"
  fi
fi

# ---------------------------------------------------------------- 2c) SNAPSHOT
# Ежедневный срез состояния игрока -> retention.player_state_daily (задел
# исторических сегментов и конструктора отчётов: «кто БЫЛ VIP / в оттоке в феврале»).
# Единственный источник схемы и запроса — player_state_daily.sql. DDL идемпотентен
# (IF NOT EXISTS) — применяем каждый прогон. Сам INSERT — не чаще раза в сутки на
# ДАТУ ДАННЫХ (data_asof = max дата завершённых ставок), а НЕ на календарный день:
# гард сравнивает max(snap_date) со свежей data_asof и вставляет, только если срез
# отстаёт (при догрузке данных задним числом срез ложится на верную дату).
# Идемпотентность самого INSERT — на ReplacingMergeTree по (snap_date,id): повторные
# вставки схлопываются, читать через FINAL. Сбой снапшота НЕ рушит петлю — это
# задел-аналитика, а не поток казино.
CHQ "$(sed -n '/^CREATE TABLE/,/;/p' player_state_daily.sql)"   # DDL — каждый прогон
SNAP_LAST=$(CHQ "SELECT toString(max(snap_date)) FROM retention.player_state_daily")
SNAP_ASOF=$(CHQ "SELECT toString(max(toDate(created_at))) FROM retention.game_transactions WHERE status='completed'")
if [ -z "$SNAP_LAST" ] || [[ "$SNAP_LAST" < "$SNAP_ASOF" ]]; then
  if sed -n '/^INSERT INTO/,$p' player_state_daily.sql | CHM; then
    echo "[$(ts)] snapshot: срез записан на $SNAP_ASOF ($(CHQ "SELECT count() FROM retention.player_state_daily FINAL WHERE snap_date='$SNAP_ASOF'") игроков)"
  else
    echo "[$(ts)] snapshot: INSERT НЕ удался — пропускаю (петля продолжается)"
  fi
else
  echo "[$(ts)] snapshot: срез на $SNAP_LAST уже актуален (data_asof=$SNAP_ASOF) — пропуск"
fi

# ---------------------------------------------------------------- 2d) MATERIALIZE SEGMENTS
# Пересчёт членства сегментов конструктора -> retention.segment_members. Читает
# активные определения из automation.segments (Postgres), компилирует и наполняет
# CH. Каждый прогон (быстро: маленькая таблица, DELETE-перед-INSERT синхронно) —
# и суточные, и триггерные сегменты держатся свежими. Запускаем В КОНТЕЙНЕРЕ борда
# (там flask/psycopg/clickhouse_connect и пакет api/, правильные адреса CH/PG) —
# как directory_sync выше. Сбой НЕ рушит петлю: это задел-автоматизация, не поток.
if docker exec retention-board-board-1 python materialize_segments.py \
     > /tmp/materialize_segments.log 2>&1; then
  echo "[$(ts)] segments: $(tail -1 /tmp/materialize_segments.log)"
else
  echo "[$(ts)] segments: материализация НЕ удалась (см. /tmp/materialize_segments.log) — пропускаю"
fi

# ---------------------------------------------------------------- 3) SCORE
# warm-сервис (секунды). 409 = скоринг уже идёт: ждём и пробуем ещё раз.
# Только если сервис реально недоступен/упал — fallback на одноразовый контейнер.
score_once() { curl -s -o /tmp/score_out.json -w '%{http_code}' -X POST --max-time 180 http://127.0.0.1:8099/score 2>/dev/null; }
CODE=$(score_once)
if [ "$CODE" = "409" ]; then
  echo "[$(ts)] score: занято (параллельный скоринг), жду 30с и повторяю"
  sleep 30
  CODE=$(score_once)
fi
if [ "$CODE" = "200" ]; then
  echo "[$(ts)] score: ок (warm, $(grep -o '"took_s": *[0-9.]*' /tmp/score_out.json | grep -o '[0-9.]*')с)"
elif [ "$CODE" = "409" ]; then
  echo "[$(ts)] score: всё ещё занято — пропускаю скоринг в этом цикле (сигналы уйдут по прошлым скорам)"
else
  echo "[$(ts)] score: warm-сервис недоступен (HTTP $CODE), fallback на одноразовый контейнер"
  SCORE_ONLY=1 docker compose run --rm scorer > /tmp/retention_score.log 2>&1 \
    && echo "[$(ts)] score: ок (fallback)" \
    || { echo "[$(ts)] score: ОШИБКА (см. /tmp/retention_score.log)"; exit 1; }
fi

# ---------------------------------------------------------------- 4) PUSH
# Отправляем в казино ТОЛЬКО при явном PREDICTIONS_ENABLED=1 в .env (скоринг для
# витрины выше выполняется в любом случае). Перечитывается каждый тик.
#
# FAIL-CLOSED. Раньше условие было `= "0"` -> пропустить, иначе отправить: если
# .env недоступен или строку удалили, sed возвращал пусто, это не «0», и сигналы
# уходили игрокам. Авария не должна приводить к отправке — молчание чинится одной
# строкой в .env, а разосланные бонусы уже не отозвать.
PRED=$(sed -n 's/^PREDICTIONS_ENABLED=//p' .env | head -1 | tr -d '"'"'"' ' | tr 'A-Z' 'a-z')
case "$PRED" in
  1|true|yes|on)
    docker compose run --rm pusher 2>&1 | grep -E 'signals' | sed "s/^/[$(ts)] push: /" ;;
  *)
    echo "[$(ts)] push: пропущен — отправка выключена (PREDICTIONS_ENABLED='${PRED}')" ;;
esac

echo "[$(ts)] loop: завершено"
