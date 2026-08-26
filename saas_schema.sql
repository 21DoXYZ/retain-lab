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
    `email`              String,                    -- ТОЛЬКО серверные события:
                                                    -- сниппет в браузере шлёт лишь hash.
                                                    -- Без адреса неоплатившему юзеру
                                                    -- невозможно написать письмо.
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
    `email`              String,
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

-- Dead-letter: строки, не пережившие парсинг, раньше исчезали БЕССЛЕДНО -
-- дрейф схемы или кривая интеграция теряли события без единого следа,
-- полноту нельзя было ни доказать, ни переиграть. Теперь сырьё + причина.
CREATE TABLE IF NOT EXISTS retention.saas_events_dead
(
    `raw`         String,
    `error`       String,
    `received_at` DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY received_at
TTL received_at + INTERVAL 90 DAY;

DROP VIEW IF EXISTS retention.saas_events_dead_mv;
CREATE MATERIALIZED VIEW retention.saas_events_dead_mv
TO retention.saas_events_dead AS
SELECT _raw_message AS raw, _error AS error, now() AS received_at
FROM retention.saas_events_queue
WHERE length(_error) > 0;

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
    `client_user_id`     String,                    -- основной (для join'ов)
    `client_user_ids`    Array(String) DEFAULT [],  -- ВСЕ аккаунты человека:
                                                    -- второй cuid под тем же
                                                    -- email раньше сиротел
    `sources`            Array(LowCardinality(String)),
    `first_seen`         DateTime64(3),
    `updated_at`         DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, identity_id);
ALTER TABLE retention.identities
    ADD COLUMN IF NOT EXISTS `client_user_ids` Array(String) DEFAULT []
    AFTER `client_user_id`;

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
    `buy_intent`   Float64 DEFAULT 0,       -- намерение купить/расшириться (heur-v3)
    `features`     String,                  -- JSON фич, из которых собраны скоры
    `version`      LowCardinality(String),  -- напр. heur-v1
    `scored_at`    DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (tenant_id, identity_id, scored_at);
ALTER TABLE retention.user_scores
    ADD COLUMN IF NOT EXISTS `buy_intent` Float64 DEFAULT 0 AFTER `power_score`;

CREATE OR REPLACE VIEW retention.user_scores_current AS
SELECT tenant_id, identity_id,
       argMax(p_convert, scored_at)    AS p_convert,
       argMax(p_churn, scored_at)      AS p_churn,
       argMax(ltv_estimate, scored_at) AS ltv_estimate,
       argMax(power_score, scored_at)  AS power_score,
       argMax(buy_intent, scored_at)   AS buy_intent,
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
       argMax(client_user_id, updated_at)     AS client_user_id,
       argMax(client_user_ids, updated_at)    AS client_user_ids
FROM retention.identities
GROUP BY tenant_id, identity_id;

-- Развёртка аккаунтов: (tenant, alias-cuid) -> identity. Через неё события
-- ВТОРОГО аккаунта человека находят его identity - раньше они сиротели.
CREATE OR REPLACE VIEW retention.identity_aliases AS
SELECT tenant_id, identity_id, alias
FROM retention.identities_current
ARRAY JOIN arrayDistinct(
    arrayConcat(client_user_ids,
                if(client_user_id != '', [client_user_id], []))) AS alias
WHERE alias != '';

-- Каждое событие → identity по старшему доступному ключу (ровно один матч):
-- client_user_id > stripe_customer_id > email_hash.
-- ЗНАНИЕ О КЛИЕНТЕ, отдельно от его секретов. Разбор продукта и экономика
-- подарков - это данные с историей: тарифы меняются, и надо видеть, что именно
-- поменялось. Ключи и токены сюда НЕ кладутся, они живут в secrets/tenants.json.
CREATE TABLE IF NOT EXISTS retention.tenant_knowledge
(
    `tenant_id`  LowCardinality(String),
    `kind`       LowCardinality(String),   -- brief | economics | ...
    `version`    UInt32,
    `payload`    String,                   -- JSON, схему держит модуль-владелец
    `source`     String,                   -- откуда собрано (адрес сайта и т.п.)
    `created_at` DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (tenant_id, kind, version);

CREATE OR REPLACE VIEW retention.tenant_knowledge_current AS
SELECT tenant_id, kind,
       argMax(payload, version)    AS payload,
       argMax(source, version)     AS source,
       max(version)                AS version_max,
       argMax(created_at, version) AS updated_at
FROM retention.tenant_knowledge
GROUP BY tenant_id, kind;

-- Отбитые события: приходят с сайта клиента, но ключ не подходит. Такое
-- случается после перевыпуска токена - на сайте остаётся старый код, и всё
-- молча уходит в 401. Без этой таблицы клиент видит только «событий нет» и
-- часами ищет ошибку у себя. tenant_id берём из ТЕЛА запроса (заявка клиента,
-- не доверенная) - его хватает, чтобы показать подсказку нужному пространству.
CREATE TABLE IF NOT EXISTS retention.ingest_rejects
(
    `tenant_id`    LowCardinality(String),
    `origin`       String,
    `token_prefix` String,
    `reason`       LowCardinality(String),
    `ts`           DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (tenant_id, ts)
TTL ts + INTERVAL 30 DAY;

CREATE OR REPLACE VIEW retention.saas_events_resolved AS
SELECT a.identity_id AS identity_id, e.*
FROM retention.saas_events e
JOIN retention.identity_aliases a
  ON e.tenant_id = a.tenant_id AND e.client_user_id = a.alias
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
-- Дедуплицированный поток per identity. Сниппет повторяет отправку при сбое
-- сети, Stripe перепосылает вебхук на любой не-2xx - одно событие приходит
-- дважды. Схлопываем по event_id ОДИН раз здесь: иначе удваивался расход
-- юнитов (ложная стадия «упёрся в лимит»), число моментов ценности и всё
-- поведение. Общий вход для фичей - и для любых будущих витрин.
CREATE OR REPLACE VIEW retention.saas_events_deduped AS
SELECT tenant_id, identity_id, event_id,
       any(ts)           AS ts,
       any(event_type)   AS event_type,
       any(source)       AS source,
       any(page)         AS page,
       any(tokens_spent) AS tokens_spent,
       any(meta)         AS meta
FROM retention.saas_events_resolved
GROUP BY tenant_id, identity_id, event_id;

CREATE OR REPLACE VIEW retention.user_event_features AS
-- Фичи одного человека ОДНИМ проходом по дедуплицированному потоку. Разбита
-- на смысловые блоки (использование / биллинг / поведение / перформанс /
-- намерение / контекст устройства). Разносить блоки по отдельным вьюхам с
-- JOIN нельзя: каждая заново сканировала бы события (в N раз дороже) - здесь
-- сознательно один проход. Потребители: scoring.py, карточка, user_actions.
SELECT
    tenant_id,
    identity_id,
    -- ── использование и жизненный цикл ──
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
    -- юниты за месяц: колонка tokens_spent (Server Events API) ПЛЮС списания
    -- кредитов из экспорта продукта - у клиента с экспортом burn живёт на них
    sumIf(tokens_spent, ts >= toStartOfMonth(now()))
      + toInt64(sumIf(abs(JSONExtractFloat(meta, 'amount')),
                      event_type = 'credit_spend'
                      AND ts >= toStartOfMonth(now())))                  AS tokens_spent_month,
    -- billing.* только из Stripe: шлюз чужие billing-события отбивает, но
    -- витрина не доверяет и историческим строкам (второй рубеж)
    maxIf(ts, event_type = 'billing.payment_failed' AND source = 'stripe')  AS last_payment_failed,
    maxIf(ts, event_type = 'billing.invoice_paid' AND source = 'stripe')    AS last_invoice_paid,
    maxIf(ts, event_type = 'billing.subscription_cancel_scheduled'
              AND source = 'stripe')                                        AS last_cancel_scheduled,
    maxIf(ts, event_type NOT LIKE 'billing.%')                           AS last_product_seen,
    -- поведение сниппета v2 (meta-JSON): фрустрация и время в продукте -
    -- ранние сигналы ухода, которых нет в метриках использования
    countIf(event_type = 'rage_click' AND ts >= now() - INTERVAL 7 DAY)  AS rage_clicks_7d,
    countIf(event_type = 'js_error' AND ts >= now() - INTERVAL 7 DAY)    AS js_errors_7d,
    sumIf(JSONExtractInt(meta, 'seconds'),
          event_type = 'page_leave' AND ts >= now() - INTERVAL 7 DAY)
      + countIf(event_type = 'heartbeat'
                AND ts >= now() - INTERVAL 7 DAY) * 120                  AS active_sec_7d,
    sumIf(JSONExtractInt(meta, 'seconds'),
          event_type = 'page_leave' AND ts >= now() - INTERVAL 14 DAY
          AND ts < now() - INTERVAL 7 DAY)
      + countIf(event_type = 'heartbeat' AND ts >= now() - INTERVAL 14 DAY
                AND ts < now() - INTERVAL 7 DAY) * 120                   AS active_sec_prev_7d,
    -- проекты: шаг воронки между регистрацией и первой генерацией.
    -- projects>0 при generations=0 - намерение было, ценность не случилась
    countIf(event_type = 'project_created')                              AS projects_total,
    -- ── поддержка и обратная связь (экспорт продукта) ──
    -- обращение в поддержку и баг-репорт - фрустрация ДО падения активности
    countIf(event_type = 'support_ticket'
            AND ts >= now() - INTERVAL 30 DAY)                           AS support_tickets_30d,
    countIf(event_type = 'feedback'
            AND JSONExtractString(meta, 'category') IN ('bug', 'complaint')
            AND ts >= now() - INTERVAL 30 DAY)                           AS bug_reports_30d,
    maxIf(ts, event_type = 'support_ticket')                             AS last_support_at,
    -- ── намерение купить (buy-intent) ──
    -- заходы на прайсинг (кросс-сессия из RFM), пейвол, старт чекаута,
    -- скачивания (адаптация). Сильнейший - pricing_visits.
    max(JSONExtractInt(meta, 'pricing_visits'))                          AS pricing_visits,
    max(JSONExtractInt(meta, 'visits'))                                  AS visit_count,
    countIf(event_type = 'download_click' AND ts >= now() - INTERVAL 14 DAY) AS downloads_14d,
    -- ── перформанс как исход (тормоза = тихий отток): INP и LCP, худшее за 7д ──
    maxIf(JSONExtractInt(meta, 'inp'), event_type IN ('page_leave', 'heartbeat')
          AND ts >= now() - INTERVAL 7 DAY)                             AS inp_ms,
    maxIf(JSONExtractInt(meta, 'lcp'), event_type IN ('page_leave', 'heartbeat')
          AND ts >= now() - INTERVAL 7 DAY)                             AS lcp_ms,
    -- контекст последней сессии: страна, ОС/браузер, тип устройства, GPU-тир
    argMaxIf(JSONExtractString(meta, 'geo', 'country'), ts,
             JSONExtractString(meta, 'geo', 'country') != '')            AS geo_country,
    argMaxIf(JSONExtractString(meta, 'ua', 'os'), ts,
             JSONExtractString(meta, 'ua', 'os') != '')                  AS os_family,
    argMaxIf(JSONExtractString(meta, 'ua', 'device_type'), ts,
             JSONExtractString(meta, 'ua', 'device_type') != '')         AS device_type,
    argMaxIf(JSONExtractString(meta, 'gpu'), ts,
             JSONExtractString(meta, 'gpu') != '')                       AS gpu,
    argMaxIf(JSONExtractString(meta, 'model'), ts,
             JSONExtractString(meta, 'model') != '')                     AS device_model,
    maxIf(JSONExtractInt(meta, 'apple_pay'), event_type = 'session_start') AS apple_pay,
    argMaxIf(JSONExtractInt(meta, 'datacenter'), ts,
             JSONExtractString(meta, 'geo', 'ip') != '')                 AS datacenter
FROM retention.saas_events_deduped
GROUP BY tenant_id, identity_id;

-- Последний снимок подписки per customer.
-- Последнее состояние КАЖДОЙ подписки (у клиента их может быть несколько).
CREATE OR REPLACE VIEW retention.stripe_subscriptions_latest AS
SELECT tenant_id, subscription_id,
       argMax(customer_id, updated_at)           AS customer_id,
       argMax(status, updated_at)                AS status,
       argMax(plan_id, updated_at)               AS plan_id,
       argMax(amount, updated_at)                AS amount,
       argMax(bill_interval, updated_at)         AS bill_interval,
       argMax(trial_end, updated_at)             AS trial_end,
       argMax(cancel_at, updated_at)             AS cancel_at,
       argMax(canceled_at, updated_at)           AS canceled_at,
       argMax(current_period_start, updated_at)  AS current_period_start,
       argMax(current_period_end, updated_at)    AS current_period_end,
       max(updated_at)                           AS updated_at_max
FROM retention.stripe_subscriptions
GROUP BY tenant_id, subscription_id;

-- Клиент целиком. ВАЖНО: у него может быть основная подписка и допы. Раньше
-- эта вьюха брала «последнюю обновлённую» - и отменённый доп делал активного
-- плательщика «отменившим» (ложный винбэк), а его MRR схлопывался до цены
-- допа. Теперь статус выбирается по живости, а деньги суммируются по всем
-- живым подпискам.
CREATE OR REPLACE VIEW retention.stripe_subscriptions_current AS
SELECT tenant_id,
       customer_id,
       argMax(subscription_id, (alive_rank, monthly))      AS subscription_id,
       argMax(status, (alive_rank, monthly))               AS status,
       argMax(plan_id, (alive_rank, monthly))              AS plan_id,
       argMax(amount, (alive_rank, monthly))               AS amount,
       argMax(bill_interval, (alive_rank, monthly))        AS bill_interval,
       argMax(trial_end, (alive_rank, monthly))            AS trial_end,
       argMax(cancel_at, (alive_rank, monthly))            AS cancel_at,
       argMax(canceled_at, (alive_rank, monthly))          AS canceled_at,
       argMax(current_period_start, (alive_rank, monthly)) AS current_period_start,
       argMax(current_period_end, (alive_rank, monthly))   AS current_period_end,
       round(sumIf(monthly, alive_rank >= 2), 2)           AS mrr_total,
       count()                                             AS subs_count
FROM (
    SELECT *,
           multiIf(status = 'active', 4,
                   status = 'trialing', 3,
                   status = 'past_due', 2,
                   status IN ('paused', 'incomplete', 'unpaid'), 1,
                   0)                                                AS alive_rank,
           if(bill_interval = 'year', toFloat64(amount) / 12, toFloat64(amount)) AS monthly
    FROM retention.stripe_subscriptions_latest
)
GROUP BY tenant_id, customer_id;

-- ГЛАВНАЯ ВЬЮХА Phase 2: ровно одна стадия + действие на каждого stitched-юзера.
-- Приоритет: DUNNING > WINBACK > CONVERT > SAVE > UPGRADE > ACTIVATE > MONITOR.
-- DUNNING событийный: последний payment_failed новее последнего paid, либо
-- статус подписки past_due — вьюха видит новое событие сразу (без ночного джоба).
-- Лестница тарифов: для каждого плана - цена СЛЕДУЮЩЕГО по величине. Нужна,
-- чтобы «недобор апгрейдов» считался реальной разницей цен, а не выдуманным
-- процентом от текущего платежа.
-- Расход юнитов ЗА ТЕКУЩИЙ ОПЛАЧЕННЫЙ ПЕРИОД человека. Лимит тарифа
-- обновляется в дату его платежа, а не 1-го числа: у клиента с оплатой 20-го
-- календарный счётчик обнулялся посреди периода, burn_rate падал в пол и
-- стадия «упёрся в лимит» пропадала ровно тогда, когда человек у лимита.
CREATE OR REPLACE VIEW retention.user_period_usage AS
SELECT e.tenant_id                AS tenant_id,
       e.identity_id              AS identity_id,
       sum(e.units_spent)         AS tokens_spent_period
FROM (
    -- юниты = колонка tokens_spent (Server Events API) ПЛЮС списания кредитов
    -- из экспорта: иначе у клиента с экспортом периодный расход был вечным
    -- нулём, а НЕ-NULL ноль побеждал месячную фичу в coalesce - burn умирал
    SELECT tenant_id, identity_id, event_id,
           any(ts) AS ts,
           any(tokens_spent)
             + toInt64(if(any(event_type) = 'credit_spend',
                          abs(any(JSONExtractFloat(meta, 'amount'))), 0)) AS units_spent
    FROM retention.saas_events_resolved
    GROUP BY tenant_id, identity_id, event_id
) e
JOIN retention.identities_current i
  ON i.tenant_id = e.tenant_id AND i.identity_id = e.identity_id
JOIN retention.stripe_subscriptions_current s
  ON s.tenant_id = i.tenant_id AND s.customer_id = i.stripe_customer_id
WHERE e.ts >= s.current_period_start
GROUP BY e.tenant_id, e.identity_id;

CREATE OR REPLACE VIEW retention.tenant_plan_ladder AS
SELECT p.tenant_id                                   AS tenant_id,
       p.plan_id                                     AS plan_id,
       p.mrr                                         AS plan_mrr,
       coalesce(min(if(q.mrr > p.mrr, q.mrr, NULL)), 0) AS next_mrr
FROM retention.tenant_plans_current p
LEFT JOIN retention.tenant_plans_current q ON q.tenant_id = p.tenant_id
GROUP BY p.tenant_id, p.plan_id, p.mrr;

CREATE OR REPLACE VIEW retention.user_actions AS
WITH
    -- CH не мешает Decimal и Float64 в одном if - приводим явно
    if(s.mrr_total > 0, round(toFloat64(s.mrr_total), 2),
       if(s.bill_interval = 'year', round(toFloat64(s.amount) / 12, 2),
          toFloat64(s.amount)))                                         AS sub_mrr,
    if(p.monthly_tokens > 0,
       coalesce(u.tokens_spent_period, f.tokens_spent_month) / p.monthly_tokens,
       0)                                                               AS burn_rate_calc,
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
        stage_calc = 'UPGRADE',  greatest(toFloat64(coalesce(l.next_mrr, 0))
                                          - toFloat64(sub_mrr), 0),
        stage_calc IN ('CONVERT', 'ACTIVATE', 'WINBACK'), toFloat64(coalesce(p.mrr, 0)),
        0.0)            AS value_at_stake,
    if(is_canceled AND days_since_cancel < 30, 'post_cancel_cooldown', '') AS stage_note,
    sc.p_convert, sc.p_churn, sc.ltv_estimate, sc.power_score, sc.buy_intent,
    sc.last_scored_at AS scored_at
FROM retention.identities_current i
LEFT JOIN retention.stripe_subscriptions_current s
    ON i.tenant_id = s.tenant_id AND i.stripe_customer_id = s.customer_id
LEFT JOIN retention.user_event_features f
    ON i.tenant_id = f.tenant_id AND i.identity_id = f.identity_id
LEFT JOIN retention.tenant_plans_current p
    ON i.tenant_id = p.tenant_id AND s.plan_id = p.plan_id
LEFT JOIN retention.tenant_plan_ladder l
    ON i.tenant_id = l.tenant_id AND s.plan_id = l.plan_id
LEFT JOIN retention.user_period_usage u
    ON i.tenant_id = u.tenant_id AND i.identity_id = u.identity_id
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
    `provider_id` String,                    -- id письма/сообщения у провайдера:
                                             -- по нему вебхуки доставки находят касание
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
    `kind`           LowCardinality(String) DEFAULT 'banner',  -- banner | nps
    `expires_at`     DateTime,
    `created_at`     DateTime64(3)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (tenant_id, message_id);
ALTER TABLE retention.inapp_inbox
    ADD COLUMN IF NOT EXISTS `kind` LowCardinality(String) DEFAULT 'banner'
    AFTER `entry_stage`;

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

-- ============================================================================
-- ИИ-слой 2: аналитик результатов + разбор причин отмены.
-- LLM здесь ПРЕДЛАГАЕТ и КЛАССИФИЦИРУЕТ, но ничего не исполняет: правки
-- кампаний применяет владелец кнопкой, категории отмен - только чтение.
-- ============================================================================

-- Рекомендации ИИ-аналитика по результатам (вход: uplift + логи касаний).
CREATE TABLE IF NOT EXISTS retention.ai_insights
(
    `tenant_id`    LowCardinality(String),
    `insight_id`   String,                    -- детерминированный: период+кампания+вид
    `period_start` Date,
    `period_end`   Date,
    `campaign_id`  LowCardinality(String),
    `step_idx`     Int32,                     -- -1 = про кампанию целиком
    `kind`         LowCardinality(String),    -- drop_step|change_delay|rewrite_copy|cut_offer|raise_cap|scale_up|no_action
    `title`        String,
    `rationale`    String,                    -- обоснование ЦИФРАМИ из evidence
    `evidence`     String,                    -- JSON фактов, на которых построено
    `suggestion`   String,                    -- JSON конкретной правки (что применить)
    `status`       LowCardinality(String),    -- new|applied|dismissed
    `created_at`   DateTime64(3)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (tenant_id, insight_id);

CREATE OR REPLACE VIEW retention.ai_insights_current AS
SELECT tenant_id, insight_id,
       argMax(period_start, created_at) AS period_start,
       argMax(period_end, created_at)   AS period_end,
       argMax(campaign_id, created_at)  AS campaign_id,
       argMax(step_idx, created_at)     AS step_idx,
       argMax(kind, created_at)         AS kind,
       argMax(title, created_at)        AS title,
       argMax(rationale, created_at)    AS rationale,
       argMax(evidence, created_at)     AS evidence,
       argMax(suggestion, created_at)   AS suggestion,
       argMax(status, created_at)       AS status,
       max(created_at)                  AS created_at_max
FROM retention.ai_insights
GROUP BY tenant_id, insight_id;

-- Причины отмены: свободный текст юзера -> фиксированная категория.
CREATE TABLE IF NOT EXISTS retention.cancel_reasons
(
    `tenant_id`   LowCardinality(String),
    `event_id`    String,
    `identity_id` String,
    `category`    LowCardinality(String),  -- price|missing_feature|one_time_need|switched|quality|support|other
    `summary`     String,                  -- краткий пересказ (1 фраза)
    `verbatim`    String,                  -- исходный текст юзера
    `mrr`         Decimal(18, 2),
    `ts`          DateTime64(3),
    `created_at`  DateTime64(3)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (tenant_id, event_id);

-- ============================================================================
-- Email-канал: доставляемость и закон. Без этих трёх таблиц отправка «в
-- никуда»: не видно баунсов, нельзя выполнить отписку, можно спамить в
-- жалующихся (домен уходит в чёрные списки).
-- ============================================================================

-- События доставки от Resend (webhook): sent/delivered/opened/clicked/
-- bounced/complained/delivery_delayed. Первичный ключ - id письма провайдера.
CREATE TABLE IF NOT EXISTS retention.email_events
(
    `tenant_id`   LowCardinality(String),
    `provider_id` String,                   -- id письма в Resend
    `event_type`  LowCardinality(String),
    `address`     String,
    `campaign_id` LowCardinality(String),
    `step_idx`    Int32,
    `detail`      String,                   -- причина баунса и т.п.
    `ts`          DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (tenant_id, provider_id, event_type, ts);

-- Список подавления: кому больше НЕ пишем никогда. Причины: отписка юзера,
-- жалоба на спам, жёсткий баунс (адрес не существует).
CREATE TABLE IF NOT EXISTS retention.email_suppressions
(
    `tenant_id`  LowCardinality(String),
    `address`    String,
    `reason`     LowCardinality(String),    -- unsubscribed | complained | bounced
    `detail`     String,
    `created_at` DateTime64(3)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (tenant_id, address);

CREATE OR REPLACE VIEW retention.email_suppressions_current AS
SELECT tenant_id, address,
       argMax(reason, created_at) AS reason,
       argMax(detail, created_at) AS detail,
       max(created_at)            AS suppressed_at
FROM retention.email_suppressions
GROUP BY tenant_id, address;

-- ── Переписка личного WhatsApp (трек C): инбокс основателя ──────────────────
-- Пишет вебхук WAHA (оба направления: входящие и ответы, в т.ч. набранные с
-- телефона). chat_id хранится ПОЛНЫМ (с @lid/@c.us) - он же адрес для ответа.
-- Replacing по (tenant, chat, msg): эхо собственного ответа не дублируется.
CREATE TABLE IF NOT EXISTS retention.wa_messages
(
    `tenant_id`   LowCardinality(String),
    `chat_id`     String,
    `wa_msg_id`   String,
    `direction`   LowCardinality(String),   -- in | out
    `text`        String,
    `sender_name` String,
    `ts`          DateTime64(3)
)
ENGINE = ReplacingMergeTree(ts)
ORDER BY (tenant_id, chat_id, wa_msg_id);

-- ============================================================================
-- Дирижёр конвейера: журнал прогонов стадий (ops_loop.py). Каждая стадия
-- пишет сюда исход - и по нему следующая стадия проверяет свежесть входа
-- (DAG зависимостей), а владелец/оператор видит здоровье всего контура.
-- Без этого крон крутил стадии по часам вслепую: стадия могла тихо посчитать
-- на устаревших данных, если предыдущая упала.
-- ============================================================================
CREATE TABLE IF NOT EXISTS retention.pipeline_runs
(
    `tenant_id`      LowCardinality(String),
    `stage`          LowCardinality(String),
    `status`         LowCardinality(String),  -- ok | error | timeout | skipped
    `detail`         String,                   -- хвост вывода / причина скипа
    `input_fresh`    UInt8,                    -- 1 = вход был свежим на момент запуска
    `skipped_reason` String,                   -- stale_dep:<stage> и т.п.
    `rows`           Int64,                     -- сколько обработано (если стадия говорит)
    `duration_s`     Float64,
    `started_at`     DateTime64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(started_at)
ORDER BY (tenant_id, stage, started_at)
TTL toDateTime(started_at) + INTERVAL 90 DAY;

-- Текущее здоровье: последний прогон каждой стадии по тенанту + его возраст.
CREATE OR REPLACE VIEW retention.pipeline_health AS
SELECT tenant_id, stage,
       argMax(status, started_at)         AS status,
       argMax(detail, started_at)         AS detail,
       argMax(input_fresh, started_at)    AS input_fresh,
       argMax(skipped_reason, started_at) AS skipped_reason,
       argMax(rows, started_at)           AS rows,
       argMax(duration_s, started_at)     AS duration_s,
       max(started_at)                    AS last_run,
       dateDiff('minute', max(started_at), now()) AS age_min,
       -- последний УСПЕШНЫЙ прогон отдельно: стадия могла упасть последний раз,
       -- но её выход всё ещё свежий с предыдущего успеха
       maxIf(started_at, pipeline_runs.status = 'ok')   AS last_ok,
       dateDiff('minute', maxIf(started_at, pipeline_runs.status = 'ok'), now()) AS ok_age_min
FROM retention.pipeline_runs
GROUP BY tenant_id, stage;

-- LLM-стадии: исход каждого обращения к модели (llm_stage.record_run).
-- Галлюцинации и пустые ответы видны единообразно: сколько принято/отбраковано
-- доменной валидацией (схемы офферов, copy_review, коды-не-проза).
CREATE TABLE IF NOT EXISTS retention.llm_runs
(
    `tenant_id` LowCardinality(String),
    `stage`     LowCardinality(String),   -- offers | copy | analyst | cancel
    `status`    LowCardinality(String),   -- ok | error
    `kept`      Int64,
    `rejected`  Int64,
    `note`      String,
    `ts`        DateTime64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (tenant_id, stage, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY;

-- ============================================================================
-- Карты клиентов: срок действия для перехвата НЕВОЛЬНОГО оттока. Карта
-- истекает -> следующий платёж не пройдёт -> человек уходит, не желая того.
-- Пишет mapper из событий payment_method.* (attached/updated/автообновление).
-- ============================================================================
CREATE TABLE IF NOT EXISTS retention.stripe_cards
(
    `tenant_id`   LowCardinality(String),
    `customer_id` String,
    `brand`       LowCardinality(String),
    `last4`       String,
    `exp_month`   UInt8,
    `exp_year`    UInt16,
    `updated_at`  DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, customer_id);

CREATE OR REPLACE VIEW retention.stripe_cards_current AS
SELECT tenant_id, customer_id,
       argMax(brand, updated_at)     AS brand,
       argMax(last4, updated_at)     AS last4,
       argMax(exp_month, updated_at) AS exp_month,
       argMax(exp_year, updated_at)  AS exp_year
FROM retention.stripe_cards
GROUP BY tenant_id, customer_id;

-- ============================================================================
-- Replenishment Autopilot v1 (REPLENISHMENT-AUTOPILOT.md): предиктивный реордер
-- расходников. Слой ПРОИЗВОДНЫЙ поверх saas_events (принцип 4 спеки):
-- единственные живые сущности - план цикла и базлайн скорости потребления;
-- продления/opt-out'ы выводятся из событий, ничего не гадаем (принцип 1).
-- Пишет джоб stripe_sync/replenishment.py; JOIN'ы - ТОЛЬКО через *_current.
-- ============================================================================

-- Один купленный «пакет» расходника: цикл от заказа до «закончилось».
CREATE TABLE IF NOT EXISTS retention.replenishment_plans
(
    `tenant_id`      LowCardinality(String),
    `plan_id`        String,                   -- детерминированный: md5(tenant|identity|sku|order_ref)
    `identity_id`    String,
    `sku`            String,
    `order_ref`      String,                   -- заказ-источник (дубль-защита)
    `status`         LowCardinality(String),   -- ACTIVE | QUEUED | FINISHED
    `started_at`     DateTime64(3),
    `predicted_days` UInt16,                   -- базлайн пары | медиана SKU | default_days
    `extension_days` UInt16,                   -- +7 за каждый ответ «ещё есть» (не учится)
    `finished_at`    Nullable(DateTime64(3)),
    `finish_reason`  LowCardinality(String),   -- USER_CONFIRMED | REORDERED | EXPIRED | CANCELLED
    `updated_at`     DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, plan_id);

CREATE OR REPLACE VIEW retention.replenishment_plans_current AS
SELECT tenant_id, plan_id,
       argMax(identity_id, updated_at)    AS identity_id,
       argMax(sku, updated_at)            AS sku,
       argMax(order_ref, updated_at)      AS order_ref,
       argMax(status, updated_at)         AS status,
       argMax(started_at, updated_at)     AS started_at,
       argMax(predicted_days, updated_at) AS predicted_days,
       argMax(extension_days, updated_at) AS extension_days,
       argMax(finished_at, updated_at)    AS finished_at,
       argMax(finish_reason, updated_at)  AS finish_reason,
       max(updated_at)                    AS updated_at_max
FROM retention.replenishment_plans
GROUP BY tenant_id, plan_id;

-- Скорость потребления пары «клиент × SKU». EWMA двигают ТОЛЬКО циклы,
-- закрытые явным подтверждением юзера (USER_CONFIRMED) - принцип 2 спеки.
CREATE TABLE IF NOT EXISTS retention.consumption_baselines
(
    `tenant_id`       LowCardinality(String),
    `identity_id`     String,
    `sku`             String,
    `baseline_days`   Float64,
    `last_cycle_days` Float64,
    `cycles_count`    UInt32,
    `updated_at`      DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, identity_id, sku);

CREATE OR REPLACE VIEW retention.consumption_baselines_current AS
SELECT tenant_id, identity_id, sku,
       argMax(baseline_days, updated_at)   AS baseline_days,
       argMax(last_cycle_days, updated_at) AS last_cycle_days,
       argMax(cycles_count, updated_at)    AS cycles_count
FROM retention.consumption_baselines
GROUP BY tenant_id, identity_id, sku;

-- Что делает SKU отслеживаемым: атрибуты заполняет мерчант в CRM или
-- LLM-бэкфилл по названию товара; source='MANUAL' бэкфилл НЕ перезаписывает.
CREATE TABLE IF NOT EXISTS retention.replenishment_sku_attrs
(
    `tenant_id`    LowCardinality(String),
    `sku`          String,
    `eligible`     UInt8,
    `pack_size`    Float64,
    `unit`         LowCardinality(String),
    `default_days` UInt16,                    -- дефолт цикла до первого обучения
    `source`       LowCardinality(String),    -- MANUAL | LLM
    `updated_at`   DateTime64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, sku);

CREATE OR REPLACE VIEW retention.replenishment_sku_attrs_current AS
SELECT tenant_id, sku,
       argMax(eligible, updated_at)     AS eligible,
       argMax(pack_size, updated_at)    AS pack_size,
       argMax(unit, updated_at)         AS unit,
       argMax(default_days, updated_at) AS default_days,
       argMax(source, updated_at)       AS source
FROM retention.replenishment_sku_attrs
GROUP BY tenant_id, sku;

-- Карта истекает СКОРО у активной подписки = будущий невольный отток.
-- Дней до конца месяца истечения; порог перехвата (<=45 дней) применяет код.
CREATE OR REPLACE VIEW retention.card_expiry_current AS
SELECT c.tenant_id                                             AS tenant_id,
       c.customer_id                                           AS customer_id,
       c.brand                                                 AS brand,
       c.last4                                                 AS last4,
       c.exp_month                                             AS exp_month,
       c.exp_year                                              AS exp_year,
       -- последний день месяца истечения (карта живёт до конца месяца)
       toLastDayOfMonth(makeDate(c.exp_year, c.exp_month, 1))     AS expires_on,
       dateDiff('day', today(),
                toLastDayOfMonth(makeDate(c.exp_year, c.exp_month, 1))) AS days_to_expiry
FROM retention.stripe_cards_current c
WHERE c.exp_year > 0 AND c.exp_month BETWEEN 1 AND 12;
