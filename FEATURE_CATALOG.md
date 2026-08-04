# Каталог фич (500+) — обогащение данных для моделей

> Цель: из реальных столбцов наших таблиц вывести максимум **осмысленных** фич для разных моделей.
> Всё привязано к живым данным (мёртвые колонки исключены). Наименования — code-convention (`snake_case`).

## Легенда

**Модель-теги:** `[C]` churn (отток 30д) · `[L]` LTV (депозиты d90) · `[R]` repeat (2-й депозит) · `[D]` ladder (следующий депозит) · `[B]` bonus (отклик на бонус) · `[Rk]` risk/RG · `[F]` fraud/абьюз · `[Re]` reactivation (реактивация спящих, НОВАЯ) · `[Dc]` decline (затухание ценности, НОВАЯ) · `[V]` value (сегментация ценности)

**Статус:** ✅ уже есть (в витрине/модели) · 🆕 новая

**Окна (W):** `1d, 3d, 7d, 14d, 30d, 60d, 90d, life` (точка отсчёта — момент скоринга T; все считаются на `created_at < T` — защита от утечки).

---

## 0. Инвентарь столбцов (что есть и что показывает)

### Живые источники
| Таблица | Ключевые живые столбцы | Что показывает |
|---|---|---|
| `game_transactions` (62M) | transaction_type, bet_amount, win_amount, aggregator, game_uuid, round_id, session_id, balance_before/after, currency, status, created_at | каждая ставка/выигрыш: сумма, игра, провайдер, раунд, сессия, баланс, время |
| `money_transactions` (166k) | type, status, amount, payment_method, rejection_reason, sent_at, balance_before/after, bonus_balance_before/after, created_at, processed_at | депозиты/выводы/бонусы: сумма, метод, отказ, время обработки, баланс |
| `users` (42k) | reg_date, ftd_date, ftd_amount, country_iso_estimated, phone_country_code, timezone, affiliate_code/type, registration_source, account_type, status, balance, bonus_balance | профиль, привлечение, гео, статус |
| `game_sessions` (270k) | session_id, aggregator, game_uuid, started_at/ended_at | связка сессий (длительность реконструируем из game_transactions) |

### Мёртвые колонки — НЕ использовать
`game_sessions.device`=всегда desktop · `duration_minutes`=всегда 0 · `mode`=всегда real · `money.fees`=0 · `assigned_bank_name`=пусто · `users.telegram_id/has_whatsapp/has_viber/marketing_consent/risk_tags/rg_flag/self_excluded`=пусты. Контактность/консент/RG — не покрыты (можно запросить у казино).

### Что модели используют СЕЙЧАС (~существующие фичи)
- **Витрина `player_features`** (~72 кол.): tenure_days, bets, turnover, wins_sum, net, avg_bet, max_bet, distinct_games, active_days, real_bets, freespins_bets, primary_provider, dep_count/sum, wd_count/sum, bonus_count/sum, cash_deposits, withdrawals_abs, bonus_cost, net_cash, vip_level, favourite/stuck_game, game_concentration, freespin_ratio, night_share, recency_days, activation_lag_days, bets_per_active_day, lifecycle, *_recency_days, churned_30/90d.
- **churn**: recency_at_T, tenure_at_T, bets/turnover/active_days_to_T, avg_bet, freespin_ratio, night_share, bets_last7/prev7/last30, momentum_7v7, expected_gap, overdue_ratio, is_depositor, dep_count/sum, deposit_recency, +cat(provider,country,affiliate,payment).
- **ltv**: ftd_amount, act_lag_days, dep_d1/d7, ndep_d7, bets/turnover/avg_bet/distinct_games/active_days/freespin/night_d7, +cat.
- **repeat**: как ltv, но окно первого дня (d0).
- **ladder**: deposit_number, days_since_reg, gap_before, total/avg/max_to_k, mean_gap, this_amount, +cat.
- **bonus**: recency, tenure, bets, turnover, active_days, avg_bet, freespin_ratio, night_share, dep_count/sum, deposit_recency, +cat(provider,country,affiliate,bonus_type).

---

## 1. Активность — оконные агрегаты `[C][L][Dc][Re][V]`
Базовый паттерн: `<метрика>_<W>`. Все — новые, кроме отмеченных ✅.

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 1–8 | `bets_{1d,3d,7d,14d,30d,60d,90d,life}` | число ставок в окне (7d/30d ✅) | C, Dc, Re |
| 9–16 | `real_bets_{W×8}` | ставки реальными деньгами (не фриспины) | C, Rk, F |
| 17–24 | `freespin_bets_{W×8}` | ставки с бонус-баланса | B, F |
| 25–32 | `turnover_{W×8}` | оборот (Σ bet) в окне (d7 ✅) | L, V, Dc |
| 33–40 | `wins_{W×8}` | Σ выигрышей в окне | L, F |
| 41–48 | `net_{W×8}` | net игрока (win−bet) в окне | Dc, F, Rk |
| 49–56 | `ggr_{W×8}` | GGR казино (bet−win) в окне | V, L |
| 57–64 | `active_days_{W×8}` | активных дней в окне (life ✅) | C, Re, Dc |
| 65–72 | `distinct_games_{W×8}` | уник. игр в окне | B, Dc |
| 73–80 | `sessions_{W×8}` | число сессий в окне | C, Dc |
| 81–88 | `rounds_{W×8}` | число раундов (round_id) в окне | Dc, F |
| 89 | `bets_lifetime` ✅ | всего ставок | C, V |
| 90 | `active_days_since_reg` | активных дней от регистрации | C, Re |

