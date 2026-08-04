-- ============================================================================
-- marts.sql — аналитический слой retention (вьюхи + ML-таблицы + производные данные).
--
-- Порядок применения на ЧИСТОЙ базе:
--   1) schema.sql            — 4 исходные таблицы
--   2) (загрузка данных — см. SETUP.md)
--   3) player_features.sql   — витрина игроков
--   4) marts.sql             — ЭТОТ ФАЙЛ  (clickhouse client --multiquery < marts.sql)
--   5) pip install -r requirements-ml.txt && ./train_all.sh   — обучает 6 моделей,
--      наполняет ML-таблицы
--
-- ML-таблицы создаются ПУСТЫМИ — их наполняют *_model.py (DROP+CREATE+INSERT, повторно безопасно);
-- player_games и bonus_effectiveness_t — производные ДАННЫЕ, наполняются здесь (CREATE AS SELECT);
-- bonus_effectiveness_t считается из тяжёлого джойна (54M ставок) → применение ~1 мин;
-- вьюхи — логика, считаются на лету. Применять ПОСЛЕ player_features.sql.
-- ============================================================================


-- ───────── ML-таблицы (пустые; наполняет train_all.sh) + операторские ─────────

CREATE TABLE IF NOT EXISTS retention.player_ltv_ml (`casino_player_id` UInt32, `pred_ltv_d90_ml` Float64) ENGINE = MergeTree ORDER BY casino_player_id SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS retention.player_ltv_quantiles (`casino_player_id` UInt32, `ltv_p10` Float64, `ltv_p50` Float64, `ltv_p90` Float64) ENGINE = MergeTree ORDER BY casino_player_id SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS retention.player_repeat_ml (`casino_player_id` UInt32, `p_2nd_ml` Float64) ENGINE = MergeTree ORDER BY casino_player_id SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS retention.player_churn_ml (`casino_player_id` UInt32, `p_churn` Float64) ENGINE = MergeTree ORDER BY casino_player_id SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS retention.player_next_deposit_ml (`casino_player_id` UInt32, `deposit_number` UInt16, `p_next_deposit` Float64) ENGINE = MergeTree ORDER BY casino_player_id SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS retention.player_bonus_ml (`casino_player_id` UInt32, `rec_bonus` String, `rec_response` Float64) ENGINE = MergeTree ORDER BY casino_player_id SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS retention.bonus_uplift (`metric` String, `value` Float64) ENGINE = TinyLog;

CREATE TABLE IF NOT EXISTS retention.player_offers (`casino_player_id` UInt32, `status` String, `offer_text` String, `note` String, `operator` String, `ts` DateTime DEFAULT now()) ENGINE = ReplacingMergeTree(ts) ORDER BY casino_player_id SETTINGS index_granularity = 8192;


-- ───────── производная таблица: агрегаты игрок×игра (наполняется) ─────────

CREATE TABLE IF NOT EXISTS retention.player_games
ENGINE = MergeTree ORDER BY (casino_player_id, game_uuid) AS
SELECT casino_player_id, game_uuid,
  anyHeavy(aggregator)                                                   AS provider,
  countIf(transaction_type IN ('bet','freespins_bet'))                  AS bets,
  round(sumIf(bet_amount, transaction_type IN ('bet','freespins_bet')),2) AS turnover,
  round(sumIf(win_amount, transaction_type IN ('win','freespins_win')),2) AS wins,
  round(sumIf(win_amount, transaction_type IN ('win','freespins_win'))
      - sumIf(bet_amount, transaction_type IN ('bet','freespins_bet')),2) AS net,
  uniqExact(toDate(created_at))                                         AS days_played,
  min(created_at)                                                       AS first_played,
  max(created_at)                                                       AS last_played
FROM retention.game_transactions
WHERE game_uuid != ''
GROUP BY casino_player_id, game_uuid
HAVING bets > 0;


