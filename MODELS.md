# Модели и их интеграция на VPS

> 6 CatBoost-моделей ретеншн-CRM: что предсказывают, где сохраняются, как наполняют
> ClickHouse и как развернуть на сервере. Дизайн моделей (таргеты, почему CatBoost) — в
> [ML_PLAN.md](ML_PLAN.md); системная картина — в [ARCHITECTURE.md](ARCHITECTURE.md).
> **Какие поля ест каждая модель, откуда брать и как запустить на VPS → [MODEL_DATA.md](MODEL_DATA.md).**

---

## 1. Реестр моделей (как они сохраняются)

Раньше модель обучалась и **выбрасывалась** — оставались только строки предсказаний в ClickHouse.
Теперь каждый `*_model.py` сохраняет обученную модель в файл через [model_registry.py](model_registry.py):

```
models/
  <name>/
    model.cbm        # бинарь CatBoost (у квантилей — p10.cbm / p50.cbm / p90.cbm)
    meta.json        # дата обучения, метрики, фичи, cat-фичи, целевая таблица
```

- **`meta.json` и `*.cbm`** коммитятся в git — на VPS модели приезжают обычным `git pull`.
  (`.cbm` — сериализованные деревья: фичи/пороги/листья, без сырых PII-строк.)
  `transfer_models.sh` остаётся для переноса без git (rsync).
- **Режим `SCORE_ONLY=1`** — скрипт НЕ обучается, а грузит сохранённую `.cbm` и только скорит
  (наполняет ML-таблицу). Быстро, детерминированно, без тяжёлого обучения.

```bash
./train_all.sh                 # обучить все 6 (+ сохранить .cbm + наполнить таблицы)
SCORE_ONLY=1 ./train_all.sh    # НЕ обучать: загрузить .cbm и только переписать предсказания
PYTHON=.venv/bin/python ./train_all.sh   # явный интерпретатор (по умолчанию .venv/bin/python)
```

---

## 2. Две схемы интеграции на VPS — выбери одну

### Pattern B — скорим локально, на VPS льём только таблицы  ✅ рекомендуется
Модели и скоринг живут локально (нам тут быстрее). На VPS уезжают лишь таблицы предсказаний.
**catboost/sklearn на сервере НЕ нужны.**

```
локально:  ./train_all.sh                         # обучить + наполнить ML-таблицы локально
перенос:   ./dump_ml_tables.sh && scp -r ml_dump/ user@vps:/path/  (на VPS) ./restore_ml_tables.sh
           # либо прямой ClickHouse→ClickHouse через remote() (как делали с переносом базы)
```
Дашборд на VPS читает таблицы — прогнозы на месте. Это согласуется с «работаем локально».

### Pattern A — скорим на VPS из сохранённой модели
Нужен **catboost на VPS** + перенос моделей. Полезно, если хочешь обновлять предсказания
прямо на сервере без обращения к локальной машине.

```
локально:  ./train_all.sh                          # получить models/*.cbm
перенос:   ./transfer_models.sh user@vps:/path/retention-board
на VPS:    pip install -r requirements-ml.txt
           SCORE_ONLY=1 CH_HOST=127.0.0.1 ./train_all.sh   # грузит .cbm, скорит из VPS-данных
```
Скоринг читает фичи из VPS-ClickHouse (raw + `player_features` — уже перенесены).

---

## 3. Модели (6) — карта интеграции

| # | Модель | Скрипт | Артефакт | Таблица (выход) | Предсказывает → действие |
|---|---|---|---|---|---|
| 1 | **LTV** | `ltv_model.py` | `models/ltv/model.cbm` | `player_ltv_ml(casino_player_id, pred_ltv_d90_ml)` | депозит на D90 → ранжирование по ценности, VIP |
| 2 | **LTV-квантили** | `ltv_quantiles.py` | `models/ltv_quantiles/{p10,p50,p90}.cbm` | `player_ltv_quantiles(casino_player_id, ltv_p10, ltv_p50, ltv_p90)` | диапазон ценности (риск-полоса) → «медиана X, верх до Y» |
| 3 | **Repeat (2-й деп)** | `repeat_model.py` | `models/repeat/model.cbm` | `player_repeat_ml(casino_player_id, p_2nd_ml)` | P(2-й депозит в 30д) → нудж близким к конверсии |
| 4 | **Churn** | `churn_model.py` | `models/churn/model.cbm` | `player_churn_ml(casino_player_id, p_churn)` | P(уйдёт в 30д) → удержать (⚠ слабый сигнал, см. ML_PLAN) |
| 5 | **Deposit-ladder** | `deposit_ladder_model.py` | `models/deposit_ladder/model.cbm` | `player_next_deposit_ml(casino_player_id, deposit_number, p_next_deposit)` | P(следующий депозит в 30д) на текущей ступени → нудж на депозит |
| 6 | **Bonus** | `bonus_model.py` | `models/bonus/model.cbm` | `player_bonus_ml(casino_player_id, rec_bonus, rec_response)` + `bonus_uplift(metric, value)` | лучший тип бонуса + uplift-сводка → next-best-action |

**Зависимости скоринга (что должно быть в ClickHouse на VPS):** raw-таблицы (`users`,
`money_transactions`, `game_transactions`) и витрина `player_features` (её читает `bonus_model`).
Всё это уже перенесено (см. перенос базы). Метрики качества каждой модели — в её `models/<name>/meta.json`.

### Детали по моделям

**1. LTV** — обучение на депозиторах с FTD ≥90 дней (таргет наблюдаем), фичи первой недели,
лог-таргет (киты), валидация по времени. Скоринг — все депозиторы.
`python ltv_model.py` · score-only: `SCORE_ONLY=1 python ltv_model.py`.

**2. LTV-квантили** — три регрессора (Quantile α=0.1/0.5/0.9) на тех же фичах; монотонность
p10≤p50≤p90 чинится после предсказания. Сохраняются три артефакта.

**3. Repeat** — классификатор P(2-й депозит) по поведению ПЕРВОГО дня (защита от утечки: депозит-окна не берём).

**4. Churn** — point-in-time срезы T (несколько месячных), население «активен 30д + ≥2 дней»,
метка «не играл (T,T+30]». ⚠ Уходят ~92% — сигнал слабый; в ML_PLAN предложено переформулировать в at-risk(H=14).

**5. Deposit-ladder** — 1 строка = (игрок, депозит #k), фичи «как было на #k», таргет «#(k+1) в 30д».
Сплит по игрокам. Скоринг — последний депозит каждого.

**6. Bonus** — S-learner: состояние игрока + тип бонуса → P(retention-30). Перебор типов бонуса →
рекомендуем лучший. Плюс квазиэксперимент uplift (propensity-matching) → `bonus_uplift`.
⚠ Контроль тонкий → оценка наблюдательная, не RCT. `bonus_uplift` пересчитывается всегда (не модель).

---

## 4. Обновление (refresh) и расписание

| Что обновилось | Действие |
|---|---|
| дозалили данные, модели НЕ меняем | `SCORE_ONLY=1 ./train_all.sh` → свежие предсказания на текущей модели |
| хотим переобучить на свежих данных | `./train_all.sh` (заодно перезапишет `.cbm` + `meta.json`) |
| обновить VPS | Pattern B: перелить таблицы предсказаний · Pattern A: `transfer_models.sh` + `SCORE_ONLY=1` на VPS |

**Cron-разделение (ARCHITECTURE.md ML-1):** обучение редко (раз в неделю, `train_all.sh`),
скоринг часто (ночью, `SCORE_ONLY=1 ./train_all.sh`). По мере роста данных править даты срезов в `churn_model.py`.