## 2. Моментум / тренд / ускорение `[C][Dc][Re]`
Отношения окон — ловят изменение паттерна (падение чека/частоты — то, что просил эксперт).

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 91 | `momentum_bets_7v7` ✅ | ставки 7д ÷ пред.7д | C, Dc |
| 92–96 | `momentum_bets_{3v3,14v14,30v30,7v30,7v14}` | частота: разные горизонты | C, Dc |
| 97–101 | `momentum_turnover_{7v7,14v14,30v30,7v30,7v14}` | оборот растёт/падает | Dc, L |
| 102–106 | `momentum_avg_bet_{7v7,14v14,30v30,7v30,7v14}` | **средний чек** тренд | Dc, C |
| 107–111 | `momentum_net_{7v7,14v14,30v30,7v30,7v14}` | результат тренд | F, Dc |
| 112–116 | `momentum_deposit_{7v7,14v14,30v30,7v30,7v14}` | депозиты тренд | L, Dc |
| 117–121 | `momentum_sessions_{7v7,14v14,30v30,7v30,7v14}` | частота сессий тренд | C, Dc |
| 122–126 | `momentum_active_days_{...}` | вовлечённость тренд | Re, Dc |
| 127 | `trend_turnover_30d` | наклон линейной регрессии оборота по дням | Dc, L |
| 128 | `trend_bets_30d` | наклон числа ставок | C, Dc |
| 129 | `trend_avg_bet_30d` | наклон среднего чека | Dc |
| 130 | `trend_net_30d` | наклон net | F, Dc |
| 131 | `accel_turnover` | ускорение (изм. наклона 15д vs 15-30д) | Dc |
| 132 | `accel_bets` | ускорение частоты | C, Dc |
| 133 | `days_since_peak_turnover` | дней с пика оборота | Dc |
| 134 | `days_since_peak_bet` | дней с макс. ставки | Rk, Dc |
| 135 | `pct_from_peak_turnover` | текущий оборот в % от пикового | Dc, Re |
| 136 | `weeks_declining_streak` | недель подряд падения оборота | Dc, C |
| 137 | `is_reactivated` | вернулся после паузы >14д | Re |
| 138 | `dormancy_count` | сколько раз «засыпал» и возвращался | Re, C |

## 3. Размер ставки — распределение и волатильность `[Rk][F][V]`
Из `bet_amount` (реальные ставки).

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 139 | `avg_bet` ✅ | средняя ставка | все |
| 140 | `median_bet` | медианная ставка | V, Rk |
| 141 | `max_bet` ✅ | макс. ставка | Rk, V |
| 142 | `min_bet` | мин. ставка | V |
| 143 | `bet_stddev` | разброс ставок | Rk, F |
| 144 | `bet_cv` | коэф. вариации (stddev/avg) | Rk, F |
| 145–150 | `bet_p{10,25,75,90,95,99}` | перцентили ставки | V, Rk |
| 151 | `bet_range` | max−min | Rk |
| 152 | `bet_iqr` | межквартильный размах | Rk |
| 153 | `bet_skew` | асимметрия (склонность к крупным) | Rk, F |
| 154 | `max_to_avg_bet` | max ÷ avg (всплески) | Rk, F |
| 155 | `bet_escalation_ratio` | ср.ставка 2-й половины ÷ 1-й | Rk, Dc |
| 156 | `high_bet_share` | доля ставок >p90 персональной | Rk |
| 157 | `round_bet_share` | доля «круглых» ставок (10/50/100) | F |
| 158 | `distinct_bet_sizes` | сколько разных номиналов ставки | F, V |
| 159 | `modal_bet` | самый частый номинал ставки | V |
| 160 | `bet_size_entropy` | энтропия распределения ставок | F, Rk |
| 161 | `first_bet_amount` | ставка самой первой игры | R, L |
| 162 | `bet_growth_life` | ср.ставка last30 ÷ first30 | V, Dc |

## 4. Депозиты — поведение и лестница `[L][R][D][V]`
Из `money_transactions type='deposit'`.

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 163 | `dep_count` ✅ | число успешных депозитов | L, D |
| 164 | `dep_sum` / `cash_deposits` ✅ | Σ депозитов | L, V |
| 165 | `ftd_amount` ✅ | первый депозит | L, R |
| 166 | `avg_deposit` | средний депозит | L, V |
| 167 | `median_deposit` | медиана депозита | V |
| 168 | `max_deposit` | макс. депозит | V, Rk |
| 169 | `min_deposit` | мин. депозит | V |
| 170 | `deposit_stddev` | разброс депозитов | Rk |
| 171 | `deposit_cv` | вариация депозитов | Rk |
| 172 | `dep_d1` ✅ | депозиты в 1-й день | L, R |
| 173 | `dep_d7` ✅ | депозиты за 7д от FTD | L |
| 174 | `dep_d30` | депозиты за 30д от FTD | L |
| 175 | `ndep_d7` ✅ | число депозитов за 7д | L |
| 176 | `deposit_number` ✅ | порядковый номер депозита | D |
| 177 | `days_to_2nd_deposit` | дней между 1-м и 2-м | R, D |
| 178 | `days_to_ftd` / `activation_lag` ✅ | рег → FTD | R, L |
| 179 | `mean_deposit_gap` ✅ | средний интервал между депозитами | D |
| 180 | `median_deposit_gap` | медианный интервал | D |
| 181 | `deposit_gap_stddev` | регулярность депозитов | D, Rk |
| 182 | `last_deposit_gap` | дней с последнего депозита ✅ | D, C |
| 183 | `deposit_regularity` | 1/(1+cv интервалов) | D, V |
| 184 | `deposit_escalation` | последние 3 депозита растут? | L, V |
| 185 | `deposit_amount_trend` | наклон сумм депозитов | L, Dc |
| 186 | `dep_failed` ✅ | отклонённых депозитов | F, Rk |
| 187 | `deposit_fail_ratio` | отказы ÷ попытки депозита | F, Rk |
| 188 | `dep_pending_count` | депозитов в pending | F |
| 189 | `deposits_per_active_day` | депозитов на активный день | V |
| 190 | `first_deposit_hour` | час суток FTD | L, Rk |
| 191 | `first_deposit_weekday` | день недели FTD | L |
| 192 | `total_to_k` ✅ | Σ депозитов до k-го | D |
| 193 | `avg_to_k` ✅ | средний до k-го | D |
| 194 | `max_to_k` ✅ | макс. до k-го | D |
| 195 | `gap_before` ✅ | интервал перед k-м | D |
| 196 | `deposit_velocity_30d` | сумма депозитов за 30д / 30 | L, V |
| 197 | `is_high_roller` | avg_deposit > p95 базы | V, Rk |
| 198 | `deposit_recency_ratio` | last_gap / mean_gap (просрочка депозита) | D, C |