-- ───────── вьюхи (логика, считаются на лету) ─────────

CREATE VIEW retention.ltv_tier_model (`early_tier_D7` String, `cohort_n` UInt64, `exp_d30` Float64, `exp_d90` Float64, `exp_d120` Float64) AS WITH (SELECT toDate(max(created_at)) FROM retention.money_transactions) AS dmax SELECT early_tier_D7, count() AS cohort_n, round(avg(d30), 0) AS exp_d30, round(avg(d90), 0) AS exp_d90, round(avgIf(d120, mat >= 120), 0) AS exp_d120 FROM (SELECT multiIf(d7 < 1000, 'A', d7 < 3000, 'B', d7 < 10000, 'C', 'D') AS early_tier_D7, d7, arraySum(x -> if(((x.1) >= 0) AND ((x.1) <= 30), x.2, 0), deps) AS d30, arraySum(x -> if(((x.1) >= 0) AND ((x.1) <= 90), x.2, 0), deps) AS d90, arraySum(x -> if(((x.1) >= 0) AND ((x.1) <= 120), x.2, 0), deps) AS d120, mat FROM (SELECT u.casino_player_id, dateDiff('day', toDate(u.ftd_date), dmax) AS mat, groupArray((dateDiff('day', toDate(u.ftd_date), toDate(m.created_at)), toFloat64(m.amount))) AS deps, arraySum(x -> if(((x.1) >= 0) AND ((x.1) <= 7), x.2, 0), groupArray((dateDiff('day', toDate(u.ftd_date), toDate(m.created_at)), toFloat64(m.amount)))) AS d7 FROM retention.users AS u INNER JOIN retention.money_transactions AS m USING (casino_player_id) WHERE (u.account_type = 'normal') AND (u.ftd_date IS NOT NULL) AND (dateDiff('day', toDate(u.ftd_date), dmax) >= 90) AND (m.type IN ('deposit', 'manual_deposit')) AND (m.status = 'completed') GROUP BY u.casino_player_id, u.ftd_date)) GROUP BY early_tier_D7;

CREATE VIEW retention.ltv_curve (`day` UInt8, `cohort_n` UInt64, `avg_cum_deposit` Float64, `median_cum_deposit` Float64) AS WITH [1, 3, 7, 14, 30, 60, 90, 120] AS H, (SELECT toDate(max(created_at)) FROM retention.money_transactions) AS dmax SELECT h AS day, count() AS cohort_n, round(avg(cum_dep), 0) AS avg_cum_deposit, round(median(cum_dep), 0) AS median_cum_deposit FROM (SELECT pl.maturity AS maturity, h, arraySum(x -> if(((x.1) >= 0) AND ((x.1) <= h), x.2, 0), pl.deps) AS cum_dep FROM (SELECT u.casino_player_id, dateDiff('day', toDate(u.ftd_date), dmax) AS maturity, groupArray((dateDiff('day', toDate(u.ftd_date), toDate(m.created_at)), toFloat64(m.amount))) AS deps FROM retention.users AS u INNER JOIN retention.money_transactions AS m USING (casino_player_id) WHERE (u.account_type = 'normal') AND (u.ftd_date IS NOT NULL) AND (m.type IN ('deposit', 'manual_deposit')) AND (m.status = 'completed') GROUP BY u.casino_player_id, u.ftd_date) AS pl ARRAY JOIN H AS h WHERE pl.maturity >= h) GROUP BY h ORDER BY h ASC;

