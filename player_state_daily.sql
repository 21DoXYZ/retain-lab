-- ============================================================================
-- player_state_daily — снапшот «состояние игрока на дату данных» (point-in-time).
--
-- ЗАЧЕМ: player_features хранит только ТЕКУЩИЙ срез (DROP+CREATE каждую петлю),
-- истории сегментов нет. Конструктор отчётов и исторические выборки требуют
-- ответа «кто БЫЛ VIP / в оттоке / с каким прогнозом в феврале». Прошлое почти
-- не реконструируется из raw-фактов дёшево — поэтому начинаем КОПИТЬ срез сейчас:
-- по одной строке на игрока за каждый снятый день данных.
--
-- ДАТА СРЕЗА = data_asof = max(toDate(created_at)) по завершённым игровым
-- транзакциям — ровно та же «дата данных», от которой считается lifecycle в
-- player_features.sql:10. НЕ today(): при догрузке данных задним числом срез
-- ляжет на дату ДАННЫХ, а не на календарный день прогона.
--
-- NULL-ЧЕСТНОСТЬ: в ClickHouse LEFT JOIN подставляет несопоставленным строкам
-- ДЕФОЛТ типа (0 для чисел), а не NULL. Для p_churn / pred_ltv_d90 значение 0 —
-- ВАЛИДНО (нулевой риск, нулевой прогноз), поэтому nullIf(...,0) применять НЕЛЬЗЯ.
-- Отличаем «нет скора» от «скор = 0» по ключу приджойненной таблицы:
-- если ch.casino_player_id = 0 — строки в player_churn_ml не было → честный NULL
-- (минимальный реальный casino_player_id в данных = 38, id=0 не существует).
-- Аналогично pred_ltv_d90 из вьюхи player_ltv (в ней только депозиторы normal).
--
-- ИДЕМПОТЕНТНОСТЬ / КОНВЕНЦИЯ ЧТЕНИЯ: движок ReplacingMergeTree, ключ
-- ORDER BY (snap_date, casino_player_id). Повторный INSERT того же дня физически
-- добавляет дубли (snap_date,id), но они схлопываются при слиянии. Так как данные
-- за один день детерминированы, какой из дублей «победит» — неважно.
--   ЧИТАТЬ ВСЕГДА через FINAL:  SELECT ... FROM retention.player_state_daily FINAL
--   либо argMax по ключу        (до фонового мержа сырые дубли ещё видны без FINAL).
--
-- ПОРЯДОК: применять ПОСЛЕ пересборки player_features (см. run_loop.sh, шаг 2c).
-- Раскладка на статементы: 1-й ';' закрывает DDL, INSERT — до EOF (run_loop
-- вырезает части через sed по этим границам: DDL — каждый прогон, INSERT — под
-- суточным гардом).
-- ============================================================================

CREATE TABLE IF NOT EXISTS retention.player_state_daily
(
  snap_date         Date,
  casino_player_id  UInt32,
  vip_level         UInt8,
  lifecycle         LowCardinality(String),
  dep_sum           Float64,
  dep_count         UInt32,
  net               Float64,
  net_cash          Float64,
  early_tier        LowCardinality(String),
  p_churn           Nullable(Float32),
  pred_ltv_d90      Nullable(Float64)
)
ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMM(snap_date)
ORDER BY (snap_date, casino_player_id);

INSERT INTO retention.player_state_daily
WITH (SELECT max(toDate(created_at)) FROM retention.game_transactions WHERE status = 'completed') AS asof
SELECT
  asof                                                        AS snap_date,
  f.casino_player_id                                          AS casino_player_id,
  f.vip_level                                                 AS vip_level,
  f.lifecycle                                                 AS lifecycle,
  f.dep_sum                                                   AS dep_sum,
  f.dep_count                                                 AS dep_count,
  f.net                                                       AS net,
  f.net_cash                                                  AS net_cash,
  ltv.early_tier                                              AS early_tier,
  -- честный NULL там, где скора/строки нет (см. шапку: 0 — валидное значение)
  if(ch.casino_player_id  = 0, NULL, toFloat32(ch.p_churn))   AS p_churn,
  if(ltv.casino_player_id = 0, NULL, ltv.pred_ltv_d90)        AS pred_ltv_d90
FROM retention.player_features AS f
LEFT JOIN retention.player_churn_ml AS ch ON ch.casino_player_id  = f.casino_player_id
LEFT JOIN retention.player_ltv      AS ltv ON ltv.casino_player_id = f.casino_player_id;