## 5. Выводы — поведение и обработка `[F][Rk][C]`
Из `money_transactions type='withdrawal'` + `sent_at`, `rejection_reason`.

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 199 | `wd_count` ✅ | успешных выводов | F |
| 200 | `wd_sum` / `withdrawals_abs` ✅ | Σ выводов | F, V |
| 201 | `avg_withdrawal` | средний вывод | F, V |
| 202 | `max_withdrawal` | макс. вывод | Rk, F |
| 203 | `wd_rejected` ✅ | отклонённых выводов | F, Rk |
| 204 | `withdrawal_reject_ratio` | отказы ÷ попытки вывода | F, Rk |
| 205 | `wd_pending_count` | выводов в pending | F |
| 206 | `wd_attempts_total` | все попытки вывода (любой статус) | F, Rk |
| 207 | `withdrawal_attempts_per_day` | частота попыток вывода | F |
| 208 | `avg_withdrawal_processing_min` | ср. время processed−created | F |
| 209 | `avg_withdrawal_payout_min` | ср. время sent_at−created | F |
| 210 | `withdrawal_retry_burst` | макс. попыток вывода за 1 час | F |
| 211 | `first_withdrawal_after_reg_days` | дней рег → 1-й вывод | F, Rk |
| 212 | `min_gap_deposit_to_withdrawal` | мин. интервал деп→вывод (мгновенный кэшаут) | F |
| 213 | `avg_gap_deposit_to_withdrawal` | ср. интервал деп→вывод | F |
| 214 | `fast_cashout_ratio` | доля выводов в <1ч после депозита | F |
| 215 | `withdraw_without_play_flag` | вывод без ставок между деп и выводом | F |
| 216 | `withdrawal_to_deposit_count` | выводов ÷ депозитов | F, V |
| 217 | `distinct_withdrawal_methods` | разных методов вывода | F |
| 218 | `withdrawal_method_switches` | смен метода вывода | F |
| 219 | `pending_withdrawal_amount` | сумма в pending сейчас | F |
| 220 | `net_cash` ✅ | касса: депозиты − выводы | V, F, Rk |
| 221 | `cashout_pressure` | (pending+rejected выводы) ÷ депозиты | F |
| 222 | `has_manual_withdrawal` | были ручные корректировки (бонус) | F, B |
| 223 | `withdrawal_amount_vs_deposit` | ср.вывод ÷ ср.депозит | F, V |

## 6. Денежные потоки и финансовые отношения `[V][L][F]`

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 224 | `ggr_lifetime` | GGR казино за всё | V, L |
| 225 | `ngr_proxy` | GGR − bonus_cost | V |
| 226 | `hold_pct` | GGR ÷ turnover (маржа) | V, F |
| 227 | `personal_rtp` | wins ÷ bets ×100 | F, Rk |
| 228 | `rtp_deviation` | personal_rtp − 96 (аномалия удачи) | F |
| 229 | `cash_efficiency` | net_cash ÷ cash_deposits | V, F |
| 230 | `reinvest_ratio` | turnover ÷ cash_deposits (сколько раз прокрутил депозит) | V |
| 231 | `bonus_to_deposit_ratio` | bonus_cost ÷ cash_deposits | B, F |
| 232 | `turnover_per_deposit` | оборот ÷ депозит | V |
| 233 | `win_to_bet_ratio` | wins ÷ bets | F |
| 234 | `deposit_to_turnover` | депозиты ÷ оборот (доля «свежих» денег) | V, F |
| 235 | `net_position` | balance + bonus_balance − непокрытые обязательства | V |
| 236 | `lifetime_value_realized` | net_cash × −1 (сколько казино заработало кэшем) | V, L |
| 237 | `revenue_per_active_day` | GGR ÷ active_days | V |
| 238 | `revenue_per_session` | GGR ÷ sessions | V |
| 239 | `bonus_cost_share_of_ggr` | bonus_cost ÷ GGR | B |
| 240 | `provider_cost_proxy` | Σ по студиям (ставки) | V |
| 241 | `margin_trend_30d` | наклон hold% по дням | Dc, V |
| 242 | `is_profitable_for_casino` | net_cash ≥ 0 И net ≤ 0 | V, F |
| 243 | `loss_to_deposit_ratio` | (−net) ÷ депозиты (насколько «слил») | V, Rk |
| 244 | `whale_score` | комбо: dep_sum×hold×tenure нормир. | V |