CREATE VIEW retention.player_ltv (`casino_player_id` UInt32, `days_since_ftd` Nullable(Int64), `tier_provisional` Nullable(UInt8), `dep_d1` Float64, `dep_d7` Float64, `dep_to_date` Float64, `early_tier` String, `pred_ltv_d30` Float64, `pred_ltv_d90` Float64, `pred_ltv_d120` Float64, `ltv_is_ml` UInt8, `ltv_headroom` Float64) AS WITH (SELECT toDate(max(created_at)) FROM retention.money_transactions) AS dmax SELECT p.casino_player_id AS casino_player_id, p.mat AS days_since_ftd, p.mat < 7 AS tier_provisional, p.d1 AS dep_d1, p.d7 AS dep_d7, p.dep_total AS dep_to_date, multiIf(p.d7 < 1000, 'A', p.d7 < 3000, 'B', p.d7 < 10000, 'C', 'D') AS early_tier, tm.exp_d30 AS pred_ltv_d30, round(ifNull(ml.pred_ltv_d90_ml, tm.exp_d90)) AS pred_ltv_d90, tm.exp_d120 AS pred_ltv_d120, ml.pred_ltv_d90_ml IS NOT NULL AS ltv_is_ml, greatest(round(ifNull(ml.pred_ltv_d90_ml, tm.exp_d90)) - p.dep_total, 0) AS ltv_headroom FROM (SELECT u.casino_player_id, dateDiff('day', toDate(u.ftd_date), dmax) AS mat, arraySum(x -> if(((x.1) >= 0) AND ((x.1) <= 1), x.2, 0), deps) AS d1, arraySum(x -> if(((x.1) >= 0) AND ((x.1) <= 7), x.2, 0), deps) AS d7, arraySum(x -> (x.2), deps) AS dep_total FROM (SELECT u.casino_player_id, u.ftd_date, groupArray((dateDiff('day', toDate(u.ftd_date), toDate(m.created_at)), toFloat64(m.amount))) AS deps FROM retention.users AS u INNER JOIN retention.money_transactions AS m USING (casino_player_id) WHERE (u.account_type = 'normal') AND (u.ftd_date IS NOT NULL) AND (m.type IN ('deposit', 'manual_deposit')) AND (m.status = 'completed') GROUP BY u.casino_player_id, u.ftd_date) AS u) AS p LEFT JOIN retention.ltv_tier_model AS tm ON multiIf(p.d7 < 1000, 'A', p.d7 < 3000, 'B', p.d7 < 10000, 'C', 'D') = tm.early_tier_D7 LEFT JOIN retention.player_ltv_ml AS ml USING (casino_player_id);

CREATE VIEW retention.ltv_deciles (`decile` Int64, `players` UInt64, `avg_ltv` Float64, `sum_ltv` Float64, `pct_of_value` Nullable(Float64)) AS SELECT decile, count() AS players, round(avg(pred_ltv_d90)) AS avg_ltv, round(sum(pred_ltv_d90)) AS sum_ltv, round((100 * sum(pred_ltv_d90)) / (SELECT sum(pred_ltv_d90) FROM retention.player_ltv), 1) AS pct_of_value FROM (SELECT pred_ltv_d90, 11 - ntile(10) OVER (ORDER BY pred_ltv_d90 ASC) AS decile FROM retention.player_ltv) GROUP BY decile ORDER BY decile ASC;

CREATE VIEW retention.repeat_deposit_model (`ftd_tier` String, `cohort_n` UInt64, `p_2nd_deposit` Float64, `avg_total_deposits` Float64) AS WITH (SELECT toDate(max(created_at)) FROM retention.money_transactions) AS dmax SELECT ftd_tier, count() AS cohort_n, round(avg(made_2nd), 3) AS p_2nd_deposit, round(avg(n_deposits), 2) AS avg_total_deposits FROM (SELECT multiIf(ftd_amount < 500, 'A: <500', ftd_amount < 1500, 'B: 500-1.5k', ftd_amount < 5000, 'C: 1.5-5k', 'D: 5k+') AS ftd_tier, n_deposits, n_deposits >= 2 AS made_2nd FROM (SELECT u.casino_player_id, any(u.ftd_amount) AS ftd_amount, countIf((m.type IN ('deposit', 'manual_deposit')) AND (m.status = 'completed')) AS n_deposits FROM retention.users AS u INNER JOIN retention.money_transactions AS m USING (casino_player_id) WHERE (u.account_type = 'normal') AND (u.ftd_date IS NOT NULL) AND (dateDiff('day', toDate(u.ftd_date), dmax) >= 30) GROUP BY u.casino_player_id)) GROUP BY ftd_tier;

