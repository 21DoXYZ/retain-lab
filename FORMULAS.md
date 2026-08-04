# 📐 FORMULAS — все формулы расчётов retention-системы

Справочник всех вычислений: где считается, как считается. Источники: `player_features.sql`,
`marts.sql` (вьюхи), `*_model.py` (модели), `player_board.py` (KPI/борд).

Условные обозначения (**спека казино**): период по `created_at`/`ts`. **Успешные операции** =
`status IN ('completed','approved','success')` (v2 = completed; legacy approved/success тоже успех).
Игровые (`game_transactions`): только `status='completed'` — pending/rejected/failed НЕ в итоги.
`bet` = ставка (`transaction_type IN ('bet','freespins_bet')`), `win` = выигрыш (`'win','freespins_win'`),
`dep` = кэш-депозит (`type='deposit'`, успешный — **manual_deposit не входит**, это бонус),
`dmax` = последняя дата в данных, все расчёты по `account_type='normal'`.

> **Депозиты/выводы НЕ входят в GGR.** GGR — только по игровым ставкам и выигрышам.
> Ставки provider (engr/infra/rev) и affiliate commission_rate — из **справочников** (не транзакции):
> таблицы `provider_rates` (по студиям) и `affiliate_rates` (по affiliate_code), заливаются
> `load_reference_rates.py`. На источнике: `site_settings.ggr_provider_rates_json` + `affiliates.commission_rate`.

---

## 1. Базовые агрегаты игрока (`player_features.sql`)

| Метрика | Формула | Смысл |
|---|---|---|
| `turnover` (оборот) | `Σ bet_amount` по ставкам | сколько поставил |
| `wins_sum` | `Σ win_amount` по выигрышам | сколько выиграл в игре |
| `net` | `wins_sum − turnover` | + игрок в плюсе / − слил (со стороны игрока) |
| `avg_bet` | `avg(bet_amount)` по ставкам | средняя ставка |
| `active_days` | `uniqExact(toDate(created_at))` | дней с игрой |
| `recency_days` | `dateDiff('day', last_bet, today())` | дней с последней ставки |
| `freespin_ratio` | `freespins_bets / bets` | доля фриспин-ставок |
| `night_share` | `night_bets / bets` (час < 6 по Стамбулу) | доля ночной игры |
| `bets_per_active_day` | `bets / active_days` | интенсивность |
| `activation_lag_days` | `dateDiff('day', reg_date, first_bet)` | скорость активации |
| `lifecycle` | по `recency`: ≤7 `active` · ≤30 `cooling` · ≤60 `at_risk` · ≤90 `dormant` · >90 `churned` · нет ставок `never` | стадия |
| `churned_30d / 90d` | `recency > 30 / 90 → 1` | метка оттока |
| `is_depositor` (борд/движок) | `dep_count > 0` | реальный депозитор |

---

## 2. Экономика / денежные KPI — **спека казино** (`/overview`, `/report`, `/affiliates`)

Игровые метрики (только `status='completed'`):
| Метрика | Формула |
|---|---|
| **Bet** | `Σ bet_amount` по ставкам |
| **Win** | `Σ win_amount` по выигрышам |
| **GGR** | `Bet − Win` |
| **RTP** | `Win / Bet × 100%` |
| **Rounds** | кол-во игровых транзакций/раундов |
| **Active players** | `COUNT DISTINCT casino_player_id` |
| **Avg bet** | `Bet / Rounds` |

Cash / payment net:
| Метрика | Формула |
|---|---|
| **Deposits** | `Σ amount` по успешным `deposit` (manual_deposit НЕ входит) |
| **Withdrawals** | `Σ ABS(amount)` по успешным `withdrawal` |
| **Net** | `Deposits − Withdrawals` |
| **Margin** | `Net / Deposits × 100%` |

Бонусы:
| Метрика | Формула |
|---|---|
| **Bonus cost** | `Σ ABS(amount)` по `bonus/manual_bonus/freespin` (успешные) |
| **Bonus usage** | `Σ bet_amount` где `balance_source='bonus'` |
| **Bonus ratio** | `Bonus cost / GGR × 100%` |

Provider cost — **по каждой студии** (`provider_rates`), студия резолвится из `game_uuid` через `dict_game_names`:
| Метрика | Формула |
|---|---|
| GGR студии | `Bet_студии − Win_студии` |
| **Provider cost** | `Σ по студиям max(GGR_студии, 0) × (engr% + infra% + rev%)` |