## 7. Бонусы — использование и зависимость `[B][F][Rk]`

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 245 | `bonus_count` ✅ | число бонусов | B |
| 246 | `bonus_sum` / `bonus_cost` ✅ | Σ бонусов | B |
| 247 | `freespin_ratio` ✅ | доля фриспин-ставок | B, F |
| 248 | `bonus_bet_share` | Σ бонус-ставок ÷ Σ всех ставок | F, Rk |
| 249 | `abuse_ratio` | (bonus_bet+bonus_cost) ÷ bet ×100 (Risk/Abuse) | F, Rk |
| 250 | `bonus_per_deposit` | бонусов ÷ депозитов | B, F |
| 251 | `bonus_conversion_count` | завершённых отыгрышей | B |
| 252 | `bonus_conversion_rate` | отыграно ÷ выдано | B |
| 253 | `days_since_last_bonus` | давность бонуса | B |
| 254 | `first_bonus_type` | тип первого бонуса | B |
| 255 | `dominant_bonus_type` | самый частый тип бонуса | B |
| 256 | `distinct_bonus_types` | разнообразие бонусов | B |
| 257 | `deposit_match_count` | депозит-матч бонусов | B |
| 258 | `freespin_bonus_count` | фриспин-бонусов | B |
| 259 | `cashback_count` | кэшбэков | B |
| 260 | `nodeposit_bonus_count` | бездеп-бонусов | B, F |
| 261 | `manual_bonus_count` | ручных бонусов | B |
| 262 | `bonus_balance_now` ✅ | текущий бонус-баланс | B |
| 263 | `bonus_balance_ratio` | bonus_balance ÷ balance | B |
| 264 | `plays_only_on_bonus` | ставит только с бонуса (real_bets≈0) | F, B |
| 265 | `bonus_reliance_trend` | тренд bonus_bet_share по времени | B, F |
| 266 | `bonus_before_deposit_flag` | получал бонус до первого депозита | F |
| 267 | `retained_after_bonus_30d` | (метка) играл 30д после бонуса | B (target) |
| 268 | `deposited_after_bonus_14d` | (метка) внёс за 14д после бонуса | B (target) |
| 269 | `bonus_roi_proxy` | (net после бонуса) ÷ bonus_cost | B, F |
| 270 | `no_deposit_but_bonus_flag` | 0 депозитов, но есть бонусы | F |

## 8. Сессии — интенсивность и ритм (реконструкция из game_transactions) `[C][Dc][Rk]`
`duration = max(created_at)−min(created_at)` внутри session_id.

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 271 | `sessions_count` ✅ | всего сессий | C |
| 272 | `avg_session_duration_min` | ср. длит. сессии (реконстр.) | C, Rk |
| 273 | `median_session_duration_min` | медиана длит. | Rk |
| 274 | `max_session_duration_min` | макс. длит. (марафон) | Rk |
| 275 | `avg_spins_per_session` | ставок на сессию | Dc, Rk |
| 276 | `max_spins_per_session` | макс. ставок за сессию | Rk |
| 277 | `avg_bets_per_minute` | интенсивность (ставок/мин) | Rk, F |
| 278 | `sessions_per_active_day` | сессий на активный день | C, Dc |
| 279 | `avg_session_turnover` | оборот на сессию | V, Dc |
| 280 | `avg_session_net` | результат на сессию | F |
| 281 | `long_session_ratio` | доля сессий >60 мин | Rk |
| 282 | `short_session_ratio` | доля сессий <5 мин | Dc |
| 283 | `avg_gap_between_sessions_h` | ср. интервал между сессиями (часы) | C, Re |
| 284 | `session_gap_stddev` | регулярность заходов | C, Dc |
| 285 | `days_since_last_session` | давность последней сессии | C, Re |
| 286 | `sessions_last7` | сессий за 7д | C, Dc |
| 287 | `session_frequency_trend` | тренд частоты сессий | Dc |
| 288 | `binge_flag` | ≥3 сессий подряд без длинных пауз | Rk |
| 289 | `avg_games_per_session` | уник. игр за сессию | Dc |
| 290 | `night_session_ratio` | доля ночных сессий | Rk |
| 291 | `session_intensity_trend` | тренд ставок/мин | Rk, Dc |
| 292 | `first_session_duration` | длит. первой сессии | R, L |
| 293 | `first_session_spins` | ставок в первой сессии | R, L |
| 294 | `first_session_net` | результат первой сессии | R |
| 295 | `avg_session_start_hour` | типичный час захода | Re |
| 296 | `session_start_hour_shift` | сдвиг часа захода last7 vs prev | Dc, Re |
| 297 | `weekend_session_ratio` | доля сессий в выходные | V |
| 298 | `session_streak_days` | дней подряд с сессией | C, V |
| 299 | `max_dormancy_days` | макс. пауза без сессий | Re, C |
| 300 | `comeback_count` | возвратов после паузы >7д | Re |

## 9. Время суток / день недели `[Rk][V][Re]`
Из `toHour/toDayOfWeek(toTimezone(created_at,'Europe/Istanbul'))`.

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 301 | `night_share` ✅ | доля игры 00–06 | Rk |
| 302 | `morning_share` | 06–12 | Re |
| 303 | `afternoon_share` | 12–18 | V |
| 304 | `evening_share` | 18–24 | V |
| 305–316 | `hour_bucket_share_{h}` (12×2ч) | профиль по 2-часовым слотам | Re, Rk |
| 317 | `modal_play_hour` | самый частый час игры | Re |
| 318 | `play_hour_entropy` | «размазанность» по часам | Rk, F |
| 319 | `night_share_shift_7v30` | сдвиг ночной доли | Dc, Re |
| 320 | `late_night_ratio` | доля 02–05 (проблемная игра) | Rk |
| 321–327 | `weekday_share_{mon..sun}` | доля по дням недели | V, Re |
| 328 | `weekend_ratio` | доля игры сб+вс | V |
| 329 | `peak_weekday` | самый активный день недели | Re |
| 330 | `weekday_entropy` | равномерность по дням | Rk |
| 331 | `payday_activity_flag` | всплеск 1-го/15-го числа | V |
| 332 | `days_active_of_last_7` | сколько из 7 дней играл | C, Dc |
| 333 | `days_active_of_last_30` | из 30 | C, Re |
| 334 | `activity_regularity_score` | равномерность активных дней | C, V |