CREATE VIEW retention.deposit_ladder (`deposit_no` UInt8, `reached` UInt64, `reached_next` UInt64, `conv_to_next_pct` Nullable(Float64)) AS SELECT N AS deposit_no, countIf(n >= N) AS reached, countIf(n >= (N + 1)) AS reached_next, round((100 * countIf(n >= (N + 1))) / nullIf(countIf(n >= N), 0), 1) AS conv_to_next_pct FROM (SELECT casino_player_id, countIf((type IN ('deposit', 'manual_deposit')) AND (status = 'completed')) AS n FROM retention.money_transactions WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type = 'normal') GROUP BY casino_player_id) ARRAY JOIN range(1, 11) AS N GROUP BY N ORDER BY N ASC;

CREATE VIEW retention.deposit_percentiles (`metric` String, `p10` Decimal(38, 2), `p25` Decimal(38, 2), `p50` Decimal(38, 2), `p75` Decimal(38, 2), `p90` Decimal(38, 2), `p95` Decimal(38, 2), `p99` Decimal(38, 2), `pmax` Decimal(38, 2)) AS SELECT 'депозиты (сумма)' AS metric, round(quantile(0.1)(dep_sum)) AS p10, round(quantile(0.25)(dep_sum)) AS p25, round(quantile(0.5)(dep_sum)) AS p50, round(quantile(0.75)(dep_sum)) AS p75, round(quantile(0.9)(dep_sum)) AS p90, round(quantile(0.95)(dep_sum)) AS p95, round(quantile(0.99)(dep_sum)) AS p99, round(max(dep_sum)) AS pmax FROM retention.player_features WHERE (account_type = 'normal') AND (dep_count > 0);

CREATE VIEW retention.churn_deciles (`decile` UInt64, `players` UInt64, `avg_risk` Float64, `lo` Float64, `hi` Float64) AS SELECT decile, count() AS players, round(avg(p_churn), 3) AS avg_risk, round(min(p_churn), 3) AS lo, round(max(p_churn), 3) AS hi FROM (SELECT p_churn, ntile(10) OVER (ORDER BY p_churn ASC) AS decile FROM retention.player_churn_ml) GROUP BY decile ORDER BY decile ASC;

CREATE VIEW retention.bonus_effectiveness (`bonus_type` String, `bonus_events` UInt64, `players` UInt64, `dep_resp_14d_pct` Float64, `retained_30d_pct` Float64) AS WITH bn AS (SELECT casino_player_id, created_at AS bts, multiIf(type = 'freespin', 'freespins', description ILIKE '%deneme%', 'no-deposit/trial', description ILIKE '%kay%p%', 'cashback', (description ILIKE '%dsc%') OR (description ILIKE '%yat%'), 'deposit-match', 'other-manual') AS bonus_type FROM retention.money_transactions WHERE (type IN ('freespin', 'manual_bonus', 'bonus')) AND (status = 'completed')), deps AS (SELECT casino_player_id, created_at AS dts FROM retention.money_transactions WHERE (type IN ('deposit', 'manual_deposit')) AND (status = 'completed')), plays AS (SELECT casino_player_id, created_at AS gts FROM retention.game_transactions WHERE transaction_type IN ('bet', 'freespins_bet')) SELECT bonus_type, count() AS bonus_events, uniqExact(cid) AS players, round((100 * countIf(next_dep <= 14)) / count(), 1) AS dep_resp_14d_pct, round((100 * countIf(next_play <= 30)) / count(), 1) AS retained_30d_pct FROM (SELECT b.casino_player_id AS cid, b.bonus_type AS bonus_type, b.bts AS bts, min(if(d.dts > b.bts, dateDiff('day', b.bts, d.dts), NULL)) AS next_dep, min(if(p.gts > b.bts, dateDiff('day', b.bts, p.gts), NULL)) AS next_play FROM bn AS b LEFT JOIN deps AS d ON d.casino_player_id = b.casino_player_id LEFT JOIN plays AS p ON p.casino_player_id = b.casino_player_id GROUP BY b.casino_player_id, b.bonus_type, b.bts) GROUP BY bonus_type ORDER BY bonus_events DESC;

