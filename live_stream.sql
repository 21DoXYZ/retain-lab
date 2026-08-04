-- ============================================================================
-- Стрим-контур приёма (v2): Redpanda(Kafka) -> ClickHouse.
-- Расширенный контракт: несёт всё, что нужно и для /live, и для МОДЕЛЕЙ
-- (профиль игрока, статусы денежных операций, фриспины, провайдер, способ оплаты).
--
-- Типы событий (event_type):
--   user                         — профиль игрока (upsert): регистрация/обновление
--   bet, win                     — игровые (с флагом is_freespin и провайдером)
--   deposit, withdrawal, bonus   — денежные (со status и payment_method)
--   session_start, session_end   — сессии
--
-- Поля по типам — см. INTEGRATION.md и генератор casino-event-simulator.
-- ============================================================================

-- ---------------------------------------------------------------- ОЧЕРЕДЬ (Kafka engine)
-- Широкая: все возможные поля всех типов (лишние в конкретном событии просто пустые).
DROP TABLE IF EXISTS retention.live_events_queue;
CREATE TABLE retention.live_events_queue
(
    `event_id`         String,
    `event_type`       String,
    `casino_player_id` UInt32,
    `ts`               DateTime64(3),
    -- активность (game/money)
    `session_id`       String,
    `game_uuid`        String,
    `game_name`        String,        -- человекочитаемое название игры (v2.1)
    `provider`         String,
    `bet_amount`       Decimal(18, 2),
    `win_amount`       Decimal(18, 2),
    `amount`           Decimal(18, 2),
    `is_freespin`      UInt8,
    `currency`         String,
    `balance_after`    Decimal(18, 2),
    `status`           String,          -- для deposit/withdrawal/bonus: completed/rejected/failed/pending
    `payment_method`   String,
    `is_manual`        UInt8,             -- ручная операция (0/1); либо event_type='manual_*'
    `transaction_id`   String,            -- бизнес-id транзакции казино (не наш event_id)
    `description`      String,            -- комментарий оператора (напр. «30 katı kuralı»)
    `bonus_id`         String,            -- id бонуса в системе казино: склейка выдачи с цепочкой bonus_status
    `bonus_code`       String,            -- код акции (deposit_reload_50)
    `bonus_name`       String,            -- человекочитаемое название («Reload 50%»)
    -- профиль (event_type='user')
    `account_type`     String,
    `account_status`   String,
    `activity_status`  String,
    `is_active`        String,
    `country`          String,
    `reg_date`         Nullable(DateTime64(3)),
    `ftd_date`         Nullable(DateTime64(3)),
    `ftd_amount`       Nullable(Decimal(18, 2)),
    `affiliate_code`   String,
    `affiliate_type`   String,
    `phone_verified`   String,
    `email_verified`   String,
    `balance`          Nullable(Decimal(18, 2)),
    `bonus_balance`    Nullable(Decimal(18, 2)),
    `last_login`       Nullable(DateTime64(3)),
    `last_active`      Nullable(DateTime64(3))
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'redpanda:9092',
    kafka_topic_list  = 'casino.events',
    kafka_group_name  = 'ch-live-ingest',
    kafka_format      = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_flush_interval_ms = 500,
    date_time_input_format = 'best_effort',
    input_format_skip_unknown_fields = 1,
    input_format_null_as_default = 1,
    kafka_handle_error_mode = 'stream';

-- ---------------------------------------------------------------- LIVE-АКТИВНОСТЬ (для /live)
-- DROP: в проде вместо этого ALTER ADD COLUMN; сейчас таблица тестовая — пересоздаём.
DROP TABLE IF EXISTS retention.live_events;
CREATE TABLE retention.live_events
(
    `event_id`         String,
    `event_type`       LowCardinality(String),
    `casino_player_id` UInt32,
    `session_id`       String,
    `game_uuid`        String,
    `game_name`        String,        -- человекочитаемое название игры (v2.1)
    `provider`         String,
    `amount`           Decimal(18, 2),
    `bet_amount`       Decimal(18, 2),
    `win_amount`       Decimal(18, 2),
    `is_freespin`      UInt8,
    `currency`         LowCardinality(String),
    `balance_after`    Decimal(18, 2),
    `status`           LowCardinality(String),
    `payment_method`   LowCardinality(String),
    `is_manual`        UInt8,
    `transaction_id`   String,
    `description`      String,
    `bonus_id`         String,
    `bonus_code`       String,
    `bonus_name`       String,
    `ts`               DateTime64(3),
    `ingested_at`      DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMMDD(ts)
ORDER BY (casino_player_id, ts, event_id);

-- Нормализация ручных операций: казино может слать признак ДВУМЯ способами —
--   1) event_type='deposit' + is_manual=1
--   2) event_type='manual_deposit' (без флага)
-- Приводим к единому виду: базовый event_type + is_manual=1. Читателям (витрина,
-- модели) не нужно знать, каким способом прислали.
DROP VIEW IF EXISTS retention.live_events_mv;
CREATE MATERIALIZED VIEW retention.live_events_mv TO retention.live_events AS
SELECT event_id,
       if(startsWith(raw_type, 'manual_'), substring(raw_type, 8), raw_type) AS event_type,
       casino_player_id, session_id, game_uuid, game_name, provider,
       amount, bet_amount, win_amount, is_freespin, currency, balance_after,
       status, payment_method,
       greatest(raw_manual, toUInt8(startsWith(raw_type, 'manual_')))        AS is_manual,
       transaction_id, description, bonus_id, bonus_code, bonus_name, ts
