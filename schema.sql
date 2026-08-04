-- ============================================================================
-- Схема БД retention: база + 4 исходные таблицы (ClickHouse / MergeTree).
-- Запуск:  clickhouse client --multiquery < schema.sql
-- Данные сюда заливаются отдельно (из локального ClickHouse или из CSV) — см. SETUP.md
-- ============================================================================

CREATE DATABASE IF NOT EXISTS retention;

-- ---------------------------------------------------------------- users
CREATE TABLE IF NOT EXISTS retention.users
(
    `casino_player_id` UInt32,
    `display_id` String,
    `username` String,
    `email` String,
    `phone` String,
    `phone_country_code` String,
    `country_iso_estimated` LowCardinality(String),
    `country_name` LowCardinality(String),
    `currency` LowCardinality(String),
    `reg_date` Nullable(DateTime64(3)),
    `ftd_date` Nullable(DateTime64(3)),
    `ftd_amount` Nullable(Decimal(18, 2)),
    `last_active` Nullable(DateTime64(3)),
    `activity_status` LowCardinality(String),
    `account_type` LowCardinality(String),
    `account_type_reason` String,
    `role` LowCardinality(String),
    `status` LowCardinality(String),
    `is_active` String,
    `is_real_player_candidate` String,
    `phone_verified` String,
    `email_verified` String,
    `timezone` LowCardinality(String),
    `marketing_consent` String,
    `marketing_consent_at` String,
    `marketing_consent_source` String,
    `service_consent` String,
    `service_consent_at` String,
    `service_consent_source` String,
    `self_excluded` String,
    `rg_flag` String,
    `risk_tags` String,
    `opt_out` String,
    `do_not_contact` String,
    `telegram_id` String,
    `telegram_username` String,
    `has_whatsapp` String,
    `has_viber` String,
    `affiliate_db_id` String,
    `affiliate_code` String,
    `affiliate_username` String,
    `affiliate_account_type` String,
    `traffic_link_code` String,
    `traffic_sub_id` String,
    `balance` Nullable(Decimal(18, 2)),
    `bonus_balance` Nullable(Decimal(18, 2)),
    `total_deposits_lifetime` Nullable(Decimal(18, 2)),
    `total_withdrawals_lifetime` Nullable(Decimal(18, 2)),
    `total_bets_lifetime` Nullable(Decimal(18, 2)),
    `total_wins_lifetime` Nullable(Decimal(18, 2)),
    `created_at` Nullable(DateTime64(3)),
    `last_login` Nullable(DateTime64(3)),
    `registration_source` String,
    `click_id` String,
    `aggregate_id` String
)
ENGINE = MergeTree ORDER BY casino_player_id;

-- ------------------------------------------------------- money_transactions
CREATE TABLE IF NOT EXISTS retention.money_transactions
(
    `transaction_row_id` String,
    `transaction_id` String,
    `casino_player_id` UInt32,
    `type` LowCardinality(String),
    `status` LowCardinality(String),
    `amount` Decimal(18, 2),
    `currency` LowCardinality(String),
    `payment_method` LowCardinality(String),
    `payment_details` String,
    `reference_id` String,
    `balance_before` Nullable(Decimal(18, 2)),
    `balance_after` Nullable(Decimal(18, 2)),
    `bonus_balance_before` Nullable(Decimal(18, 2)),
    `bonus_balance_after` Nullable(Decimal(18, 2)),
    `fees` Nullable(Decimal(18, 2)),
    `exchange_rate` Nullable(Decimal(18, 6)),
    `assigned_bank_id` String,
    `assigned_bank_name` String,
    `description` String,
    `rejection_reason` String,
    `reviewed_by` String,
    `notes` String,
    `created_at` DateTime64(3),
    `updated_at` Nullable(DateTime64(3)),
    `processed_at` Nullable(DateTime64(3)),
    `sent_at` Nullable(DateTime64(3))
)
ENGINE = MergeTree ORDER BY (casino_player_id, created_at);

-- ------------------------------------------------------- game_transactions
CREATE TABLE IF NOT EXISTS retention.game_transactions
(
    `source_table` LowCardinality(String),
    `transaction_row_id` String,
    `casino_player_id` UInt32,
    `session_id` String,
    `aggregator` LowCardinality(String),
    `game_uuid` String,
    `game_code` String,
    `round_id` String,
    `external_transaction_id` String,
    `reference_transaction_id` String,
    `transaction_type` LowCardinality(String),
    `bet_amount` Decimal(18, 2),
    `win_amount` Decimal(18, 2),
    `amount` Decimal(18, 2),
    `currency` LowCardinality(String),
    `status` LowCardinality(String),
    `balance_before` Decimal(18, 2),
    `balance_after` Decimal(18, 2),
    `balance_source` LowCardinality(String),
    `raw_game_data` String,
    `created_at` DateTime64(3),
    `processed_at` Nullable(DateTime64(3))
)
ENGINE = MergeTree PARTITION BY toYYYYMM(created_at) ORDER BY (casino_player_id, created_at);