CREATE VIEW retention.player_actions (`casino_player_id` UInt32, `lifecycle` String, `recency_days` Nullable(Int64), `is_depositor` UInt8, `dep_count` UInt64, `dep_sum` Float64, `avg_bet` Float64, `freespin_ratio` Float64, `primary_provider` String, `early_tier` String, `pred_ltv_d90` Float64, `ltv_headroom` Float64, `p_2nd_deposit` Nullable(Float64), `p_churn` Nullable(Float64), `value_try` Float64, `save_weight` Float64, `action` String, `bonus` String, `priority` Float64, `when_to` String) AS SELECT *, round(value_try * ifNull(p_churn, save_weight)) AS priority, multiIf(startsWith(action, 'SAVE') OR startsWith(action, 'WINBACK'), 'сейчас', startsWith(action, 'NUDGE'), 'окно 2-го депозита (ближайшие дни)', startsWith(action, 'CONVERT'), 'сейчас (играет без депозита)', startsWith(action, 'NURTURE'), 'к следующей сессии', '—') AS when_to FROM (SELECT pf.casino_player_id AS casino_player_id, pf.lifecycle AS lifecycle, pf.recency_days AS recency_days, pf.dep_count > 0 AS is_depositor, pf.dep_count AS dep_count, toFloat64(ifNull(pf.dep_sum, 0)) AS dep_sum, toFloat64(ifNull(pf.avg_bet, 0)) AS avg_bet, pf.freespin_ratio AS freespin_ratio, pf.primary_provider AS primary_provider, pl.early_tier AS early_tier, pl.pred_ltv_d90 AS pred_ltv_d90, pl.ltv_headroom AS ltv_headroom, if(pf.dep_count > 0, round(rp.p_2nd_ml, 3), NULL) AS p_2nd_deposit, if(ch.ch_has = 1, ch.p_churn, NULL) AS p_churn, if(pf.dep_count > 0, greatest(toFloat64(ifNull(pl.pred_ltv_d90, 0)), toFloat64(ifNull(pf.dep_sum, 0))), 0.) AS value_try, multiIf(pf.lifecycle = 'active', 0.3, pf.lifecycle = 'cooling', 0.7, pf.lifecycle = 'at_risk', 1., pf.lifecycle = 'dormant', 0.55, pf.lifecycle = 'churned', 0.35, 0.) AS save_weight, multiIf(pf.dep_count > 0 AND pf.net_cash < 0 AND pf.net > 0, 'MONITOR · игрок в плюсе (ревью)', (pf.dep_count = 0) AND pf.ever_played, 'CONVERT · первый депозит', (pf.dep_count = 1) AND (pf.recency_days <= 30), 'NUDGE · 2-й депозит', (pf.lifecycle IN ('cooling', 'at_risk')), 'SAVE · удержать', (pf.lifecycle IN ('dormant', 'churned')), 'WINBACK · вернуть', pf.lifecycle = 'active', 'NURTURE · растить', 'наблюдать') AS action, multiIf(pf.dep_count > 0 AND pf.net_cash < 0 AND pf.net > 0, '⚠ без бонуса — игрок в плюсе (ревью)', pf.dep_count = 0, 'бонус на первый депозит', pf.freespin_ratio > 0.4, concat('фриспины · ', pf.primary_provider), (pl.early_tier IN ('C', 'D')) OR (toFloat64(ifNull(pf.avg_bet, 0)) >= 200), 'VIP-оффер (кэшбэк / деп-матч)', pf.dep_count <= 1, 'релоад-бонус на 2-й депозит', 'релоад / кэшбэк') AS bonus FROM retention.player_features AS pf LEFT JOIN retention.player_ltv AS pl USING (casino_player_id) LEFT JOIN retention.player_repeat_ml AS rp USING (casino_player_id) LEFT JOIN (SELECT casino_player_id, p_churn, toUInt8(1) AS ch_has FROM retention.player_churn_ml) AS ch USING (casino_player_id) WHERE pf.account_type = 'normal');


