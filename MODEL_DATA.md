# Справка: данные для моделей и запуск на VPS

> Что каждая модель ест (поля), откуда это берётся, как собрать и как запустить на сервере.
> Дополняет [MODELS.md](MODELS.md) (интеграция/реестр) и [SETUP.md](SETUP.md) (деплой).
> Все модели считают **только `account_type='normal'`** (реальные игроки), ключ — `casino_player_id`.

---

## 0. TL;DR — запуск на VPS (данные уже в ClickHouse)

```bash
cd retention-board && git pull            # подтянуть код + модели (.cbm в git)
python3 -m venv .venv
.venv/bin/pip install -r requirements-ml.txt   # catboost, sklearn, pandas, numpy, scipy

# вариант A — только заскорить готовыми моделями (быстро, без обучения):
SCORE_ONLY=1 CH_HOST=127.0.0.1 CH_PORT=8123 ./train_all.sh

# вариант B — переобучить на свежих данных (перезапишет .cbm + таблицы):
CH_HOST=127.0.0.1 CH_PORT=8123 ./train_all.sh
```
Конфиг ClickHouse — через env: `CH_HOST CH_PORT CH_USER CH_PASSWORD CH_DB` (дефолт `127.0.0.1:8123`, user `default`, db `retention`).

---

## 1. Поток данных (откуда что берётся)

```
4 сырые таблицы ──► player_features.sql ──► marts.sql ──► модели (*_model.py)
(users,            (1 строка = игрок,      (вьюхи +        читают сырьё + player_features,
 money_transactions, ~66 фич)              ML-таблицы      пишут предсказания в player_*_ml)
 game_transactions,                        пустые)
 game_sessions)
```

Модели читают **сырые таблицы напрямую** (считают свои фичи на лету) + витрину `player_features`
(только bonus-модель для скоринга). `game_sessions` моделям напрямую НЕ нужна (идёт в дашборд/витрину).

---

## 2. Сырые поля, которые ОБЯЗАТЕЛЬНЫ (что собрать из источника)

Если данные приходят из внешней системы (см. [ARCHITECTURE.md](ARCHITECTURE.md) §2) — эти колонки
должны быть в контракте. Схема — в [schema.sql](schema.sql).

### `users` (1 строка = игрок)
| Поле | Тип | Зачем |
|---|---|---|
| `casino_player_id` | UInt32 | ключ везде |
| `account_type` | String | фильтр `='normal'` (реальные игроки) |
| `ftd_date` | Date/DateTime | старт окна для LTV/repeat (первый депозит) |
| `ftd_amount` | Float | фича во всех «депозитных» моделях |
| `reg_date` | Date/DateTime | лаг reg→FTD, days_since_reg |
| `affiliate_account_type` | String | cat-фича `affiliate_type` |
| `country_iso_estimated` | String | cat-фича `country` |

### `money_transactions` (депозиты/выводы/бонусы)
| Поле | Тип | Зачем |
|---|---|---|
| `casino_player_id` | UInt32 | ключ |
| `created_at` | DateTime | окна/гэпы/последовательности депозитов |
| `type` | String | `deposit`/`manual_deposit`/`freespin`/`manual_bonus`/`bonus` |
| `status` | String | фильтр `='completed'` |
| `amount` | Float | суммы депозитов, ладдер |
| `payment_method` | String | cat-фича (теги `campaign:%` отфильтровываются) |
| `description` | String | тип бонуса (bonus-модель парсит ILIKE-паттерны) |

### `game_transactions` (каждая ставка/выигрыш — 54M строк)
| Поле | Тип | Зачем |
|---|---|---|
| `casino_player_id` | UInt32 | ключ |
| `created_at` | DateTime (UTC) | recency, ритм, окна d0/d7, ночная доля |
| `transaction_type` | String | `bet`/`freespins_bet`/`win`/`freespins_win` |
| `bet_amount` | Float | turnover, avg_bet |
| `win_amount` | Float | net (win−bet) — repeat-модель |
| `game_uuid` | String | distinct_games |
| `aggregator` | String | cat-фича `provider` (имена игр НЕТ, только провайдер) |

> Время в `game_transactions` — UTC; «ночь» и суточные срезы считаются в `Europe/Istanbul` (+3).

---

## 3. Модели — что ест и что отдаёт