## 10. Игры и провайдеры — разнообразие и предпочтения `[B][Dc][V]`

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 335 | `distinct_games` ✅ | уник. игр за всё | B, Dc |
| 336 | `distinct_providers` | уник. провайдеров (aggregator) | B, Dc |
| 337 | `game_concentration` ✅ | доля ставок в любимой игре (HHI-прокси) | Dc, B |
| 338 | `provider_concentration` | HHI по провайдерам | B |
| 339 | `favourite_game` ✅ | любимая игра | B |
| 340 | `favourite_game_share` | доля ставок в ней | Dc |
| 341 | `favourite_provider` | любимый провайдер | B |
| 342 | `favourite_provider_share` | доля оборота у него | B |
| 343 | `top3_games_share` | доля топ-3 игр | Dc |
| 344 | `top3_providers_share` | доля топ-3 провайдеров | B |
| 345 | `stuck_game` ✅ | игра, куда возвращался дольше всего | B |
| 346 | `stuck_game_days` ✅ | дней возврата в неё | B |
| 347 | `oneshot_games` ✅ | игр попробовал 1 день и бросил | Dc |
| 348 | `oneshot_ratio` | доля «однодневных» игр | Dc |
| 349 | `game_exploration_rate` | новых игр за 30д ÷ всего | Dc, Re |
| 350 | `new_games_last7` | новых игр за неделю | Dc |
| 351 | `game_switch_rate` | смен игры на 100 ставок | Rk, Dc |
| 352 | `provider_switch_rate` | смен провайдера | B |
| 353 | `is_slot_only` | играет только слоты | V |
| 354 | `high_volatility_game_share` | доля игр 1000-серии (Gates 1000 итд) | Rk |
| 355 | `tumble_game_share` | доля tumble-игр (Sweet Bonanza тип) | V |
| 356 | `avg_wins_per_round` | выигрышей на раунд (round_id) — каскадность | V |
| 357 | `favourite_game_stability` | не менял любимую игру последние 30д | Dc |
| 358 | `game_loyalty_score` | 1/(1+exploration_rate) | Dc, V |
| 359 | `distinct_games_trend` | тренд разнообразия | Dc |
| 360 | `provider_ggr_alignment` | играет в провайдеров с высокой нашей маржой? | V |
| 361–370 | `share_provider_{top10}` | доля оборота по 10 крупнейшим провайдерам | B, V |
| 371 | `games_per_session_avg` | уник. игр на сессию | Dc |
| 372 | `first_game_provider` | провайдер самой первой игры | R, L |
| 373 | `sport_vs_casino_ratio` | (если появятся sport-ставки) | V |
| 374 | `bet_amount_by_favourite` | ср.ставка в любимой игре | V |

## 11. Провайдерные срезы (per-provider, для микс-моделей) `[B][V]`
Для топ-N провайдеров игрока — оборот/net/доля. (генерирует ~N×3 фич; N=8)

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 375–382 | `prov{1..8}_turnover_share` | доля оборота в i-м провайдере | B, V |
| 383–390 | `prov{1..8}_net` | net игрока по i-му провайдеру | F, V |
| 391–398 | `prov{1..8}_rtp` | персональный RTP по провайдеру | F |
| 399 | `provider_rtp_variance` | разброс RTP между провайдерами | F |
| 400 | `best_provider_for_player` | где игрок больше всего выигрывает | F |
| 401 | `worst_provider_for_player` | где больше всего проигрывает | V |
| 402 | `provider_diversity_index` | Шеннон по провайдерам | B |

## 12. Жизненный цикл, стаж, скорость `[C][Re][V]`

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 403 | `tenure_days` ✅ | стаж от регистрации | C, V |
| 404 | `tenure_since_ftd` | стаж от первого депозита | L, V |
| 405 | `recency_days` ✅ | дней с последней ставки | C, Re |
| 406 | `login_recency_days` ✅ | дней с логина | C, Re |
| 407 | `deposit_recency_days` ✅ | дней с депозита | D, C |
| 408 | `activity_density` | active_days ÷ tenure | C, V |
| 409 | `activation_lag_days` ✅ | рег → первая ставка | R, L |
| 410 | `expected_gap` ✅ | ожидаемый интервал между ставками | C |
| 411 | `overdue_ratio` ✅ | recency ÷ expected_gap (просрочка) | C, Re |
| 412 | `lifecycle` ✅ | стадия (active..churned) | все |
| 413 | `lifecycle_numeric` | стадия числом 0–5 | C, Re |
| 414 | `days_in_current_stage` | дней в текущей стадии | Re |
| 415 | `stage_downgrade_flag` | ушёл в стадию хуже за 14д | Dc, C |
| 416 | `lifetime_stage_transitions` | сколько раз менял стадию | Re |
| 417 | `is_new_player` | tenure < 7д | R, L |
| 418 | `is_established` | tenure > 90д и активен | V |
| 419 | `weeks_since_reg` | недель от регистрации | все |
| 420 | `age_bucket` | корзина стажа (0-7/8-30/31-90/90+) | V |
| 421 | `churned_30d` ✅ | метка оттока 30д | C (target) |
| 422 | `churned_90d` ✅ | метка оттока 90д | C |
| 423 | `survival_weeks` | недель активности до первой длинной паузы | C |
| 424 | `honeymoon_intensity` | активность первых 7 дней | R, L |
| 425 | `value_realized_per_tenure_day` | GGR ÷ tenure | V |

