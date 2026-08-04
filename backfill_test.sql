-- ============================================================================
-- СИНТЕТИЧЕСКИЙ БЭКФИЛЛ тестовых игроков (casino_player_id 1000000..1001999).
-- Цель: прогнать ВСЮ петлю (features → модели → сигналы → казино) на синтетике.
--
-- Пишет прямо в сырые таблицы, но ТОЛЬКО тестовые ID 1M+ — реальные строки
-- не затрагиваются. Якорь времени = 2026-06-04 18:00 (конец реальных данных),
-- поэтому max(created_at) НЕ сдвигается и предикты реальных игроков не искажаются.
--
-- Паттерн: у игрока pid последняя активность ≈ якорь − (pid % 60) дней,
-- активность размазана на ~45 дней назад от неё → полный спектр lifecycle
-- (active / cooling / at_risk) для churn-модели. Каждый 50-й игрок — «кит»
-- (крупные ставки и депозиты) → сигнал для LTV-тиров.
--
-- Очистка синтетики (одной командой на таблицу):
--   ALTER TABLE retention.users              DELETE WHERE casino_player_id >= 1000000;
--   ALTER TABLE retention.game_transactions  DELETE WHERE casino_player_id >= 1000000;
--   ALTER TABLE retention.money_transactions DELETE WHERE casino_player_id >= 1000000;
--   ALTER TABLE retention.game_sessions      DELETE WHERE casino_player_id >= 1000000;
-- ============================================================================

-- ---- профиль (2000 игроков) ------------------------------------------------
INSERT INTO retention.users
  (casino_player_id, account_type, activity_status, country_iso_estimated, currency,
   reg_date, ftd_date, ftd_amount, affiliate_account_type, affiliate_code,
   phone_verified, email_verified, status, is_active, last_login, last_active,
   balance, bonus_balance)
SELECT
  toUInt32(1000000 + number),
  'normal', 'active', 'TR', 'TRY',
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay(120 + (rand(1) % 280)),
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay(60 + (rand(2) % 55)),
  toDecimal64(50 + (rand(3) % 2000), 2),
  if(rand(4) % 3 = 0, 'cpa', ''),
  if(rand(5) % 3 = 0, ['aff_gold','aff_silver','tg_channel'][1 + (rand(6) % 3)], ''),
  'true', 'true', 'active', 'true',
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay(number % 60),
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay(number % 60),
  toDecimal64(rand(7) % 5000, 2), toDecimal64(rand(8) % 500, 2)
FROM numbers(2000);

-- ---- ставки (~250 на игрока = 500k строк) -----------------------------------
INSERT INTO retention.game_transactions
  (casino_player_id, session_id, aggregator, game_uuid, transaction_type,
   bet_amount, win_amount, amount, currency, status,
   balance_before, balance_after, created_at)
SELECT
  toUInt32(1000000 + pid),
  concat('bf-', toString(pid), '-', toString(intDiv(ev, 15))),
  ['pragmatic','hacksaw','nolimit','pgsoft','evolution','playngo'][1 + (pid % 6)],
  ['pragmatic/gates-of-olympus','hacksaw/wanted','nolimit/mental',
   'pgsoft/fortune-tiger','evolution/crazy-time','playngo/book-of-dead'][1 + (pid % 6)],
  if(rand(1) % 100 < 15, 'freespins_bet', 'bet'),
  toDecimal64(5 + (rand(2) % if(pid % 50 = 0, 2000, 200)), 2),
  toDecimal64(0, 2),
  toDecimal64(5 + (rand(2) % if(pid % 50 = 0, 2000, 200)), 2),
  'TRY', 'completed',
  toDecimal64(rand(3) % 10000, 2), toDecimal64(rand(4) % 10000, 2),
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay(pid % 60) - toIntervalSecond(rand(5) % (45 * 86400))
FROM (SELECT number % 2000 AS pid, intDiv(number, 2000) AS ev FROM numbers(500000));

-- ---- выигрыши (~35% от ставок, игрок в среднем в минусе) --------------------
INSERT INTO retention.game_transactions
  (casino_player_id, session_id, aggregator, game_uuid, transaction_type,
   bet_amount, win_amount, amount, currency, status,
   balance_before, balance_after, created_at)
SELECT
  toUInt32(1000000 + pid),
  concat('bf-', toString(pid), '-', toString(intDiv(ev, 5))),
  ['pragmatic','hacksaw','nolimit','pgsoft','evolution','playngo'][1 + (pid % 6)],
  ['pragmatic/gates-of-olympus','hacksaw/wanted','nolimit/mental',
   'pgsoft/fortune-tiger','evolution/crazy-time','playngo/book-of-dead'][1 + (pid % 6)],
  if(rand(1) % 100 < 15, 'freespins_win', 'win'),
  toDecimal64(0, 2),
  toDecimal64(10 + (rand(2) % if(pid % 50 = 0, 4000, 400)), 2),
  toDecimal64(10 + (rand(2) % if(pid % 50 = 0, 4000, 400)), 2),
  'TRY', 'completed',
  toDecimal64(rand(3) % 10000, 2), toDecimal64(rand(4) % 10000, 2),
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay(pid % 60) - toIntervalSecond(rand(5) % (45 * 86400))
FROM (SELECT number % 2000 AS pid, intDiv(number, 2000) AS ev FROM numbers(175000));

-- ---- депозиты (~5 на игрока, 88% completed) ---------------------------------
INSERT INTO retention.money_transactions
  (casino_player_id, type, status, amount, currency, payment_method, created_at)
SELECT
  toUInt32(1000000 + (number % 2000)),
  'deposit',
  if(rand(1) % 100 < 88, 'completed', if(rand(2) % 2 = 0, 'rejected', 'failed')),
  toDecimal64(50 + (rand(3) % if((number % 2000) % 50 = 0, 5000, 500)), 2),
  'TRY',
  ['papara','havale','credit_card','crypto_usdt','payfix'][1 + (rand(4) % 5)],
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay((number % 2000) % 60) - toIntervalSecond(rand(5) % (45 * 86400))
FROM numbers(10000);

-- ---- выводы (~1.5 на игрока, 75% completed) ---------------------------------
INSERT INTO retention.money_transactions
  (casino_player_id, type, status, amount, currency, payment_method, created_at)
SELECT
  toUInt32(1000000 + (number % 2000)),
  'withdrawal',
  if(rand(1) % 100 < 75, 'completed', 'rejected'),
  toDecimal64(100 + (rand(2) % 1500), 2),
  'TRY', '',
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay((number % 2000) % 60) - toIntervalSecond(rand(3) % (40 * 86400))
FROM numbers(3000);

-- ---- сессии (~15 на игрока) --------------------------------------------------
INSERT INTO retention.game_sessions
  (casino_player_id, session_id, aggregator, game_uuid, currency, status, is_active,
   duration_minutes, created_at)
SELECT
  toUInt32(1000000 + (number % 2000)),
  concat('bf-', toString(number % 2000), '-', toString(intDiv(number, 2000))),
  ['pragmatic','hacksaw','nolimit','pgsoft','evolution','playngo'][1 + ((number % 2000) % 6)],
  ['pragmatic/gates-of-olympus','hacksaw/wanted','nolimit/mental',
   'pgsoft/fortune-tiger','evolution/crazy-time','playngo/book-of-dead'][1 + ((number % 2000) % 6)],
  'TRY', 'closed', 'false',
  round(5 + (rand(1) % 120), 1),
  toDateTime64('2026-06-04 18:00:00', 3) - toIntervalDay((number % 2000) % 60) - toIntervalSecond(rand(2) % (45 * 86400))
FROM numbers(30000);
