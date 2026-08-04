-- ============================================================================
-- Retention analytics — starter queries (ClickHouse)
-- DB: retention | tables: users, money_transactions, game_sessions, game_transactions
-- Все деньги в TRY (major unit). Время хранится в UTC; для турецких суток
-- оборачивай created_at в toTimezone(created_at,'Europe/Istanbul').
-- Запускать: clickhouse client --host 127.0.0.1 < analytics_queries.sql
-- или вставлять по одному в Metabase (Native SQL).
-- ============================================================================

-- 0) Санити: объёмы и период --------------------------------------------------
SELECT 'game_transactions' tbl, count() rows, uniqExact(casino_player_id) players,
       min(created_at) first_event, max(created_at) last_event
FROM retention.game_transactions;

-- 1) DAU / активные игроки по дням (Istanbul) ---------------------------------
SELECT toDate(toTimezone(created_at,'Europe/Istanbul')) AS d,
       uniqExact(casino_player_id) AS dau,
       count() AS events
FROM retention.game_transactions
GROUP BY d ORDER BY d;

-- 2) Истинный GGR по дням (ставки минус выигрыши; freespins считаем отдельно) --
SELECT toDate(toTimezone(created_at,'Europe/Istanbul')) AS d,
       round(sumIf(bet_amount, transaction_type IN ('bet','freespins_bet')),2)  AS bets,
       round(sumIf(win_amount, transaction_type IN ('win','freespins_win')),2)  AS wins,
       round(sumIf(bet_amount, transaction_type IN ('bet','freespins_bet'))
           - sumIf(win_amount, transaction_type IN ('win','freespins_win')),2)  AS ggr
FROM retention.game_transactions
WHERE currency='TRY'
GROUP BY d ORDER BY d;

-- 3) WEEKLY RETENTION (когорта = неделя регистрации) --------------------------
-- Week 0 = неделя регистрации; ячейка = % когорты, активной (была ставка) в неделю N.
WITH cohort AS (
    SELECT casino_player_id,
           toMonday(toTimezone(reg_date,'Europe/Istanbul')) AS cohort_week
    FROM retention.users
    WHERE reg_date IS NOT NULL
),
activity AS (
    SELECT DISTINCT casino_player_id,
           toMonday(toTimezone(created_at,'Europe/Istanbul')) AS active_week
    FROM retention.game_transactions
)
SELECT c.cohort_week,
       dateDiff('week', c.cohort_week, a.active_week) AS week_n,
       uniqExact(c.casino_player_id) AS players
FROM cohort c
INNER JOIN activity a ON c.casino_player_id = a.casino_player_id
WHERE a.active_week >= c.cohort_week
GROUP BY c.cohort_week, week_n
ORDER BY c.cohort_week, week_n;
-- В Metabase: визуализируй как pivot/heatmap (строки cohort_week, колонки week_n).

-- 4) Классический Day-N retention (N = 1,7,14,30) -----------------------------
WITH reg AS (
    SELECT casino_player_id,
           toDate(toTimezone(reg_date,'Europe/Istanbul')) AS reg_day
    FROM retention.users WHERE reg_date IS NOT NULL
),
act AS (
    SELECT DISTINCT casino_player_id,
           toDate(toTimezone(created_at,'Europe/Istanbul')) AS day
    FROM retention.game_transactions
)
SELECT reg.reg_day,
       uniqExact(reg.casino_player_id) AS cohort_size,
       uniqExactIf(reg.casino_player_id, dateDiff('day',reg.reg_day,act.day)=1)  AS d1,
       uniqExactIf(reg.casino_player_id, dateDiff('day',reg.reg_day,act.day)=7)  AS d7,
       uniqExactIf(reg.casino_player_id, dateDiff('day',reg.reg_day,act.day)=14) AS d14,
       uniqExactIf(reg.casino_player_id, dateDiff('day',reg.reg_day,act.day)=30) AS d30
FROM reg LEFT JOIN act ON reg.casino_player_id = act.casino_player_id
GROUP BY reg.reg_day ORDER BY reg.reg_day;

-- 5) Депозиты: воронка и динамика (money_transactions) ------------------------
SELECT toDate(toTimezone(created_at,'Europe/Istanbul')) AS d,
       type, status,
       count() AS cnt,
       round(sum(amount),2) AS total
FROM retention.money_transactions
GROUP BY d, type, status
ORDER BY d, total DESC;

-- 6) Player LTV / экономика игрока (деньги) ------------------------------------
-- ВАЖНО: cash-типы = deposit/manual_deposit и withdrawal/manual_withdrawal
-- (остальное — бонусы: bonus_conversion, freespin, manual_bonus и т.п.)
SELECT casino_player_id,
       round(sumIf(amount, type IN ('deposit','manual_deposit')      AND status='completed'),2) AS deposits,
       round(sumIf(amount, type IN ('withdrawal','manual_withdrawal') AND status='completed'),2) AS withdrawals,
       round(sumIf(amount, type IN ('deposit','manual_deposit')       AND status='completed')
           - sumIf(amount, type IN ('withdrawal','manual_withdrawal')  AND status='completed'),2) AS net_deposit
FROM retention.money_transactions
GROUP BY casino_player_id
ORDER BY net_deposit DESC
LIMIT 100;

-- 7) RFM-ядро: давность/частота/оборот по игрокам -----------------------------
SELECT t.casino_player_id,
       max(toTimezone(t.created_at,'Europe/Istanbul')) AS last_seen,
       dateDiff('day', toDate(max(toTimezone(t.created_at,'Europe/Istanbul'))), today()) AS recency_days,
       count() AS frequency_events,
       round(sumIf(t.bet_amount, t.transaction_type IN ('bet','freespins_bet')),2) AS monetary_turnover
FROM retention.game_transactions t
GROUP BY t.casino_player_id
ORDER BY monetary_turnover DESC
LIMIT 100;

-- 8) Топ игр по обороту (джойн на сессии не нужен — game_uuid в фактах) --------
SELECT game_uuid,
       formatReadableQuantity(count()) AS spins,
       uniqExact(casino_player_id) AS players,
       round(sumIf(bet_amount, transaction_type IN ('bet','freespins_bet')),2) AS turnover
FROM retention.game_transactions
GROUP BY game_uuid ORDER BY turnover DESC LIMIT 30;
