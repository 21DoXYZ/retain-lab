# Конструктор отчётов («замена аналитика») — план MVP

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Родительский план: `docs/plans/2026-07-17-modules-etap3-plan.md` (Global Constraints действуют целиком). Статус по ТЗ — «в разработку пока не берём»; этот план готов к запуску по команде владельца. Независим от Волны 4 (этап 3), зависит только от W3-T1 (снапшот `player_state_daily`).

**Goal:** Руководитель сам собирает сводный отчёт (метрики × 2–3 уровня группировки × фильтры × период), сохраняет его, делится по ролям, выгружает в CSV/XLSX — с исторически корректными сегментами с первого дня.

**Architecture:** Реестр метрик/разрезов (`api/report_fields.py`) + компилятор в один ClickHouse GROUP BY-запрос (`api/report_builder.py`) — по образцу компилятора сегментов. Сохранённые отчёты — Postgres `automation.saved_reports` (RLS-паттерн 0013). Историческая корректность — через `retention.player_state_daily` (снапшот W3-T1) + бэкфилл прошлого из raw-фактов (vip_level и lifecycle — детерминированные функции истории, восстановимы задним числом). LLM-прослойка «текст → черновик отчёта» — фаза 2, через OpenRouter (уже используется анализатором звонков).

**Tech Stack:** как в родительском плане; экспорт — openpyxl (реюз паттерна `/players.xlsx`).

## MVP-скоуп (из ТЗ, дословно)
1. Сводная таблица: метрики + 2–3 уровня группировки + фильтры + период. ✚ изменяемый ПОРЯДОК разрезов (выбрал бренд→день недели или трафик→месяц — таблица перестраивается).
2. Сохранение/шаринг: имя, автор, доступ личный / общий / по ролям; «официальные» отчёты vs черновики (рекомендация Василия: один канонический на компанию).
3. Экспорт CSV/XLSX.
4. Историческая корректность сегментов — С ПЕРВОГО ДНЯ (дифференциатор): «VIP в феврале» = кто БЫЛ VIP в феврале.
5. Текст-ТЗ → черновик отчёта (LLM) — фаза 2.

## Порядок

```
(prereq) W3-T1 player_state_daily  ──→ W5-T1 бэкфилл истории
W5-T2 (реестр + builder + endpoint) ──→ W5-T3 (сохранённые отчёты) ──→ W5-T4 (UI) ──→ W5-T5 (LLM, фаза 2)
```
W5-T1 ∥ W5-T2 параллельно.

---

### Task W5-T1: Бэкфилл истории состояний (ключ к «VIP в феврале»)

**Files:**
- Create: `backfill_player_state.py` (корень, по образцу `load_exports.py`)
- Modify: `player_state_daily.sql` из W3-T1 — если W3-T1 ещё не сделан, включить его DDL сюда (таблица описана в родительском плане, Волна 3)

**Интерфейс:** заполняет `retention.player_state_daily` за прошлое с шагом 1 день, с даты первого депозита в данных. Оба поля — детерминированные функции истории на дату T:
- `vip_level(T)`: правило казино (`player_features.sql:66-69`) над `sumIf(amount, type='deposit' AND status IN ('completed','approved','success') AND currency='TRY' AND created_at <= T)` + гейт max разового депозита ≥100 TRY к дате T.
- `lifecycle(T)`: multiIf по `dateDiff('day', last_bet_date_до_T, T)` — те же пороги 7/30/60/90.
- `dep_sum/dep_count/net(T)`: кумулятивы до T. `early_tier(T)`: по депозитам первой недели (не меняется после D7 — берётся как есть). `p_churn/pred_ltv_d90`: NULL для прошлого (модельных скоров задним числом честно нет) — в отчётах эти поля доступны только с даты начала живых снапшотов.
- Реализация ОДНИМ запросом на месяц (не по дням в цикле): `CROSS JOIN` календаря дней месяца × игроки с активностью до конца месяца, оконные агрегаты; вставка партиями по месяцу (таблица партиционирована `toYYYYMM(snap_date)`).

- [ ] **Step 1:** запрос для одного дня, ручная сверка на тест-игроке 808 (Royal: депозиты известны — vip_level должен подняться до 5 в исторически правильный день; сверить с `users.vip_level`-текущим).
- [ ] **Step 2:** помесячный бэкфилл, идемпотентность (повторный прогон месяца не дублирует — ReplacingMergeTree + OPTIMIZE или DELETE партиции перед вставкой).
- [ ] **Step 3:** прогнать весь диапазон данных; sanity: сумма игроков с vip_level≥3 на последнюю дату снапшота == текущему счётчику из `player_features` (±0). Commit `feat(reports): бэкфилл ежедневных состояний игрока из raw-фактов`

### Task W5-T2: Реестр метрик/разрезов + builder + endpoint