## 13. Риск / ответственная игра (RG) `[Rk]`
Поведенческие маркеры (RG-флаги казино пусты — считаем сами).

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 426 | `loss_chasing_score` | рост ставок после проигрышей | Rk |
| 427 | `deposit_after_loss_ratio` | доля депозитов сразу после крупного проигрыша | Rk |
| 428 | `deposit_velocity_1d` | депозитов за 24ч (макс) | Rk, F |
| 429 | `max_deposits_per_day` | макс. депозитов за день | Rk, F |
| 430 | `escalating_deposits_flag` | депозиты растут при отрицательном net | Rk |
| 431 | `late_night_play_ratio` | доля игры 02–06 | Rk |
| 432 | `marathon_session_flag` | сессия >3ч | Rk |
| 433 | `bets_per_minute_max` | пиковая интенсивность | Rk |
| 434 | `net_drawdown` | макс. просадка баланса | Rk |
| 435 | `consecutive_loss_days` | дней подряд в минусе | Rk |
| 436 | `stake_increase_after_loss` | ср. рост ставки после серии минусов | Rk |
| 437 | `weekly_deposit_growth` | недельный рост депозитов | Rk |
| 438 | `session_length_growth` | удлинение сессий по времени | Rk |
| 439 | `spend_acceleration` | ускорение трат (2-я произв. депозитов) | Rk |
| 440 | `all_in_frequency` | как часто ставит ~весь баланс | Rk |
| 441 | `time_of_day_spread` | играет и днём и ночью (расфокус) | Rk |
| 442 | `rg_composite_score` | взвешенная сумма 426–441 | Rk |
| 443 | `deposit_to_income_proxy` | депозиты vs типичные для страны | Rk |
| 444 | `cool_off_needed_flag` | комбо-триггер вмешательства | Rk |
| 445 | `chasing_streak_len` | длина текущей серии «догоняющих» депозитов | Rk |

## 14. Фрод / абьюз / мультиаккаунт-прокси `[F]`
(Полноценный мультиаккаунт нужен IP/device — ждём от казино; пока поведенческие прокси.)

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 446 | `rtp_anomaly_score` | personal_rtp сильно >96 при большом обороте | F |
| 447 | `win_rate_zscore` | z-оценка выигрышности vs база | F |
| 448 | `low_play_high_withdraw` | мало ставок, много выводов | F |
| 449 | `deposit_withdraw_churn` | быстрые циклы деп→вывод без игры | F |
| 450 | `bonus_then_withdraw_flag` | бонус → быстрый вывод | F |
| 451 | `min_wager_before_withdraw` | минимальный отыгрыш перед выводом | F |
| 452 | `nodeposit_bonus_farming` | бездеп-бонусы + вывод | F |
| 453 | `payment_method_switching` | частая смена платёжек | F |
| 454 | `distinct_payment_methods` | число разных методов | F |
| 455 | `rejected_withdrawal_burst` | всплеск отказов вывода | F |
| 456 | `same_amount_repeat_txns` | одинаковые суммы подряд (боттинг) | F |
| 457 | `round_amount_ratio` | доля «круглых» сумм | F |
| 458 | `rapid_bet_flag` | ставок/сек выше человеческого | F |
| 459 | `balance_reconstruct_mismatch` | balance_after не сходится с суммами | F |
| 460 | `abnormal_win_concentration` | почти весь выигрыш в 1-2 раундах | F |
| 461 | `new_account_high_stakes` | молодой аккаунт + крупные ставки | F |
| 462 | `deposit_immediately_bet_max` | внёс и сразу max-ставка | F, Rk |
| 463 | `withdrawal_before_wager_done` | попытка вывода до отыгрыша | F |
| 464 | `manual_adjustment_frequency` | частота ручных корректировок | F |
| 465 | `bonus_abuse_composite` | взвешенная 446–464 | F |
| 466 | `same_ftd_amount_cohort` | одинаковый FTD с многими (промо-абьюз) | F |
| 467 | `reg_to_first_withdraw_fast` | быстрый первый вывод от регистрации | F |
| 468 | `net_positive_persistent` | стабильно в плюсе N периодов | F |
| 469 | `phone_country_mismatch` | phone_country ≠ country_iso | F |
| 470 | `currency_country_mismatch` | валюта ≠ ожидаемой для страны | F |
| 471 | `activity_burst_then_silence` | резкий всплеск и тишина | F |
| 472 | `suspicious_score` | итоговый фрод-скор | F |

## 15. Аффилиат / привлечение `[L][R][V]`

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 473 | `affiliate_type` ✅ | тип аффилиата | все (cat) |
| 474 | `affiliate_code` ✅ | код аффилиата | V (cat) |
| 475 | `registration_source` | источник регистрации | L, R (cat) |
| 476 | `has_click_id` | пришёл по трекинг-ссылке | L |
| 477 | `has_traffic_subid` | есть sub_id кампании | L |
| 478 | `traffic_link_code` | код трафик-ссылки | V (cat) |
| 479 | `affiliate_avg_ftd` | ср. FTD когорты аффилиата | L |
| 480 | `affiliate_ltv_prior` | ср. LTV игроков аффилиата (prior) | L |
| 481 | `affiliate_churn_prior` | ср. отток аффилиата | C |
| 482 | `affiliate_quality_tier` | тир качества источника | L, C |
| 483 | `affiliate_player_rank` | место игрока по обороту внутри аффилиата | V |
| 484 | `is_transferred_player` | (если появится) переданный vs прямой | V |
| 485 | `affiliate_deposit_prior` | ср. депозит когорты | L |
| 486 | `cohort_month` | месяц регистрации (когорта) | C, L |
| 487 | `cohort_size` | размер когорты регистрации | V |
| 488 | `same_source_ltv_percentile` | перцентиль игрока в источнике | V |
| 489 | `acquisition_cost_proxy` | комиссия аффилиата на игрока | V |
| 490 | `is_organic` | registration_source = organic/direct | L |