-- ---------------------------------------------------------- game_sessions
CREATE TABLE IF NOT EXISTS retention.game_sessions
(
    `session_row_id` String,
    `session_id` String,
    `casino_player_id` UInt32,
    `aggregator` LowCardinality(String),
    `game_uuid` String,
    `mode` LowCardinality(String),
    `device` LowCardinality(String),
    `language` LowCardinality(String),
    `currency` LowCardinality(String),
    `status` LowCardinality(String),
    `is_active` LowCardinality(String),
    `created_at` DateTime64(3),
    `started_at` Nullable(DateTime64(3)),
    `ended_at` Nullable(DateTime64(3)),
    `duration_minutes` Nullable(Float64)
)
ENGINE = MergeTree ORDER BY (casino_player_id, created_at);

-- -------------------------------------------------------- game_names + словарь
-- Справочник «id игры → название/провайдер». На проде эти объекты создаёт луп
-- синхронизации (run_loop.sh: CREATE ... IF NOT EXISTS на каждой итерации), а
-- наполняет поток казино v2.1 (game_name приходит вместе с игровым событием,
-- см. INSERT в game_transactions.game_name из live_events). В schema.sql DDL
-- раньше НЕ БЫЛО → после пересоздания БД локаль отличалась от прода и GN()
-- (player_board.py:93) валилась в фолбэк «id …». Дублируем DDL здесь ради
-- паритета локали с продом; все стейтменты идемпотентны (IF NOT EXISTS).
-- Наполнение: поток v2.1 (SYNC-инсерт в run_loop.sh) либо ручной INSERT.
-- Сигнатура сверена с фактическими вызовами по коду: dictGet(...,'game_name',...)
-- в GN() и dictGetOrDefault(...,'provider',...) в provider_cost_total()/GGR —
-- читаются только game_name и provider (studio/cost из словаря НЕ берутся).
CREATE TABLE IF NOT EXISTS retention.game_names
(
    `game_uuid`  String,
    `game_name`  String,
    `provider`   String,
    `updated_at` DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at) ORDER BY game_uuid;

-- Словарь поверх game_names: ключ game_uuid (String) → COMPLEX_KEY_HASHED,
-- атрибуты с дефолтом '' (GN() сам обрабатывает пустоту → усечённый «id …»).
-- ОТЛИЧИЕ ОТ ПРОДА: там SOURCE несёт USER 'default' PASSWORD '$PASS' из .env
-- (run_loop.sh подставляет через shell). schema.sql применяется голым
-- `clickhouse client < schema.sql` без подстановки — поэтому SOURCE здесь без
-- пароля (локальный default беспарольный). Кредо-версию на проде ведёт
-- run_loop.sh (тоже IF NOT EXISTS). LIFETIME(MIN 300 MAX 600) — как на проде.
CREATE DICTIONARY IF NOT EXISTS retention.dict_game_names
(
    `game_uuid`  String,
    `game_name`  String DEFAULT '',
    `provider`   String DEFAULT ''
)
PRIMARY KEY game_uuid
SOURCE(CLICKHOUSE(TABLE 'game_names' DB 'retention'))
LAYOUT(COMPLEX_KEY_HASHED())
LIFETIME(MIN 300 MAX 600);

-- ------------------------------------------------------------ bonus_events
-- Жизненный цикл бонусов: issued → activated → wagering_completed / expired / cancelled.
-- Наполняется событием bonus_status (контракт — new_u/Запрос_казино_события_бонусов.md);
-- сама ВЫДАЧА (движение денег) остаётся строкой в money_transactions.
-- Одна строка = одна смена статуса; текущее состояние бонуса — во вьюхе bonus_status_current.
CREATE TABLE IF NOT EXISTS retention.bonus_events
(
    `event_id` String,
    `casino_player_id` UInt32,
    `bonus_id` String,
    `bonus_code` LowCardinality(String),
    `bonus_name` String,
    `status` LowCardinality(String),
    `amount` Nullable(Decimal(18, 2)),
    `currency` LowCardinality(String),
    `wager_requirement` Nullable(Decimal(18, 2)),
    `wager_multiplier` Nullable(Decimal(10, 2)),
    `wagered_amount` Nullable(Decimal(18, 2)),
    `expires_at` Nullable(DateTime64(3)),
    `money_transaction_id` String,
    `status_at` DateTime64(3),
    `ingested_at` DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at) ORDER BY (casino_player_id, bonus_id, status, status_at);

-- Текущее состояние каждого бонуса (последний статус по времени) — для карточки игрока.
CREATE VIEW IF NOT EXISTS retention.bonus_status_current AS
SELECT
    casino_player_id,
    bonus_id,
    argMax(status, status_at)            AS status,
    argMax(bonus_code, status_at)        AS bonus_code,
    argMax(bonus_name, status_at)        AS bonus_name,
    argMax(amount, status_at)            AS amount,
    argMax(currency, status_at)          AS currency,
    argMax(wager_requirement, status_at) AS wager_requirement,
    argMax(wager_multiplier, status_at)  AS wager_multiplier,
    argMax(wagered_amount, status_at)    AS wagered_amount,
    argMax(money_transaction_id, status_at) AS money_transaction_id,
    minIf(status_at, bonus_events.status = 'issued') AS issued_at,
    max(status_at)                       AS last_status_at
FROM retention.bonus_events
GROUP BY casino_player_id, bonus_id;