**Files:**
- Create: `api/report_fields.py`, `api/report_builder.py`, `api/reports.py` (blueprint)
- Test: `tests/test_report_builder.py`

**Interfaces (produces):**

`api/report_fields.py` — два реестра:
```python
METRICS = {  # key -> Metric(label_key, sql_expr, source: 'money'|'game'|'players', fmt: 'try'|'int'|'pct')
  'deposits_sum':   "sumIf(amount, {DEP_OK})",           # источник money_transactions
  'deposits_count': "countIf({DEP_OK})",
  'depositors':     "uniqExactIf(casino_player_id, {DEP_OK})",
  'withdrawals_sum':"sumIf(abs(amount), {WD_OK})",
  'bonus_cost':     "sumIf(abs(amount), {BONUS_OK})",
  'net_cash':       "deposits_sum - withdrawals_sum",     # производная
  'ftd_count':      "uniqExact(casino_player_id) WHERE first_deposit in period",  # спец-обработка в builder
  'ggr':            "sumIf(bet_amount,{BET}) - sumIf(win_amount,{WIN})",          # источник game_transactions
  'turnover':       "sumIf(bet_amount, {BET})",
  'active_players': "uniqExact(casino_player_id)",        # источник game_transactions
  'registrations':  "uniqExact(casino_player_id)",        # источник users по reg_date
}
DIMENSIONS = {  # key -> Dimension(label_key, kind: 'time'|'profile'|'state_at', sql_expr, values?)
  # time (по created_at периода, Istanbul): 'day', 'week', 'month', 'weekday', 'hour'
  # profile (статичные, из users): 'country', 'currency', 'affiliate_code', 'affiliate_type',
  #   'registration_source', 'payment_method' (из транзакции), 'account_type'
  # state_at (ИСТОРИЧЕСКИ КОРРЕКТНЫЕ, из player_state_daily НА ДАТУ строки данных):
  #   'vip_level_at', 'lifecycle_at', 'early_tier_at'
}
```
`api/report_builder.py`:
```python
def build_report_query(spec: dict) -> tuple[str, dict]:
    """spec = {metrics: [...], dims: [...] (порядок = порядок группировки, 1..3),
              filters: [{dim, op, value}], period: {from, to}, base: 'money'|'game'|'auto'}
    → один CH-запрос: FROM <факт-таблица> JOIN users (profile-разрезы)
      LEFT JOIN player_state_daily psd ON psd.casino_player_id = f.casino_player_id
        AND psd.snap_date = toDate(toTimezone(f.created_at,'Europe/Istanbul'))   -- state_at на дату СОБЫТИЯ
      GROUP BY dims ORDER BY dims. Whitelist-валидация: только ключи реестров,
      значения — параметрами. Метрики из разных источников в одном отчёте:
      builder собирает по источникам и FULL-джойнит по dims (макс 2 источника в MVP)."""
```
Правило исторической корректности (зашить в докстринг и тест): разрез `vip_level_at` для строки «февраль» использует состояние игрока НА ДАТУ события в феврале (join через snap_date), НЕ текущее. Тест-кейс: игрок, ставший VIP в марте, в февральской строке считается со своим февральским уровнем.

`api/reports.py` (blueprint `api_reports`, роли: `ANALYSTS`+руководители; см. заметку о ролях в W5-T3):
- `POST /api/v1/reports/run` `{spec}` → `{columns, rows, totals, meta: {rows_scanned, took_ms, history_from}}` — лимит 10 000 строк результата, таймаут 30с, `history_from` = первая дата снапшотов (UI предупреждает, если период раньше).
- `GET /api/v1/reports/fields` — оба реестра для UI.
- `POST /api/v1/reports/export.{csv,xlsx}` `{spec}` — тот же запрос, файл (openpyxl-паттерн `api/players_analytics.py:804`).

- [ ] **Step 1 (TDD):** `tests/test_report_builder.py`: (а) 1 метрика × 1 time-разрез; (б) порядок dims меняет GROUP BY/ORDER BY; (в) state_at-разрез джойнит psd по дате события; (г) фильтр по enum; (д) отказ: неизвестная метрика, 4 разреза, период > 366 дней. Падают → реализовать до зелёного.
- [ ] **Step 2:** endpoint + smoke: «депозиты по месяцам × vip_level_at» — сумма всех строк == сумме депозитов за период без группировок (инвариант разбиения!). Автотест инварианта в smoke-скрипте.
- [ ] **Step 3:** Commit `feat(reports): реестр метрик/разрезов + builder с исторической корректностью`

### Task W5-T3: Сохранённые отчёты + доступы

**Files:**
- Create: `supabase/migrations/0015_saved_reports.sql`, `api/reports_store.py`
- Modify: `api/reports.py` (CRUD-ручки)