## 16. География / демография `[C][L][V]`

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 491 | `country` ✅ | страна | все (cat) |
| 492 | `phone_country_code` | код страны телефона | F, V |
| 493 | `timezone` | часовой пояс | Re, V |
| 494 | `currency` ✅ | валюта | V (cat) |
| 495 | `country_avg_ltv` | ср. LTV страны (prior) | L |
| 496 | `country_churn_rate` | ср. отток страны | C |
| 497 | `country_player_rank` | место по обороту в стране | V |
| 498 | `is_primary_market` | TR (основной рынок) | все |
| 499 | `country_deposit_tier` | тир страны по среднему депозиту | L, V |
| 500 | `local_hour_offset` | смещение активности vs часового пояса | Re |

## 17. Платёжные методы `[L][F][V]`

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 501 | `primary_payment_method` ✅ | основной метод депозита | L (cat) |
| 502 | `distinct_deposit_methods` | разных методов депозита | F |
| 503 | `payment_method_diversity` | энтропия методов | F |
| 504 | `uses_bank_transfer` | havale/bank | V |
| 505 | `uses_fastpay` | fastpay | V |
| 506 | `uses_crypto` | крипта (если есть) | F, V |
| 507 | `payment_method_ltv_prior` | ср. LTV метода | L |
| 508 | `payment_method_risk_tier` | риск-тир метода | F |
| 509 | `deposit_method_switches` | смен метода депозита | F |
| 510 | `first_deposit_method` | метод FTD | L, R |
| 511 | `withdrawal_method_matches_deposit` | вывод тем же методом? | F |
| 512 | `high_risk_method_ratio` | доля рисковых методов | F |
| 513 | `payment_success_rate` | успешных ÷ всех попыток по методу | F |

## 18. Баланс — динамика `[V][Rk][F]`
Из `balance_before/after` в транзакциях.

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 514 | `balance_now` ✅ | текущий баланс | V |
| 515 | `bonus_balance_now` ✅ | бонус-баланс | B |
| 516 | `avg_balance` | ср. баланс по транзакциям | V |
| 517 | `max_balance_reached` | пиковый баланс | V, F |
| 518 | `balance_volatility` | разброс баланса | Rk |
| 519 | `balance_trend_30d` | тренд баланса | Dc, Re |
| 520 | `time_at_zero_balance_ratio` | доля времени с нулём | Re, Dc |
| 521 | `balance_to_deposit_ratio` | текущий баланс ÷ Σ депозитов | V |
| 522 | `max_drawdown_from_peak` | макс. просадка от пика | Rk |
| 523 | `balance_recovery_count` | восстановлений после нуля (депозит) | Re |
| 524 | `pre_churn_balance` | баланс перед последней паузой | Re |
| 525 | `bonus_to_real_balance_shift` | миграция бонус→реал баланс | B |
| 526 | `avg_balance_before_bet` | типичный банк на ставке | Rk |

## 19. Стрики и поведенческий моментум `[C][F][Re]`

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 527 | `current_loss_streak_sessions` | сессий подряд в минусе | Rk, C |
| 528 | `current_win_streak_sessions` | сессий подряд в плюсе | F |
| 529 | `max_loss_streak` | макс. серия проигрышных сессий | Rk |
| 530 | `max_win_streak` | макс. серия выигрышных | F |
| 531 | `recent_net_14d` | net за 14д (форма) | C, Rk |
| 532 | `on_hot_streak_flag` | недавно крупно выиграл | B, Re |
| 533 | `on_cold_streak_flag` | серия проигрышей (момент для кэшбэка) | B, Rk |
| 534 | `deposit_streak_weeks` | недель подряд с депозитом | L, V |
| 535 | `active_week_streak` | недель подряд активен | C, V |
| 536 | `bounce_back_after_loss` | вернулся после крупного проигрыша | Re |
| 537 | `win_after_deposit_ratio` | выигрывает ли сразу после депозита | F |
| 538 | `momentum_direction` | знак recent_net (плюс/минус) | B, Rk |
| 539 | `volatility_of_results` | разброс посессионного net | Rk |
| 540 | `longest_active_streak_days` | макс. серия активных дней | V, C |
| 541 | `streak_break_recency` | дней с обрыва серии | C, Re |