| Модель | Скрипт | Население (train) | Таргет | Выход |
|---|---|---|---|---|
| **LTV** | `ltv_model.py` | депозиторы, FTD ≥90д назад | депозит за 90д от FTD (log1p) | `player_ltv_ml(casino_player_id, pred_ltv_d90_ml)` |
| **LTV-квантили** | `ltv_quantiles.py` | то же | те же квантили α=.1/.5/.9 | `player_ltv_quantiles(…, ltv_p10, ltv_p50, ltv_p90)` |
| **Repeat** | `repeat_model.py` | депозиторы, FTD ≥30д назад | ≥2 депозита в 30д от FTD | `player_repeat_ml(…, p_2nd_ml)` |
| **Churn** | `churn_model.py` | активны 30д + ≥2 дней на T | не играл в (T, T+30] | `player_churn_ml(…, p_churn)` |
| **Deposit-ladder** | `deposit_ladder_model.py` | (игрок × депозит #k) | депозит #(k+1) в 30д | `player_next_deposit_ml(…, deposit_number, p_next_deposit)` |
| **Bonus** | `bonus_model.py` | первый бонус игрока, mat ≥30д | играл в 30д после бонуса | `player_bonus_ml(…, rec_bonus, rec_response)` + `bonus_uplift(metric, value)` |

### Фичи по моделям (NUM + CAT)

**LTV / LTV-квантили** (16): `ftd_amount, act_lag_days, dep_d1, dep_d7, ndep_d7, bets_d7, turnover_d7, avg_bet_d7, distinct_games_d7, active_days_d7, freespin_d7, night_d7` + cat `provider_d7, payment_method, affiliate_type, country`. *(поведение и депозиты ПЕРВОЙ НЕДЕЛИ от FTD)*

**Repeat** (13): `ftd_amount, act_lag_days, bets_d0, turnover_d0, avg_bet_d0, distinct_games_d0, freespin_d0, net_d0, night_d0` + cat `provider_d0, payment_method, affiliate_type, country`. *(только ПЕРВЫЙ ДЕНЬ — без утечки депозитов)*

**Churn** (22): `recency_at_T, tenure_at_T, bets_to_T, turnover_to_T, active_days_to_T, avg_bet, freespin_ratio, night_share, bets_last7, bets_prev7, bets_last30, momentum_7v7, expected_gap, overdue_ratio, is_depositor, dep_count, dep_sum, deposit_recency_at_T` + cat `provider, country, affiliate_type, payment_method`. *(всё «как было на дату среза T»)*

**Deposit-ladder** (12): `deposit_number, days_since_reg, gap_before, total_to_k, avg_to_k, max_to_k, ftd_amount, this_amount, mean_gap` + cat `payment_method, affiliate_type, country`. *(состояние на момент депозита #k)*

**Bonus** (15): `recency_days, tenure_days, bets, turnover, active_days, avg_bet, freespin_ratio, night_share, dep_count, dep_sum, deposit_recency` + cat `provider, country, affiliate_type, bonus_type`. *(состояние ДО первого бонуса; bonus_type — из `description`)*

> Точный SQL фич — внутри каждого скрипта (константа `FEATURE_SQL`/`SNAP`/`PULL`/`TRAIN_SQL`).
> Сохранённый список фич каждой модели — в `models/<name>/meta.json` (`features`, `cat_features`).

---

## 4. Как собрать данные (если на VPS их ещё нет)

```bash
# 1. схема (4 сырые таблицы)
clickhouse client --multiquery < schema.sql
# 2. залить данные (перенос с локали / Parquet / прямой pull — см. SETUP.md §4, ARCHITECTURE.md §2)
# 3. витрина игроков
clickhouse client --multiquery < player_features.sql      # ~39130 строк
# 4. аналитический слой (вьюхи + ПУСТЫЕ ML-таблицы + player_games/bonus_effectiveness_t)
clickhouse client --multiquery < marts.sql
```
Проверки: `player_features` ~39130 строк; объектов в `retention` ~25.
*(Сейчас на VPS всё это уже есть — база перенесена целиком.)*

---

## 5. Запуск моделей на VPS (детально)

**Предусловие:** выполнены §4 (raw + `player_features` + `marts.sql`), стоит `requirements-ml.txt`.

```bash
# обучить все 6 по порядку (~1–2 мин на этих объёмах), сохранить .cbm, наполнить таблицы:
CH_HOST=127.0.0.1 CH_PORT=8123 ./train_all.sh

# ИЛИ только скоринг готовыми моделями из git (без обучения):
SCORE_ONLY=1 CH_HOST=127.0.0.1 CH_PORT=8123 ./train_all.sh

# по одной модели:
.venv/bin/python ltv_model.py
SCORE_ONLY=1 .venv/bin/python churn_model.py
```

**Проверка, что наполнилось:**
```bash
clickhouse client -q "SELECT
  (SELECT count() FROM retention.player_ltv_ml)            AS ltv,
  (SELECT count() FROM retention.player_ltv_quantiles)     AS quant,
  (SELECT count() FROM retention.player_repeat_ml)         AS repeat,
  (SELECT count() FROM retention.player_churn_ml)          AS churn,
  (SELECT count() FROM retention.player_next_deposit_ml)   AS next_dep,
  (SELECT count() FROM retention.player_bonus_ml)          AS bonus"
```
Ненулевые счётчики → дашборд показывает прогнозы.

---

## 6. Гочи (обязательно знать)

- **Пароль ClickHouse:** если `default` с паролем — задай `CH_PASSWORD=...` в env (иначе коннект упадёт).
- **Churn — фиксированные даты срезов** (`T_TRAIN`/`T_TEST` в `churn_model.py`): привязаны к периоду данных
  (дек'25→июн'26). По мере роста данных их надо двигать вперёд, иначе модель учится на старом.
- **Горизонты:** churn/repeat/deposit-ladder = 30 дней; bonus retention = 30 дней. Зашиты в скриптах.
- **`payment_method`:** теги `campaign:%` отфильтровываются (это не платёжка, а метка кампании).
- **bonus_type** парсится из `money_transactions.description` (ILIKE на `deneme`/`kay*p`/`dsc`/`yat`);
  cashback исключён (n=10, мало для модели).
- **`game_transactions.created_at` — UTC;** суточные/ночные срезы переводятся в `Europe/Istanbul`.
- **SCORE_ONLY требует наличия `models/<name>/*.cbm`** (приходят с `git pull` или `transfer_models.sh`).
  Если их нет — будет ошибка «Нет сохранённой модели», тогда сначала обучи без `SCORE_ONLY`.
- **Расписание:** обучение редко (раз в неделю), скоринг часто (ночью `SCORE_ONLY=1`) — см. [MODELS.md](MODELS.md) §4.
