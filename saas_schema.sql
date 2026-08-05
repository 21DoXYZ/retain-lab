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

-- ============================================================================
-- Phase 2 — Domain: планы, скоры, резолв событий в identity, стадии+действия.
-- ============================================================================

-- Конфиг планов тенанта (лимиты токенов — для burn rate; ТЗ §13: допущения,
-- реальные значения заводятся при онбординге тенанта).
CREATE TABLE IF NOT EXISTS retention.tenant_plans
(
    `tenant_id`      LowCardinality(String),
    `plan_id`        String,
    `monthly_tokens` UInt32,
    `mrr`            Decimal(18, 2),
    `updated_at`     DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, plan_id);

CREATE OR REPLACE VIEW retention.tenant_plans_current AS
SELECT tenant_id, plan_id,
       argMax(monthly_tokens, updated_at) AS monthly_tokens,
       argMax(mrr, updated_at)            AS mrr
FROM retention.tenant_plans
GROUP BY tenant_id, plan_id;

-- Скоры: append-only история прогонов (контракт под будущий ML — §0.5),
-- текущий срез — вьюха user_scores_current.
CREATE TABLE IF NOT EXISTS retention.user_scores
(
    `tenant_id`    LowCardinality(String),
    `identity_id`  String,
    `p_convert`    Float64,
    `p_churn`      Float64,
    `ltv_estimate` Float64,
    `power_score`  Float64,
    `features`     String,                  -- JSON фич, из которых собраны скоры
    `version`      LowCardinality(String),  -- напр. heur-v1
    `scored_at`    DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (tenant_id, identity_id, scored_at);

CREATE OR REPLACE VIEW retention.user_scores_current AS
SELECT tenant_id, identity_id,
       argMax(p_convert, scored_at)    AS p_convert,
       argMax(p_churn, scored_at)      AS p_churn,
       argMax(ltv_estimate, scored_at) AS ltv_estimate,
       argMax(power_score, scored_at)  AS power_score,
       argMax(version, scored_at)      AS version,
       max(scored_at)                  AS last_scored_at
FROM retention.user_scores
GROUP BY tenant_id, identity_id;

-- Текущий срез identity (Replacing → argMax).
CREATE OR REPLACE VIEW retention.identities_current AS
SELECT tenant_id, identity_id,
       argMax(email_hash, updated_at)         AS email_hash,
       argMax(email_norm, updated_at)         AS email_norm,
       argMax(stripe_customer_id, updated_at) AS stripe_customer_id,
       argMax(client_user_id, updated_at)     AS client_user_id
FROM retention.identities
GROUP BY tenant_id, identity_id;

-- Каждое событие → identity по старшему доступному ключу (ровно один матч):
-- client_user_id > stripe_customer_id > email_hash.
CREATE OR REPLACE VIEW retention.saas_events_resolved AS
SELECT i.identity_id AS identity_id, e.*
FROM retention.saas_events e
JOIN retention.identities_current i
  ON e.tenant_id = i.tenant_id AND e.client_user_id = i.client_user_id
WHERE e.client_user_id != ''
UNION ALL
SELECT i.identity_id, e.*
FROM retention.saas_events e
JOIN retention.identities_current i
  ON e.tenant_id = i.tenant_id AND e.stripe_customer_id = i.stripe_customer_id
WHERE e.client_user_id = '' AND e.stripe_customer_id != ''
UNION ALL
SELECT i.identity_id, e.*
FROM retention.saas_events e
JOIN retention.identities_current i
  ON e.tenant_id = i.tenant_id AND e.email_hash = i.email_hash
WHERE e.client_user_id = '' AND e.stripe_customer_id = '' AND e.email_hash != '';

-- Фичи по событиям per identity (общий источник для стадий и скоринг-джоба).
-- Момент ценности УНИВЕРСАЛЕН: generation_completed (Hub Content) ИЛИ
-- value_moment (канонич. имя для любого продукта, см. INTEGRATION-SAAS.md).
-- Иначе ACTIVATE/SAVE-математика мертва для тенантов с другим словарём.
CREATE OR REPLACE VIEW retention.user_event_features AS
SELECT
    tenant_id,
    identity_id,
    min(ts)                                                              AS first_seen,
    max(ts)                                                              AS last_seen,
    countIf(event_type IN ('generation_completed', 'value_moment'))                                  AS generations_total,
    countIf(event_type IN ('generation_completed', 'value_moment') AND ts >= now() - INTERVAL 7 DAY) AS generations_7d,
    countIf(event_type IN ('generation_completed', 'value_moment') AND ts >= now() - INTERVAL 14 DAY
            AND ts < now() - INTERVAL 7 DAY)                             AS generations_prev_7d,
    uniqIf(toDate(ts), event_type IN ('generation_completed', 'value_moment')
           AND ts >= now() - INTERVAL 28 DAY AND ts < now() - INTERVAL 7 DAY) AS gen_days_prior_3w,
    uniqIf(toDate(ts), event_type IN ('generation_completed', 'value_moment')
           AND ts >= toStartOfMonth(now()))                              AS gen_days_this_month,
    countIf(event_type IN ('paywall_viewed', 'plan_page_viewed'))        AS paywall_views,
    countIf(event_type = 'checkout_started')                            AS checkout_starts,
    countIf(event_type = 'cancel_flow_started'
            AND ts >= now() - INTERVAL 14 DAY)                           AS cancel_flow_14d,
    sumIf(tokens_spent, ts >= toStartOfMonth(now()))                     AS tokens_spent_month,
    maxIf(ts, event_type = 'billing.payment_failed')                     AS last_payment_failed,
    maxIf(ts, event_type = 'billing.invoice_paid')                       AS last_invoice_paid,
    maxIf(ts, event_type = 'billing.subscription_cancel_scheduled')      AS last_cancel_scheduled,
    maxIf(ts, event_type NOT LIKE 'billing.%')                           AS last_product_seen
FROM retention.saas_events_resolved
GROUP BY tenant_id, identity_id;

-- Последний снимок подписки per customer.
CREATE OR REPLACE VIEW retention.stripe_subscriptions_current AS
SELECT tenant_id, customer_id,
       argMax(subscription_id, updated_at)  AS subscription_id,
       argMax(status, updated_at)           AS status,
       argMax(plan_id, updated_at)          AS plan_id,
       argMax(amount, updated_at)           AS amount,
       argMax(bill_interval, updated_at)    AS bill_interval,
       argMax(trial_end, updated_at)        AS trial_end,
       argMax(cancel_at, updated_at)        AS cancel_at,
       argMax(canceled_at, updated_at)      AS canceled_at,
       argMax(current_period_end, updated_at) AS current_period_end
FROM retention.stripe_subscriptions
GROUP BY tenant_id, customer_id;

-- ГЛАВНАЯ ВЬЮХА Phase 2: ровно одна стадия + действие на каждого stitched-юзера.
-- Приоритет: DUNNING > WINBACK > CONVERT > SAVE > UPGRADE > ACTIVATE > MONITOR.
-- DUNNING событийный: последний payment_failed новее последнего paid, либо
-- статус подписки past_due — вьюха видит новое событие сразу (без ночного джоба).
CREATE OR REPLACE VIEW retention.user_actions AS
WITH
    if(s.bill_interval = 'year', round(s.amount / 12, 2), s.amount) AS sub_mrr,
    if(p.monthly_tokens > 0, f.tokens_spent_month / p.monthly_tokens, 0) AS burn_rate_calc,
    s.status IN ('active', 'past_due') AS is_paying,
    (f.last_payment_failed > f.last_invoice_paid) OR (s.status = 'past_due') AS dunning_now,
    s.status = 'canceled' AS is_canceled,
    if(is_canceled, dateDiff('day', coalesce(s.canceled_at, s.current_period_end), now()), 0) AS days_since_cancel,
    multiIf(
        dunning_now AND NOT is_canceled,                                   'DUNNING',
        is_canceled AND days_since_cancel >= 30,                           'WINBACK',
        s.status = 'trialing' AND s.trial_end <= now() + INTERVAL 3 DAY,   'CONVERT',
        is_paying AND (f.cancel_flow_14d > 0
                       OR f.last_cancel_scheduled > f.last_invoice_paid
                       OR (f.gen_days_prior_3w >= 9 AND f.generations_7d = 0)), 'SAVE',
        is_paying AND burn_rate_calc >= 0.8,                                    'UPGRADE',
        NOT is_paying AND NOT is_canceled
            AND f.generations_total = 0
            AND coalesce(f.first_seen, now()) <= now() - INTERVAL 48 HOUR, 'ACTIVATE',
        'MONITOR') AS stage_calc
SELECT
    i.tenant_id         AS tenant_id,
    i.identity_id       AS identity_id,
    i.email_norm        AS email_norm,
    i.client_user_id    AS client_user_id,
    i.stripe_customer_id AS stripe_customer_id,
    s.status            AS sub_status,
    s.plan_id           AS plan_id,
    sub_mrr             AS mrr,
    round(burn_rate_calc, 3) AS burn_rate,
    f.generations_7d,
    f.last_seen,
    stage_calc          AS stage,
    multiIf(
        stage_calc = 'ACTIVATE', 'K1_activation',
        stage_calc = 'CONVERT',  'K2_trial_conversion',
        stage_calc = 'DUNNING',  'K3_payment_recovery',
        stage_calc = 'SAVE',     'K4_save',
        stage_calc = 'UPGRADE',  'K5_upgrade',
        stage_calc = 'WINBACK',  'K6_winback',
        'none')         AS recommended_action,
    multiIf(
        stage_calc IN ('DUNNING', 'SAVE'), toFloat64(sub_mrr),
        stage_calc = 'UPGRADE',  toFloat64(sub_mrr) * 0.5,
        stage_calc IN ('CONVERT', 'ACTIVATE', 'WINBACK'), toFloat64(coalesce(p.mrr, 0)),
        0.0)            AS value_at_stake,
    if(is_canceled AND days_since_cancel < 30, 'post_cancel_cooldown', '') AS stage_note,
    sc.p_convert, sc.p_churn, sc.ltv_estimate, sc.power_score,
    sc.last_scored_at AS scored_at
FROM retention.identities_current i
LEFT JOIN retention.stripe_subscriptions_current s
    ON i.tenant_id = s.tenant_id AND i.stripe_customer_id = s.customer_id
LEFT JOIN retention.user_event_features f
    ON i.tenant_id = f.tenant_id AND i.identity_id = f.identity_id
LEFT JOIN retention.tenant_plans_current p
    ON i.tenant_id = p.tenant_id AND s.plan_id = p.plan_id
LEFT JOIN retention.user_scores_current sc
    ON i.tenant_id = sc.tenant_id AND i.identity_id = sc.identity_id;

-- ============================================================================
-- Phase 3 — Offers: лог выдач (holdout/hygiene/dry-run — всё в одной таблице).
-- Каждое РЕШЕНИЕ логируется: issued | dry_run | holdout | rejected. Гигиена
-- (14-дневный кэп) и uplift-отчёты (Phase 6) читают отсюда.
-- ============================================================================
CREATE TABLE IF NOT EXISTS retention.offers_issued
(
    `tenant_id`     LowCardinality(String),
    `offer_id`      LowCardinality(String),
    `identity_id`   String,
    `campaign_id`   LowCardinality(String),
    `holdout`       UInt8,
    `monetary`      UInt8,
    `executor`      LowCardinality(String),
    `params`        String,
    `status`        LowCardinality(String),   -- issued | dry_run | holdout | rejected
    `reason`        String,                    -- машинный код при rejected
    `cost_estimate` Float64,
    `issued_at`     DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (tenant_id, identity_id, issued_at);

-- ============================================================================
-- Phase 4 — Кампании K1-K5 (SaaS-раннер v1, stripe_sync/campaign_tick.py).
-- Определения — saas_campaigns.json (репо); здесь — состояние и лог касаний.
-- ============================================================================
CREATE TABLE IF NOT EXISTS retention.campaign_enrollments
(
    `tenant_id`    LowCardinality(String),
    `campaign_id`  LowCardinality(String),
    `identity_id`  String,
    `control`      UInt8,                    -- 1 = holdout: шаги не исполняются
    `entry_stage`  LowCardinality(String),
    `step_idx`     Int32,                    -- следующий шаг к исполнению
    `next_step_at` DateTime64(3),
    `status`       LowCardinality(String),   -- active | done | exited
    `enrolled_at`  DateTime64(3),
    `updated_at`   DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, campaign_id, identity_id);

CREATE OR REPLACE VIEW retention.campaign_enrollments_current AS
SELECT tenant_id, campaign_id, identity_id,
       argMax(control, updated_at)      AS control,
       argMax(entry_stage, updated_at)  AS entry_stage,
       argMax(step_idx, updated_at)     AS step_idx,
       argMax(next_step_at, updated_at) AS next_step_at,
       argMax(status, updated_at)       AS status,
       min(enrolled_at)                 AS enrolled_at
FROM retention.campaign_enrollments
GROUP BY tenant_id, campaign_id, identity_id;

-- Лог касаний (email/offer) — сырьё для uplift-отчёта Phase 6.
CREATE TABLE IF NOT EXISTS retention.campaign_send_log
(
    `tenant_id`   LowCardinality(String),
    `campaign_id` LowCardinality(String),
    `identity_id` String,
    `step_idx`    Int32,
    `action`      LowCardinality(String),   -- email | offer
    `detail`      String,                    -- subject / offer_id
    `status`      LowCardinality(String),    -- dry_run | sent | issued | holdout | rejected
    `reason`      String,
    `ts`          DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (tenant_id, campaign_id, identity_id, ts);

-- In-app канал (виджет сниппета): очередь баннеров для показа в продукте
-- тенанта. Пишет campaign_tick (action=inapp), читает /public/saas/inbox.
-- Баннер живёт, пока юзер в стадии entry_stage (оплатил -> стадия сменилась ->
-- не сервится), не истёк expires_at и не был закрыт/кликнут (события
-- inapp_dismissed/inapp_clicked в saas_events).
CREATE TABLE IF NOT EXISTS retention.inapp_inbox
(
    `tenant_id`      LowCardinality(String),
    `message_id`     String,                    -- campaign:step:identity
    `client_user_id` String,
    `identity_id`    String,
    `campaign_id`    LowCardinality(String),
    `step_idx`       Int32,
    `title`          String,
    `body`           String,
    `cta_label`      String,
    `cta_url`        String,
    `entry_stage`    LowCardinality(String),
    `expires_at`     DateTime,
    `created_at`     DateTime64(3)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (tenant_id, message_id);

-- ============================================================================
-- Phase 6 — Замер: недельный uplift-отчёт по кампаниям (target vs holdout).
-- ============================================================================
CREATE TABLE IF NOT EXISTS retention.uplift_reports
(
    `tenant_id`      LowCardinality(String),
    `campaign_id`    LowCardinality(String),
    `period_start`   Date,
    `period_end`     Date,
    `n_target`       UInt32,
    `n_control`      UInt32,
    `conv_target`    Float64,
    `conv_control`   Float64,
    `avg_check`      Float64,
    `incremental_usd` Float64,
    `goal_event`     LowCardinality(String),
    `computed_at`    DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (tenant_id, campaign_id, computed_at);

-- ============================================================================
-- Каналы: контакты юзеров с согласиями (consent-модель ТЗ §6). Email живёт в
-- identities (из Stripe); здесь - sms/viber/whatsapp/telegram, которые тенант
-- поставляет событием contact_update (см. INTEGRATION-SAAS.md §Каналы).
-- ============================================================================
CREATE TABLE IF NOT EXISTS retention.contacts
(
    `tenant_id`      LowCardinality(String),
    `client_user_id` String,
    `channel`        LowCardinality(String),  -- sms | viber | whatsapp | telegram
    `address`        String,                   -- номер / chat_id
    `consent`        UInt8,                    -- 1 = явное согласие на канал
    `consent_ts`     DateTime64(3),
    `updated_at`     DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, client_user_id, channel);

CREATE OR REPLACE VIEW retention.contacts_current AS
SELECT tenant_id, client_user_id, channel,
       argMax(address, updated_at)    AS address,
       argMax(consent, updated_at)    AS consent,
       argMax(consent_ts, updated_at) AS consent_ts
FROM retention.contacts
GROUP BY tenant_id, client_user_id, channel;