-- ───────── снапшот эффективности бонусов (из вьюхи выше; тяжёлый, ~1 мин) ─────────

CREATE TABLE IF NOT EXISTS retention.bonus_effectiveness_t
ENGINE = TinyLog AS
SELECT * FROM retention.bonus_effectiveness;


-- ───────── членство в сегментах (материализация конструктора сегментов) ─────────
-- Наполняет materialize_segments.py (шаг 2d run_loop.sh): для каждого активного
-- сегмента из automation.segments компилирует definition → INSERT id-шников.
-- Полная перезапись по сегменту: materialize делает ALTER ... DELETE WHERE sys_name
-- (mutations_sync=1) перед INSERT, поэтому дублей и «застрявших» участников нет.
-- ReplacingMergeTree(computed_at) — страховка от гонок: при слиянии останется
-- последняя запись пары (sys_name, id). Читатели (ручки /segments) считают
-- uniqExact(casino_player_id) — устойчиво к неслитым дублям без FINAL.
CREATE TABLE IF NOT EXISTS retention.segment_members (
    sys_name         LowCardinality(String),
    casino_player_id UInt32,
    computed_at      DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(computed_at) ORDER BY (sys_name, casino_player_id);


-- ───────── исполнитель цепочек: события шагов и лог отправок (W4-T4) ─────────
-- Runtime-факты цепочек живут в ClickHouse (как trigger_log / segment_exports):
-- определения — в Postgres automation.* (миграция 0014), а их исполнение
-- chain-runner-ом (chains/runner.py) пишет сюда. Обе таблицы — append-only
-- журналы (MergeTree, без дедупа): один шаг игрока = одна строка.

-- Журнал прохождения узлов цепочки. event: enter (вошёл в цепочку) | pass
-- (узел пройден; reason='control' — контрольная группа, действие НЕ исполнено) |
-- drop (проверка перед отправкой не пройдена; reason — какая) | goal (достигнута
-- цель атрибуции) | exit (цепочка завершена). Считыватели статистики (api/chains
-- /stats) группируют по (chain_id, node_id, event) и сравнивают main vs control.
CREATE TABLE IF NOT EXISTS retention.chain_events (
    ts               DateTime64(3),
    chain_id         String,
    version_no       UInt16,
    node_id          LowCardinality(String),
    casino_player_id UInt32,
    event            LowCardinality(String),   -- enter|pass|drop|goal|exit
    reason           LowCardinality(String),
    ab_group         LowCardinality(String)    -- main|control
) ENGINE = MergeTree ORDER BY (chain_id, ts);

-- Лог исходящих отправок (сообщения/бонусы). status: sent|failed|skipped
-- (+ delivered|opened|clicked позже — когда казино начнёт слать message_status).
-- Читается проверкой fatigue (chains/checks.py) — «не больше N касаний за окно».
CREATE TABLE IF NOT EXISTS retention.send_log (
    ts               DateTime64(3),
    casino_player_id UInt32,
    chain_id         String,
    node_id          String,
    channel          LowCardinality(String),
    template_id      String,
    status           LowCardinality(String),   -- sent|failed|skipped|delivered|opened|clicked
    reason           String
) ENGINE = MergeTree ORDER BY (casino_player_id, ts);
