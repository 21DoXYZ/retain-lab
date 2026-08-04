-- ============================================================================
-- Витрина player_features: 1 строка = 1 игрок, агрегаты из всех 4 таблиц.
-- БЕЗ PII (нет email/phone/username). Ключ — числовой casino_player_id.
-- Полная история (не срез на дату). Для churn-модели срез сделаем отдельно.
-- ============================================================================
DROP TABLE IF EXISTS retention.player_features;

CREATE TABLE retention.player_features
ENGINE = MergeTree ORDER BY casino_player_id AS
WITH (SELECT max(toDate(created_at)) FROM retention.game_transactions WHERE status='completed') AS asof
SELECT
  -- ---- профиль (users) ----
  u.casino_player_id                                   AS casino_player_id,
  u.account_type                                       AS account_type,
  u.activity_status                                    AS activity_status,
  u.country_iso_estimated                              AS country,
  u.currency                                           AS currency,
  u.reg_date                                           AS reg_date,
  dateDiff('day', toDate(u.reg_date), asof)         AS tenure_days,
  u.ftd_date                                           AS ftd_date,
  u.ftd_amount                                         AS ftd_amount,
  (u.ftd_date IS NOT NULL)                             AS is_depositor,
  if(u.affiliate_account_type='', '(none)', u.affiliate_account_type) AS affiliate_type,
  u.affiliate_code                                     AS affiliate_code,
  u.phone_verified                                     AS phone_verified,
  u.email_verified                                     AS email_verified,
  u.status                                             AS status,
  u.is_active                                          AS is_active,
  u.last_login                                         AS last_login,
  u.last_active                                        AS last_active,
  u.balance                                            AS balance,
  u.bonus_balance                                      AS bonus_balance,

  -- ---- игра (game_transactions) ----
  g.bets                                               AS bets,
  g.turnover                                           AS turnover,
  g.wins_sum                                           AS wins_sum,
  round(g.wins_sum - g.turnover, 2)                    AS net,            -- + игрок в плюсе / - проиграл
  g.avg_bet                                            AS avg_bet,
  g.max_bet                                            AS max_bet,
  g.distinct_games                                     AS distinct_games,
  g.active_days                                        AS active_days,
  g.first_bet_date                                     AS first_bet_date,
  g.last_bet_date                                      AS last_bet_date,
  g.real_bets                                          AS real_bets,
  g.freespins_bets                                     AS freespins_bets,
  g.primary_provider                                   AS primary_provider,

  -- ---- деньги (money_transactions) ----
  m.dep_count                                          AS dep_count,
  m.dep_sum                                            AS dep_sum,
  m.dep_failed                                         AS dep_failed,
  m.wd_count                                           AS wd_count,
  m.wd_sum                                             AS wd_sum,
  m.wd_rejected                                        AS wd_rejected,
  m.bonus_count                                        AS bonus_count,
  m.bonus_sum                                          AS bonus_sum,
  m.first_deposit_date                                 AS first_deposit_date,
  m.last_deposit_date                                  AS last_deposit_date,
  if(m.primary_payment_method='', '(none)', m.primary_payment_method) AS primary_payment_method,
  -- ---- КЭШ по спеке казино (сверяемо с их бордом; старые dep_sum/wd_sum/bonus_sum — поведенческие, не трогаем) ----
  ifNull(m.cash_deposits, 0)                           AS cash_deposits,
  ifNull(m.withdrawals_abs, 0)                          AS withdrawals_abs,
  ifNull(m.bonus_cost, 0)                               AS bonus_cost,
  round(ifNull(m.cash_deposits,0) - ifNull(m.withdrawals_abs,0), 2) AS net_cash,
  -- ---- VIP-уровень по правилам казино (накопит. успешные депозиты TRY; ≥Silver требует хотя бы 1 депозит ≥100 TRY) ----
  toUInt8(multiIf(ifNull(m.cash_max_dep_try,0)<100 OR ifNull(m.cash_deposits_try,0)<100, 0,
          m.cash_deposits_try>=1000000, 5, m.cash_deposits_try>=500000, 4,
          m.cash_deposits_try>=150000, 3, m.cash_deposits_try>=50000, 2, 1))         AS vip_level,

  -- ---- сессии (game_sessions) ----
  s.sessions_count                                     AS sessions_count,
  s.avg_session_min                                    AS avg_session_min,

  -- ---- игры и ПАТТЕРН (что играл, на чём залип, траектория) ----
  pg.favourite_game                                    AS favourite_game,
  pg.favourite_game_bets                               AS favourite_game_bets,
  if(g.bets>0, round(pg.favourite_game_bets / g.bets, 3), 0) AS game_concentration, -- доля ставок в любимой (1=моногам, ~0=исследователь)
  pg.stuck_game                                        AS stuck_game,        -- игра, в которую возвращался больше всего ДНЕЙ
  pg.stuck_game_days                                   AS stuck_game_days,
  pg.oneshot_games                                     AS oneshot_games,     -- игр попробовал 1 день и бросил
  pg.top_games                                         AS top_games,         -- [(игра, ставок)] топ-15 по ставкам
  pg.game_journey                                      AS game_journey,      -- [(игра, дата 1-й ставки, ставок)] ПО ПОРЯДКУ знакомства

  -- ---- производные признаки / метки ----
  (g.bets > 0)                                                          AS ever_played,
  if(g.bets>0, round(g.freespins_bets / g.bets, 3), 0)                  AS freespin_ratio,
  if(g.bets>0, round(g.night_bets / g.bets, 3), 0)                      AS night_share,
  if(g.bets>0, dateDiff('day', toDate(g.last_bet_date), asof), NULL) AS recency_days,
  if(g.bets>0, dateDiff('day', toDate(u.reg_date), toDate(g.first_bet_date)), NULL) AS activation_lag_days,
  if(g.bets>0, round(g.bets / g.active_days, 1), 0)                     AS bets_per_active_day,
  multiIf(g.bets=0,'never',
          dateDiff('day',toDate(g.last_bet_date),asof)<=7,'active',
          dateDiff('day',toDate(g.last_bet_date),asof)<=30,'cooling',
          dateDiff('day',toDate(g.last_bet_date),asof)<=60,'at_risk',
          dateDiff('day',toDate(g.last_bet_date),asof)<=90,'dormant','churned') AS lifecycle,
  if(u.last_login  IS NOT NULL, dateDiff('day', toDate(u.last_login),  asof), NULL) AS login_recency_days,
  if(u.last_active IS NOT NULL, dateDiff('day', toDate(u.last_active), asof), NULL) AS activity_recency_days,
  if(m.dep_count>0, dateDiff('day', toDate(m.last_deposit_date), asof), NULL)        AS deposit_recency_days,
  if(g.bets>0 AND dateDiff('day',toDate(g.last_bet_date),asof)>30, 1, 0)         AS churned_30d,
  if(g.bets>0 AND dateDiff('day',toDate(g.last_bet_date),asof)>90, 1, 0)         AS churned_90d

