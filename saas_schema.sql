-- ============================================================================
-- Revenue Autopilot (SaaS-пресет) — контур данных Phase 1 (REBUILD-TASK.md).
-- Отдельный от казино-контура: свой топик saas.events, свои таблицы, всё с
-- tenant_id (мульти-тенант с первого дня, §0.7). Применение:
--   docker compose ... exec -T clickhouse clickhouse-client --password $CH_PASSWORD \
--     --multiquery < saas_schema.sql
-- Идемпотентно: queue/MV пересоздаются, данные (MergeTree) не трогаются.
-- ============================================================================

-- ---------------------------------------------------------------- ПОТОК СОБЫТИЙ
-- Единая шина: события продукта (сниппет/API) + биллинга (Stripe-адаптер).
-- Словарь event_type — Шпаргалка §1 (usage) + billing.* (Stripe-маппер).
CREATE TABLE IF NOT EXISTS retention.saas_events
(
    `event_id`           String,
    `tenant_id`          LowCardinality(String),
    `event_type`         LowCardinality(String),
    `ts`                 DateTime64(3),
    `source`             LowCardinality(String),   -- stripe | snippet | api
    -- идентификация (любое подмножество; склейка — identity stitching)
    `client_user_id`     String,                    -- id юзера на стороне продукта
    `email_hash`         String,                    -- sha256(lower(trim(email)))
    `stripe_customer_id` String,
    -- биллинг-поля (события billing.*)
    `amount`             Decimal(18, 2),
    `currency`           LowCardinality(String),
    `plan_id`            String,
    `subscription_id`    String,
    `invoice_id`         String,
    `charge_id`          String,
    `status`             LowCardinality(String),
    -- usage-поля (события сниппета/API)
    `session_id`         String,
    `page`               String,
    `tokens_spent`       Int64,
    `tokens_balance`     Int64,
    `meta`               String,                    -- JSON-строка с остальным
    `ingested_at`        DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (tenant_id, ts, event_type);

-- Очередь объявлена явно (не AS saas_events): Kafka engine не поддерживает
-- DEFAULT-колонки, поэтому без ingested_at — его проставит целевая таблица.
DROP TABLE IF EXISTS retention.saas_events_queue;
CREATE TABLE retention.saas_events_queue
(
    `event_id`           String,
    `tenant_id`          LowCardinality(String),
    `event_type`         LowCardinality(String),
    `ts`                 DateTime64(3),
    `source`             LowCardinality(String),
    `client_user_id`     String,
    `email_hash`         String,
    `stripe_customer_id` String,
    `amount`             Decimal(18, 2),
    `currency`           LowCardinality(String),
    `plan_id`            String,
    `subscription_id`    String,
    `invoice_id`         String,
    `charge_id`          String,
    `status`             LowCardinality(String),
    `session_id`         String,
    `page`               String,
    `tokens_spent`       Int64,
    `tokens_balance`     Int64,
    `meta`               String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'redpanda:9092',
    kafka_topic_list  = 'saas.events',
    kafka_group_name  = 'ch-saas-ingest',
    kafka_format      = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_flush_interval_ms = 500,
    date_time_input_format = 'best_effort',
    input_format_skip_unknown_fields = 1,
    input_format_null_as_default = 1,
    kafka_handle_error_mode = 'stream';

DROP VIEW IF EXISTS retention.saas_events_mv;
CREATE MATERIALIZED VIEW retention.saas_events_mv TO retention.saas_events AS
SELECT * FROM retention.saas_events_queue
WHERE length(_error) = 0;

-- ---------------------------------------------------------------- STRIPE RAW
-- Снимки объектов Stripe (backfill + вебхуки). ReplacingMergeTree по updated_at:
-- каждое обновление — новая строка, витрины читают argMax/FINAL.
CREATE TABLE IF NOT EXISTS retention.stripe_customers
(
    `tenant_id`   LowCardinality(String),
    `customer_id` String,
    `email`       String,
    `email_norm`  String,
    `email_hash`  String,
    `name`        String,
    `created_ts`  DateTime64(3),
    `meta`        String,
    `updated_at`  DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, customer_id);

CREATE TABLE IF NOT EXISTS retention.stripe_subscriptions
(
    `tenant_id`            LowCardinality(String),
    `subscription_id`      String,
    `customer_id`          String,
    `status`               LowCardinality(String),  -- trialing/active/past_due/canceled/...
    `plan_id`              String,
    `price_id`             String,
    `amount`               Decimal(18, 2),
    `currency`             LowCardinality(String),
    `bill_interval`        LowCardinality(String),  -- month | year
    `current_period_start` DateTime64(3),
    `current_period_end`   DateTime64(3),
    `trial_start`          Nullable(DateTime64(3)),
    `trial_end`            Nullable(DateTime64(3)),
    `cancel_at`            Nullable(DateTime64(3)),
    `canceled_at`          Nullable(DateTime64(3)),
    `created_ts`           DateTime64(3),
    `updated_at`           DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, subscription_id);

CREATE TABLE IF NOT EXISTS retention.stripe_invoices
(
    `tenant_id`            LowCardinality(String),
    `invoice_id`           String,
    `customer_id`          String,
    `subscription_id`      String,
    `status`               LowCardinality(String),  -- draft/open/paid/void/uncollectible
    `amount_due`           Decimal(18, 2),
    `amount_paid`          Decimal(18, 2),
    `currency`             LowCardinality(String),
    `attempt_count`        UInt8,
    `next_payment_attempt` Nullable(DateTime64(3)),
    `created_ts`           DateTime64(3),
    `updated_at`           DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, invoice_id);

CREATE TABLE IF NOT EXISTS retention.stripe_charges
(
    `tenant_id`   LowCardinality(String),
    `charge_id`   String,
    `customer_id` String,
    `invoice_id`  String,
    `amount`      Decimal(18, 2),
    `currency`    LowCardinality(String),
    `status`      LowCardinality(String),
    `refunded`    UInt8,
    `created_ts`  DateTime64(3),
    `updated_at`  DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, charge_id);

-- ---------------------------------------------------------------- IDENTITY
-- Склейка Stripe customer ↔ сниппет client_user_id ↔ product user по email_hash
-- (правила — stripe_sync/stitch.py). Пересборка джобой: Replacing по ключу.
CREATE TABLE IF NOT EXISTS retention.identities
(
    `tenant_id`          LowCardinality(String),
    `identity_id`        String,                    -- стабильный uuid склейки
    `email_hash`         String,
    `email_norm`         String,                    -- есть только если источник дал email (Stripe)
    `stripe_customer_id` String,
    `client_user_id`     String,
    `sources`            Array(LowCardinality(String)),
    `first_seen`         DateTime64(3),
    `updated_at`         DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, identity_id);

-- Очередь несшитого: то, что не удалось привязать автоматически (acceptance §1.3
-- требует ≥95% авто-склейки — остаток виден здесь, разбирается руками/правилами).
CREATE TABLE IF NOT EXISTS retention.identity_unmatched
(
    `tenant_id`  LowCardinality(String),
    `source`     LowCardinality(String),
    `key_type`   LowCardinality(String),   -- client_user_id | stripe_customer_id | email_hash
    `key_value`  String,
    `reason`     String,
    `ts`         DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (tenant_id, ts);

-- ---------------------------------------------------------------- MRR (минимум Phase 1)
-- Нормализованный месячный MRR по активным/триальным подпискам (последний снимок).
CREATE OR REPLACE VIEW retention.mrr_facts AS
SELECT
    tenant_id,
    subscription_id,
    argMax(customer_id, updated_at)                    AS customer_id,
    argMax(status, updated_at)                         AS status,
    argMax(plan_id, updated_at)                        AS plan_id,
    argMax(currency, updated_at)                       AS currency,
    if(argMax(bill_interval, updated_at) = 'year',
       round(argMax(amount, updated_at) / 12, 2),
       argMax(amount, updated_at))                     AS mrr
FROM retention.stripe_subscriptions
GROUP BY tenant_id, subscription_id
HAVING status IN ('active', 'trialing', 'past_due');
