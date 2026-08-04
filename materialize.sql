-- ============================================================================
-- Материализация потока в форму сырых таблиц (для витрины/моделей).
-- UNION-вью: историческая таблица + трансформация стрима (live_events/users_stream).
-- Реальные таблицы НЕ трогаем. player_features читает эти вью.
--
-- Дедуп по игроку (users): при пересечении id берём версию из стрима (свежую).
-- ============================================================================

-- ---- профиль игрока -------------------------------------------------------
CREATE OR REPLACE VIEW retention.users_all AS
SELECT casino_player_id, account_type, activity_status, country_iso_estimated, currency,
       reg_date, ftd_date, ftd_amount, affiliate_account_type, affiliate_code,
       phone_verified, email_verified, status, is_active, last_login, last_active,
       balance, bonus_balance
FROM retention.users
WHERE casino_player_id NOT IN (SELECT casino_player_id FROM retention.users_stream)
UNION ALL
SELECT casino_player_id, account_type, activity_status, country AS country_iso_estimated, currency,
       reg_date, ftd_date, ftd_amount, affiliate_type AS affiliate_account_type, affiliate_code,
       phone_verified, email_verified, account_status AS status, is_active, last_login, last_active,
       balance, bonus_balance
FROM retention.users_stream FINAL;

-- ---- игровые транзакции ----------------------------------------------------
CREATE OR REPLACE VIEW retention.game_transactions_all AS
SELECT casino_player_id, transaction_type, bet_amount, win_amount, game_uuid, created_at, aggregator
FROM retention.game_transactions
UNION ALL
SELECT casino_player_id,
       multiIf(event_type='bet' AND is_freespin=1, 'freespins_bet',
               event_type='bet',                    'bet',
               event_type='win' AND is_freespin=1, 'freespins_win',
                                                    'win')            AS transaction_type,
       bet_amount, win_amount, game_uuid, ts AS created_at, provider AS aggregator
FROM retention.live_events
WHERE event_type IN ('bet','win');

-- ---- денежные транзакции ---------------------------------------------------
CREATE OR REPLACE VIEW retention.money_transactions_all AS
SELECT casino_player_id, type, status, amount, payment_method, created_at
FROM retention.money_transactions
UNION ALL
SELECT casino_player_id,
       event_type AS type,          -- deposit/withdrawal/bonus (manual/auto не различаем)
       status, amount, payment_method, ts AS created_at
FROM retention.live_events
WHERE event_type IN ('deposit','withdrawal','bonus');

-- ---- сессии ----------------------------------------------------------------
CREATE OR REPLACE VIEW retention.game_sessions_all AS
SELECT casino_player_id, duration_minutes
FROM retention.game_sessions
UNION ALL
SELECT casino_player_id, toFloat64(dateDiff('minute', min(ts), max(ts))) AS duration_minutes
FROM retention.live_events
WHERE session_id != '' AND event_type IN ('bet','win','session_start','session_end')
GROUP BY casino_player_id, session_id;