> `fixed_fee` / `minimum_guarantee` — settlement-поля, в NGR-сводку не входят (по README казино).
> Без наполненного `dict_game_names` (студия по игре) провайдер не резолвится → Provider cost = 0.

Affiliate commission — **по каждому аффилиату** (`affiliate_rates`, джойн по `affiliate_code`):
| Метрика | Формула |
|---|---|
| **Affiliate net** | `Deposits − Withdrawals` игроков аффилиата (успешные) |
| **Affiliate commission** | `Σ по аффилиатам max(net, 0) × commission_rate%` |

**NGR** = `GGR − Bonus cost − Provider cost − Affiliate commission`.

Player net: `Player net result = Win − Bet`; `Player loss / casino result = Bet − Win`.

> Единый источник правды в коде: `player_board.py` → константы `SUCCESS/GSUCCESS/DEP_OK/WD_OK/BONUS_OK/BET_T/WIN_T`
> и хелперы `provider_cost_total() / affiliate_commission_total() / aff_commission_row() / calc_ngr()`.
> Ставки — из справочников `provider_rates` / `affiliate_rates` (`load_reference_rates.py`).

---

## 3. LTV (ценность игрока)

**Реализованная LTV-кривая** (`ltv_curve`): для горизонта H
`avg( Σ dep.amount где 0 ≤ (dep.date − FTD) ≤ H )`, усреднение **только по дозревшим**
(`dateDiff(FTD, dmax) ≥ H`), чтобы незрелые когорты не занижали.

**LTV v0 — лукап по тиру** (`ltv_tier_model`): тир по депозиту первой недели
(`dep_d7`: A<1k · B<3k · C<10k · D≥10k) → `avg(D30/D90/D120)` дозревших в тире.

**LTV ML** (`ltv_model.py`, ********-регрессор):
- **Таргет:** `Σ dep.amount` в `[0, 90]` дней от FTD; обучение на `log1p(target)`, прогноз `expm1`.
- **Фичи (только 1-я неделя, без утечки):** `dep_d1, dep_d7, ndep_d7, ftd_amount, activation_lag`, игра 0–7 дн (`bets, turnover, avg_bet, distinct_games, active_days, freespin, night`), провайдер/страна/аффилиат/платёжка.

**Квантильный LTV** (`ltv_quantiles.py`): три ******** с `loss = Quantile(α=0.1/0.5/0.9)` → P10/P50/P90 (диапазон, честно про разброс китов).

**Headroom** («ещё ожидаем»): `greatest( pred_ltv_d90 − dep_to_date, 0 )`.

---

## 4. Депозиты: лестница и прогрессия