## 20. Взаимодействия и кросс-фичи `[V][C][L]`
Комбинации, которые ловят нелинейные эффекты.

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 542 | `vip_x_lifecycle` | VIP-уровень × стадия | C, V |
| 543 | `value_x_churn_risk` | ценность × риск оттока (приоритет) | C, V |
| 544 | `tenure_x_recency` | стаж × давность (лояльный уходит?) | C |
| 545 | `deposit_x_freespin_ratio` | депозитор vs бонус-игрок | B, F |
| 546 | `country_x_provider` | локальные предпочтения | B |
| 547 | `avg_bet_x_vip` | чек относительно тира | Rk, V |
| 548 | `net_x_deposit_count` | результат × вовлечённость (winner/whale) | F, V |
| 549 | `session_freq_x_avg_bet` | частота × размер (тип игрока) | V |
| 550 | `momentum_x_value` | затухание ценного игрока | Dc, C |
| 551 | `bonus_reliance_x_net` | бонус-зависимый победитель = абьюз | F |
| 552 | `recency_x_expected_gap` | overdue у ценного | C |
| 553 | `hold_x_turnover` | маржа × объём (реальная ценность) | V |
| 554 | `affiliate_x_country` | качество источника по гео | L |
| 555 | `first_day_intensity_x_ftd` | вовлечённость × первый депозит | R, L |
| 556 | `deposit_regularity_x_amount` | регулярный крупный депозитор | L, V |
| 557 | `night_share_x_loss_chasing` | ночная погоня за отыгрышем | Rk |
| 558 | `game_concentration_x_tenure` | «залип» надолго | Dc |
| 559 | `withdrawal_ratio_x_bonus` | абьюз-профиль | F |
| 560 | `provider_diversity_x_recency` | исследователь затухает | Dc |
| 561 | `is_depositor_x_active` | активный депозитор (ядро) | V |
| 562 | `weekend_x_deposit` | депозитит по выходным | V |
| 563 | `vip_x_declining` | ценный сползает — срочно | Dc, C |
| 564 | `high_roller_x_cold_streak` | кит на холодной серии (риск ухода) | C, Rk |
| 565 | `new_x_high_intensity` | новичок с высокой вовлечённостью | R, L |
| 566 | `payment_x_country_risk` | рисковый метод + рисковое гео | F |

## 21. Нормализованные отношения (per-unit) `[V][C]`
Нормировка сырых сумм — устойчивее к масштабу игрока.

| # | Фича | Смысл | Модели |
|---|---|---|---|
| 567 | `bets_per_active_day` ✅ | ставок на активный день | C, Dc |
| 568 | `turnover_per_active_day` | оборот на активный день | Dc, V |
| 569 | `net_per_active_day` | результат на активный день | F |
| 570 | `deposits_per_week` | депозитов в неделю | L, D |
| 571 | `turnover_per_session` | оборот на сессию | V |
| 572 | `wins_per_bet` | выигрышей на ставку | F |
| 573 | `bonus_per_active_day` | бонусов на активный день | B |
| 574 | `withdrawal_per_deposit` | вывод на депозит | F |
| 575 | `turnover_per_tenure_day` | интенсивность за всю жизнь | V |
| 576 | `sessions_per_week` | сессий в неделю | C |
| 577 | `distinct_games_per_active_day` | разнообразие в день | Dc |
| 578 | `ggr_per_bet` | маржа на ставку | V |
| 579 | `deposit_per_login` | конверсия логина в депозит | L |
| 580 | `bets_per_deposit` | сколько ставок «отрабатывает» депозит | V |
| 581 | `active_days_per_week` | плотность активности | C, Dc |
| 582 | `avg_bet_to_balance_ratio` | доля банка в ставке | Rk |
| 583 | `revenue_per_bonus` | GGR на выданный бонус | B |
| 584 | `spins_per_tl` | ставок на 1 TRY депозита | V |

---

## Итог: >584 фич

| Семейство | Фич | Основные модели |
|---|---|---|
| 1. Оконные агрегаты | 90 | C, L, Dc, Re |
| 2. Моментум/тренд | 48 | C, Dc, Re |
| 3. Распределение ставки | 24 | Rk, F, V |
| 4. Депозиты | 36 | L, R, D |
| 5. Выводы | 25 | F, Rk |
| 6. Финансовые отношения | 21 | V, L, F |
| 7. Бонусы | 26 | B, F |
| 8. Сессии | 30 | C, Dc, Rk |
| 9. Время/день недели | 34 | Rk, V, Re |
| 10. Игры/провайдеры | 40 | B, Dc, V |
| 11. Провайдерные срезы | 28 | B, V, F |
| 12. Жизненный цикл | 23 | C, Re, V |
| 13. Риск/RG | 20 | Rk |
| 14. Фрод/абьюз | 27 | F |
| 15. Аффилиат | 18 | L, R, V |
| 16. География | 10 | C, L, V |
| 17. Платёжные методы | 13 | L, F, V |
| 18. Баланс | 13 | V, Rk, F |
| 19. Стрики | 15 | C, F, Re |
| 20. Кросс-фичи | 25 | V, C, L |
| 21. Нормализованные | 18 | V, C |

## Новые модели, которые открывают эти фичи
- **`decline` (затухание ценности)** — таргет «оборот/ценность упадёт на N% за 30д». Кормится семействами 1,2,8,9,18,19. Ловит спад ДО оттока (то, что просил эксперт).
- **`reactivation` (реактивация)** — таргет «спящий вернётся за 14д». Семейства 12,19, время захода.
- **`fraud/abuse`** — таргет «бонус-абьюз/мультиаккаунт» (полноценно — после IP/device от казино). Семейства 5,7,14,17.
- **`risk/RG`** — рейтинг проблемной игры. Семейство 13.
- **`value/whale`** — сегментация по РЕАЛЬНОЙ ценности (net_cash×hold, не по депозитам). Семейства 6,20.

## Правила внедрения (важно)
1. **Каждую фичу мерить** — не всякая поднимает AUC (проверено на churn: momentum среднего чека дал 0 важности, т.к. recency доминирует). Добавляем пачками, смотрим feature_importance + AUC на out-of-time тесте.
2. **Защита от утечки** — все окна считать на `created_at < T`; ничего из будущего (пример: repeat-модель берёт только день 0).
3. **NaN — это сигнал** для CatBoost (нет ставок в окне ≠ 0); но для отображения/формул гасить в 0 (урок с avg_bet=NaN).
4. **Мёртвые колонки не трогать** (device/duration/fees/RG-флаги — пусты).
5. Многие «prior»-фичи (affiliate_ltv_prior, country_churn_rate) считать **только на train-периоде** во избежание target leakage.