```sql
CREATE SCHEMA IF NOT EXISTS automation;   -- идемпотентно, независимость от 0013
CREATE TABLE IF NOT EXISTS automation.saved_reports (
    report_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    spec       JSONB NOT NULL,
    owner_id   UUID NOT NULL REFERENCES crm.crm_users(id) ON DELETE CASCADE,
    visibility TEXT NOT NULL DEFAULT 'personal' CHECK (visibility IN ('personal','shared','roles')),
    roles      crm.user_role[] NOT NULL DEFAULT '{}',   -- для visibility='roles'
    is_official BOOLEAN NOT NULL DEFAULT false,          -- «канонический отчёт компании»
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, name));
```
Правила доступа (в Flask, зеркалом RLS): читать — владелец; `shared` — все роли с доступом к модулю; `roles` — перечисленные (кейс «зарплатный отчёт видит один менеджер» = `personal`). `is_official` ставят только `director/head_retention/super_admin`; официальные — вверху списка. Ручки: `GET/POST/PUT/DELETE /api/v1/reports/saved`, `POST /api/v1/reports/saved/<id>/duplicate`.
- [ ] **Step 1:** миграция + store + ручки, smoke: под двумя разными ролями видимость различается (curl с API_AUTH_OFF-подменой роли недостаточно — проверить через два тестовых JWT из seed_dev).
- [ ] **Step 2:** Commit `feat(reports): сохранённые отчёты — личные/общие/по ролям, официальные`

### Task W5-T4: UI конструктора отчётов

**Files:**
- Create: `crm-spa/app/(app)/reports/page.tsx` (+ loading/error), `crm-spa/components/reports/ReportBuilder.tsx`, `PivotTable.tsx`, `SavedReportsList.tsx`, `useReportRun.ts`
- Modify: `nav.ts` (пункт `reports` в модуль 📊 Аналитика), i18n `dictionaries/{ru,en,tr}/reports.ts`

- [ ] **Step 1:** панель сборки: мультиселект метрик, разрезы — упорядоченный список с кнопками ↑↓ (порядок = вложенность; максимум 3), фильтры (по enum-разрезам), период (`DateInput`×2 + пресеты «месяц/квартал»). Кнопка «Построить» → `useReportRun` (POST run).
- [ ] **Step 2:** `PivotTable`: рендер вложенных групп — уровень 1 строкой-заголовком (существующий стиль групповых строк из `CohortsView`), уровни 2–3 отступом; колонки-метрики с форматом (₺/число/%); итоговая строка. Смена порядка разрезов ре-строит таблицу (это и есть «сводная как в Excel»).
- [ ] **Step 3:** сохранение (диалог: имя, видимость, роли), список сохранённых (официальные сверху с `Badge`), «Открыть/Дублировать/Удалить». Экспорт CSV/XLSX. Предупреждение-`Banner`, если период раньше `history_from`: «до {дата} исторические статусы реконструированы из raw-данных, модельные поля недоступны».
- [ ] **Step 4:** 4 состояния, i18n ru/en/tr, build, скриншоты. Commit `feat(reports): UI — сводная таблица, порядок разрезов, сохранение и доступы`

### Task W5-T5 (фаза 2, отдельный запуск): «Волшебная кнопка» — текст → черновик

**Files:** Create: `api/report_llm.py`; Modify: `api/reports.py` (`POST /api/v1/reports/draft {text}`), `ReportBuilder.tsx` (поле «Опишите отчёт словами»)
- LLM-прослойка строго по ТЗ: текст → JSON-spec (structured output по json-схеме spec), данные считает НАШ builder — модель не видит и не выдумывает цифры. OpenRouter (ключ и клиент уже в `call_analyzer`); промпт содержит реестры METRICS/DIMENSIONS с описаниями; ответ валидируется тем же валидатором, что и ручной spec; невалидное → «не понял, уточните» (не молчаливый фолбэк).
- [ ] **Step 1:** endpoint + промпт + валидация; 5 тестовых формулировок из ТЗ (продуктовый/ретеновский/виповский/бонусный/«борды смотрят деньги») дают валидные spec. **Step 2:** UI-поле с предпросмотром черновика перед запуском. Commit `feat(reports): текст-ТЗ → черновик отчёта (LLM без доступа к цифрам)`

---

## Verification (оркестратор, после волны)
1. Инвариант разбиения: для 3 случайных комбинаций сумма по группам == тоталу без группировки (скрипт).
2. Историческая корректность: синтетическая проверка на игроке 808 — строки прошлых месяцев показывают ТОГДАШНИЙ vip_level (сверка с датами депозитов вручную).
3. Доступы: personal-отчёт не виден второй роли (два JWT).
4. Перф: отчёт «депозиты × месяц × vip_level_at» за весь период < 10с.
5. Стандартный прогон: build, eslint, i18n-аудит, скриншоты, code-review агент.