FROM retention.users u
LEFT JOIN (
  SELECT casino_player_id,
    countIf(transaction_type IN ('bet','freespins_bet'))                        AS bets,
    round(sumIf(bet_amount, transaction_type IN ('bet','freespins_bet')),2)     AS turnover,
    round(sumIf(win_amount, transaction_type IN ('win','freespins_win')),2)     AS wins_sum,
    if(countIf(transaction_type IN ('bet','freespins_bet'))>0, round(avgIf(bet_amount, transaction_type IN ('bet','freespins_bet')),2), 0) AS avg_bet,  -- 0 вместо NaN при отсутствии completed-ставок
    round(maxIf(bet_amount, transaction_type IN ('bet','freespins_bet')),2)     AS max_bet,
    uniqExact(game_uuid)                                                        AS distinct_games,
    uniqExact(toDate(toTimezone(created_at,'Europe/Istanbul')))                 AS active_days,
    min(created_at)                                                             AS first_bet_date,
    max(created_at)                                                             AS last_bet_date,
    countIf(transaction_type='bet')                                            AS real_bets,
    countIf(transaction_type='freespins_bet')                                  AS freespins_bets,
    countIf(transaction_type IN ('bet','freespins_bet') AND toHour(toTimezone(created_at,'Europe/Istanbul'))<6) AS night_bets,
    anyHeavy(aggregator)                                                        AS primary_provider
  FROM retention.game_transactions WHERE status='completed' GROUP BY casino_player_id
) g USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    countIf(type IN ('deposit','manual_deposit') AND status='completed')              AS dep_count,
    round(sumIf(amount, type IN ('deposit','manual_deposit') AND status='completed'),2) AS dep_sum,
    countIf(type IN ('deposit','manual_deposit') AND status IN ('rejected','failed')) AS dep_failed,
    countIf(type IN ('withdrawal','manual_withdrawal') AND status='completed')        AS wd_count,
    round(sumIf(amount, type IN ('withdrawal','manual_withdrawal') AND status='completed'),2) AS wd_sum,
    countIf(type IN ('withdrawal','manual_withdrawal') AND status='rejected')         AS wd_rejected,
    countIf(type IN ('bonus_conversion','freespin','manual_bonus','bonus') AND status='completed')        AS bonus_count,
    round(sumIf(amount, type IN ('bonus_conversion','freespin','manual_bonus','bonus') AND status='completed'),2) AS bonus_sum,
    minIf(created_at, type IN ('deposit','manual_deposit') AND status='completed')    AS first_deposit_date,
    maxIf(created_at, type IN ('deposit','manual_deposit') AND status='completed')    AS last_deposit_date,
    anyHeavyIf(payment_method, type IN ('deposit','manual_deposit') AND payment_method!='' AND payment_method NOT LIKE 'campaign:%') AS primary_payment_method,
    -- ---- КЭШ по спеке казино (deposit-only, ABS, без conversion; статусы completed/approved/success) ----
    round(sumIf(amount, type='deposit' AND status IN ('completed','approved','success')),2)                       AS cash_deposits,
    round(sumIf(abs(amount), type='withdrawal' AND status IN ('completed','approved','success')),2)               AS withdrawals_abs,
    round(sumIf(abs(amount), type IN ('bonus','manual_bonus','freespin') AND status IN ('completed','approved','success')),2) AS bonus_cost,
    -- ---- для VIP-уровня: накопит. успешные депозиты в TRY + макс. разовый (гейт ≥100 TRY) ----
    round(sumIf(amount, type='deposit' AND status IN ('completed','approved','success') AND currency='TRY'),2) AS cash_deposits_try,
    round(maxIf(amount, type='deposit' AND status IN ('completed','approved','success') AND currency='TRY'),2) AS cash_max_dep_try
  FROM retention.money_transactions GROUP BY casino_player_id
) m USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id, count() AS sessions_count, round(avg(duration_minutes),1) AS avg_session_min
  FROM retention.game_sessions GROUP BY casino_player_id
) s USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    argMax(game_uuid, c)                                              AS favourite_game,
    max(c)                                                            AS favourite_game_bets,
    argMax(game_uuid, dp)                                             AS stuck_game,
    max(dp)                                                           AS stuck_game_days,
    countIf(dp = 1)                                                   AS oneshot_games,
    arraySlice(arraySort(t -> -t.2, groupArray((substring(game_uuid,1,16), c))), 1, 15)            AS top_games,
    arraySlice(arraySort(t ->  t.2, groupArray((substring(game_uuid,1,12), toDate(fp), c))), 1, 20) AS game_journey
  FROM (
    SELECT casino_player_id, game_uuid,
           countIf(transaction_type IN ('bet','freespins_bet'))       AS c,
           min(created_at)                                            AS fp,
           uniqExact(toDate(toTimezone(created_at,'Europe/Istanbul'))) AS dp
    FROM retention.game_transactions WHERE game_uuid != ''
    GROUP BY casino_player_id, game_uuid HAVING c > 0
  )
  GROUP BY casino_player_id
) pg USING (casino_player_id);