FROM (
    SELECT *, event_type AS raw_type, is_manual AS raw_manual
    FROM retention.live_events_queue
    WHERE event_type IN ('bet','win','session_start','session_end',
                         'deposit','withdrawal','bonus',
                         'manual_deposit','manual_withdrawal','manual_bonus')
);

-- ---------------------------------------------------------------- ПРОФИЛЬ ИГРОКА (из потока)
-- Снапшот пользователя из событий event_type='user' (upsert по casino_player_id).
-- Отсюда позже материализуем в сырую таблицу users для витрины/моделей.
CREATE TABLE IF NOT EXISTS retention.users_stream
(
    `casino_player_id` UInt32,
    `account_type`     LowCardinality(String),
    `account_status`   LowCardinality(String),
    `activity_status`  LowCardinality(String),
    `is_active`        String,
    `country`          LowCardinality(String),
    `currency`         LowCardinality(String),
    `reg_date`         Nullable(DateTime64(3)),
    `ftd_date`         Nullable(DateTime64(3)),
    `ftd_amount`       Nullable(Decimal(18, 2)),
    `affiliate_code`   String,
    `affiliate_type`   String,
    `phone_verified`   String,
    `email_verified`   String,
    `balance`          Nullable(Decimal(18, 2)),
    `bonus_balance`    Nullable(Decimal(18, 2)),
    `last_login`       Nullable(DateTime64(3)),
    `last_active`      Nullable(DateTime64(3)),
    `updated_at`       DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY casino_player_id;

DROP VIEW IF EXISTS retention.users_stream_mv;
CREATE MATERIALIZED VIEW retention.users_stream_mv TO retention.users_stream AS
SELECT casino_player_id, account_type, account_status, activity_status, is_active,
       country, currency, reg_date, ftd_date, ftd_amount, affiliate_code, affiliate_type,
       phone_verified, email_verified, balance, bonus_balance, last_login, last_active,
       ts AS updated_at
FROM retention.live_events_queue
WHERE event_type = 'user';

-- ---------------------------------------------------------------- БОНУС-СТАТУСЫ (bonus_status)
-- ⚠ ТОЛЬКО ТАМ, ГДЕ ЕСТЬ БРОКЕР (VPS с redpanda). На локальной машине без брокера
-- Kafka-таблицу держать ОТСОЕДИНЁННОЙ: DETACH TABLE retention.bonus_events_queue
-- PERMANENTLY (и bonus_events_mv) — CH 26.2 после часов ретраев «Can't get
-- assignment» падает с Fatal (проверено 17.07.2026).
-- Жизненный цикл бонусов (выдан → активирован → отыгран/сгорел/отменён).
-- Отдельная очередь на ТОТ ЖЕ топик, но со СВОЕЙ consumer-group (ch-bonus-ingest):
-- иначе конкурировала бы с ch-live-ingest за партиции и события терялись бы.
-- Целевая таблица retention.bonus_events и вьюха bonus_status_current — в schema.sql.
-- Контракт события — new_u/Запрос_казино_события_бонусов.md.
CREATE TABLE IF NOT EXISTS retention.bonus_events_queue
(
    `event_id`             String,
    `event_type`           String,
    `casino_player_id`     UInt32,
    `ts`                   DateTime64(3),
    `bonus_id`             String,
    `bonus_code`           String,
    `bonus_name`           String,
    `status`               String,
    `amount`               Nullable(Decimal(18, 2)),
    `currency`             String,
    `wager_requirement`    Nullable(Decimal(18, 2)),
    `wager_multiplier`     Nullable(Decimal(10, 2)),
    `wagered_amount`       Nullable(Decimal(18, 2)),
    `expires_at`           Nullable(DateTime64(3)),
    `money_transaction_id` String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'redpanda:9092',
    kafka_topic_list  = 'casino.events',
    kafka_group_name  = 'ch-bonus-ingest',
    kafka_format      = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_flush_interval_ms = 500,
    date_time_input_format = 'best_effort',
    input_format_skip_unknown_fields = 1,
    input_format_null_as_default = 1,
    kafka_handle_error_mode = 'stream';

-- Маршрут: событие bonus_status → строка жизненного цикла в bonus_events.
CREATE MATERIALIZED VIEW IF NOT EXISTS retention.bonus_events_mv TO retention.bonus_events AS
SELECT event_id, casino_player_id, bonus_id, bonus_code, bonus_name, status,
       amount, currency, wager_requirement, wager_multiplier, wagered_amount,
       expires_at, money_transaction_id, ts AS status_at
FROM retention.bonus_events_queue
WHERE event_type = 'bonus_status';