| Расчёт | Формула | Где |
|---|---|---|
| Лестница: дошли до #N | `count( n_deposits ≥ N )` | `deposit_ladder` |
| Конверсия шага #N→#N+1 | `count(n≥N+1) / count(n≥N) × 100%` | `deposit_ladder` |
| P(2-й деп) эмпирика | по тиру FTD-суммы: `avg( n_deposits ≥ 2 )` | `repeat_deposit_model` |
| **P(2-й деп) ML (30д)** | таргет = `≥2 деп в 30 дн от FTD`; фичи **только FTD-дня** (без утечки); ********-классификатор | `repeat_model.py` → `player_repeat_ml` |
| **P(следующий деп)** | 1 строка = (игрок, депозит #k); таргет = `депозит #k+1 в 30 дн`; фичи на момент #k (номер, сумма, ритм, давность); ******** | `deposit_ladder_model.py` → `player_next_deposit_ml` |

---

## 5. Риск ухода (churn, point-in-time) — `churn_model.py`

| Элемент | Формула |
|---|---|
| **Срез** | дата `T` (несколько месячных), горизонт `H = 30` |
| **Население** | играл в последние 30 дн **до** T И `active_days ≥ 2` |
| **Таргет (ушёл)** | `НЕ было ставки в (T, T+30]` |
| **Фичи «как было на T»** | всё строго `created_at < T`: recency-на-T, tenure, обороты/ставки, окна `last7/prev7/last30`, моментум `bets_last7/bets_prev7`, личный ритм `expected_gap = span/(active_days−1)`, просрочка `recency/expected_gap`, депозиты-на-T, провайдер/страна/аффилиат |
| **Валидация** | по времени: ранние T → train, поздний T → test (без утечки) |

---

## 6. Движок офферов (`player_actions`)

| Расчёт | Формула |
|---|---|
| **value_try** (ценность) | `is_depositor ? max(pred_ltv_d90, dep_sum) : 0` |
| **save_weight** (вес стадии) | active `0.30` · cooling `0.70` · at_risk `1.00` · dormant `0.55` · churned `0.35` |
| **priority** (приоритет) | `round( value_try × coalesce(p_churn, save_weight) )` — реальный риск ухода, иначе вес стадии |
| **p_2nd_deposit** | `is_depositor ? p_2nd_ml : NULL` |
| **action** | CONVERT (нет деп, играл) · NUDGE (1 деп, recency≤30) · SAVE (cooling/at_risk) · WINBACK (dormant/churned) · NURTURE (active) |
| **bonus** | нет деп → перв.деп · freespin_ratio>0.4 → фриспины · тир C/D или avg_bet≥200 → VIP-кэшбэк · ≤1 деп → релоад · иначе кэшбэк |

> Приоритизация = **ценность × вероятность ухода**: спасаем ценных, кто реально уходит, а не всех подряд.

---

## 7. Сессии (реконструкция из транзакций)

Родного поля длительности нет — считаем из `game_transactions` по `session_id`:

| Метрика | Формула |
|---|---|
| Длительность | `round( dateDiff('second', min(created_at), max(created_at)) / 60 )` мин |
| Спинов | `count` ставок в сессии |
| Net сессии | `Σ win − Σ bet` |
| Итог | `net ≥ 0` → 🟢 выиграл, иначе 🔴 проиграл |
| Моментум (карточка/desk) | `recent_net = Σ net за окно (7/14/30/90/всё)` |
| Live: текущая сессия | `argMax(net, последняя_ставка)` — последняя сессия игрока |
| Авто-алерт | `pred_ltv_d90 ≥ 10000 AND net_текущей_сессии < 0` (ценный сливает сейчас) |

---

## 8. Распределения (`/dist`)

| Расчёт | Формула |
|---|---|
| Дециль LTV | `11 − ntile(10) OVER (ORDER BY pred_ltv_d90)` (D1 = топ-10%) |
| Доля ценности децили | `Σ pred_ltv_d90 (дециль) / Σ pred_ltv_d90 (все) × 100%` |
| Перцентиль депозитов | `quantile(p)(dep_sum)` для p = 0.1/0.25/0.5/0.75/0.9/0.95/0.99 |
| Дециль риска | `ntile(10) OVER (ORDER BY p_churn)` |

---

## 9. Бонусы: эффективность и uplift

**Эффективность по типу** (`bonus_effectiveness`): тип бонуса определяется по `type`+`description`
(freespins / deposit-match `%DSC/yat` / cashback `Kayıp` / no-deposit `Deneme`).

| Метрика | Формула |
|---|---|
| Отклик депозитом | `% бонус-событий, где был dep в (бонус, бонус+14д]` |
| Retention 30д | `% где была ставка в (бонус, бонус+30д]` |

**Uplift (квазиэксперимент)** (`bonus_model.py`):
- **Propensity** `e(x) = P(получил бонус | профиль)` — логистическая регрессия на (ftd_amount, lag, played, avg_bet, tenure).
- **Matching:** каждому control — ближайший treated по `|e(x)|` (nearest-neighbour).
- **ATT** = `mean( retained_treated − retained_control )` по парам; исход = «активен 30 дн».
- **CI** — бутстрэп (2000 ресемплов, перцентили 2.5/97.5).
- ⚠️ наблюдательная оценка (не RCT): контроль тонкий → directional.

---

## 10. RFM (классическая сегментация, `COHORTS.md`)

| Ось | Формула |
|---|---|
| **R** (recency) | `6 − ntile(5) OVER (ORDER BY recency)` (меньше дней = выше балл) |
| **F** (frequency) | `ntile(5) OVER (ORDER BY active_days)` |
| **M** (monetary) | `ntile(5) OVER (ORDER BY turnover)` |
| Сегмент | по (R,F,M): Champions / Loyal / At-Risk / Cant-Lose / Hibernating … |

---

> **Заметки о корректности** (из валидации): модели калиброваны на **ранжирование**, не на абсолютную
> вероятность — использовать для приоритизации. Поля от `today()` (recency/lifecycle) в витрине
> замораживаются на дату сборки `player_features` — освежать пересборкой витрины.
