# Этап 3, фаза 3а: конструктор сегментов · цепочки · каналы — детальный план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Родительский план: `docs/plans/2026-07-17-modules-etap3-plan.md` (Global Constraints оттуда действуют здесь целиком).

**Goal:** Замкнуть петлю MVP: оператор создаёт сегмент → вешает цепочку → система исполняет шаги (бонус-команда, сообщение) с контрольной группой и аналитикой шагов.

**Architecture:** Определения (сегменты/цепочки/шаблоны/каналы) — Postgres `crm.*` (Supabase, RLS, миграции 0013+), как analyzer-скрипты. Runtime-факты (членство, события шагов, отправки) — ClickHouse `retention.*`, как `trigger_log`/`segment_exports`. Исполнитель цепочек — отдельный poll-сервис по образцу `signals/rt_trigger.py`. Исходящие команды казино — расширение контракта `signals/pusher.py` (CALLBACK_URL + Bearer, DRY_RUN по умолчанию, fail-closed через PREDICTIONS_ENABLED).

**Tech Stack:** как в родительском плане + psycopg v3 (паттерн `api/call_analysis_store.py`).

## Ключевое проектное решение: каталог фильтров подключаемый

Каталог полей — реестр в `api/segment_fields.py`. **v1 (~60 полей) собирается из уже существующих данных и НЕ ждёт файла Василия.** Когда приедет «для ЦРМ.xlsx» (158 фильтров) — отдельная задача W4-T0 домержит каталог: каждый фильтр из файла получает статус `available` / `needs_event` (честные бейджи «ждёт события API» — как в Бонус-экономике). Поэтому волну можно начинать до файла; файл расширяет каталог, не меняя архитектуру.

То же с PII: отправители (`chains/senders.py`) изолированы за интерфейсом; решение proxy/direct меняет только конфигурацию каналов в W4-T4, не блокируя W4-T1..T3.

## Порядок и параллелизм

```
W4-T1 (сегменты: бэк) ──→ W4-T2 (сегменты: UI) ──┐
W4-T3 (цепочки: схема+CRUD) ──→ W4-T4 (runner+каналы) ──→ W4-T5 (цепочки: UI) ──→ W4-T6 (пресеты+DoD)
W4-T0 (импорт xlsx-каталога) — в любой момент после W4-T1, как только файл придёт
```
T1 ∥ T3 параллельно. Перед стартом волны: подтверждение PII-режима (для T4; рекомендация — proxy) и справочник бонусов казино (для действия «начислить бонус»; до него — коды из `BONUS_MAP` pusher'а: `first_deposit_bonus`, `second_deposit_reload`, `vip_offer`, `freespins`, `reload_cashback`).

---

### Task W4-T1: Сегменты — миграция 0013, компилятор, CRUD, материализация

**Files:**
- Create: `supabase/migrations/0013_segments.sql`
- Create: `api/segment_fields.py` (реестр полей v1)
- Create: `api/segment_compiler.py` (JSON → ClickHouse WHERE)
- Create: `api/segments.py` (blueprint CRUD + preview + members)
- Create: `api/segments_store.py` (Postgres-слой, паттерн `call_analysis_store.py`: psycopg ленивый, dict_row, параметризация, схема НЕ в PostgREST)
- Modify: `run_loop.sh` (шаг MATERIALIZE SEGMENTS после rebuild player_features)
- Test: `tests/test_segment_compiler.py` (pytest, чистые юнит-тесты компилятора без БД)

**Interfaces (produces):**

Миграция `0013_segments.sql` (стиль: комментарий-обоснование сверху, `IF NOT EXISTS`, как 0011):
```sql
CREATE SCHEMA IF NOT EXISTS automation;
CREATE TABLE IF NOT EXISTS automation.segments (
    segment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    sys_name     TEXT NOT NULL UNIQUE CHECK (sys_name ~ '^[a-z][a-z0-9_]{2,63}$'),
    description  TEXT NOT NULL DEFAULT '',
    definition   JSONB NOT NULL,          -- см. JSON-схему ниже
    is_trigger   BOOLEAN NOT NULL DEFAULT false,  -- real-time вход (считает runner каждый цикл)
    schedule_at  TIME NOT NULL DEFAULT '10:00',   -- время суточного пересчёта (Стамбул)
    created_by   UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at  TIMESTAMPTZ
);
-- RLS: читают роли из MARKETING+ANALYSTS+админы; пишут marketing_manager/head_retention/super_admin
-- (зеркалить паттерн политик 0007: schema не экспонируется в PostgREST, доступ только через Flask)
```

JSON-схема `definition` (валидируется в `api/segments.py` до записи):
```json
{ "all": [
    {"field": "dep_count", "op": "eq", "value": 1},
    {"any": [ {"field": "lifecycle", "op": "in", "value": ["cooling","at_risk"]},
              {"field": "recency_days", "op": "between", "value": [8, 30]} ]},
    {"not_segment": "safety_restricted"},
    {"event": {"type": "deposit", "status": "completed", "within_days": 30, "op": "gte", "count": 1}}
] }
```
- Группы: `all` (И) / `any` (ИЛИ), вложенность максимум 2 уровня (валидатор режет глубже).
- Операторы по типам (ТЗ §1.2): num — `eq, ne, gt, lt, between, top_pct`; date — `before, after, between, days_ago_gt, days_ago_lt`; enum — `in, not_in`; flag — `is, is_null`.
- `not_segment` — сегмент-исключение по `sys_name` (компилируется в `casino_player_id NOT IN (SELECT casino_player_id FROM retention.segment_members WHERE sys_name = %(x)s)`).
- `event` — раздел 0 каталога («событие X было/не было N раз за период») — компилируется в подзапрос к `money_transactions`/`game_transactions`/`live_events` по типу события.

`api/segment_fields.py` — реестр v1:
```python
FIELDS = { '<key>': Field(label_key, type, sql, section, values=None, available=True, needs=None) }
```
Состав v1 (все выражения — над `player_features AS f` + LEFT JOIN ML-таблиц + `users AS u`):
- §1 Профиль: `country, currency, account_type, activity_status, reg_date, tenure_days, phone_verified, email_verified, is_active, vip_level, timezone(u), marketing_consent(u), opt_out(u), do_not_contact(u), self_excluded(u), telegram_id_present(u), has_whatsapp(u), has_viber(u)`
- §2 Привлечение: `affiliate_code, affiliate_type, registration_source(u), traffic_sub_id(u)`
- §3 Депозиты: `dep_count, dep_sum, dep_failed, ftd_date, ftd_amount, is_depositor, first_deposit_date, last_deposit_date, deposit_recency_days, primary_payment_method, cash_deposits, net_cash, expected_next_deposit_days (ML: deposit_ladder/expected_gap)`
- §4 Выводы: `wd_count, wd_sum, wd_rejected, withdrawals_abs`
- §5 Финансы/риск: `net, balance, bonus_balance, bonus_cost`
- §6 Игра: `bets, turnover, avg_bet, max_bet, distinct_games, active_days, recency_days, last_bet_date, favourite_game, stuck_game, game_concentration, freespin_ratio, night_share, primary_provider, sessions_count, avg_session_min, bets_per_active_day`
- §9 Лайфсайкл: `lifecycle, churned_30d, churned_90d, login_recency_days, activity_recency_days, activation_lag_days`
- §10 Предиктивные: `p_churn (player_churn_ml), pred_ltv_d90 (player_ltv view), ltv_p10/p90 (quantiles), p_2nd_ml (player_repeat_ml), p_next_deposit (player_next_deposit_ml), rec_bonus (player_bonus_ml), early_tier, p_vip_churn, p_early_vip, p_non_promising`
- §0 События (механизм `event`): `deposit, withdrawal, bonus, bet, session_start, session_end` (из money/game/live_events)

`api/segment_compiler.py`:
```python
def compile_definition(definition: dict) -> tuple[str, dict]:
    """JSON-дерево → (WHERE-строка, params). Только whitelist FIELDS/операторов.
    Значения ТОЛЬКО через параметры {name:Type}; имена полей/операторов — только
    из реестра (инъекция невозможна). ValueError с человекочитаемой причиной."""
def base_query(where: str) -> str:
    """SELECT f.casino_player_id FROM player_features f LEFT JOIN ... WHERE account_type='normal' AND (<where>)"""
```

`api/segments.py` (blueprint `api_segments`, роли: читают `MARKETING_ROLES`+аналитики, пишут `marketing_manager, head_retention, super_admin`):
- `GET /api/v1/segments` — список (+счётчик последней материализации), `POST /api/v1/segments`, `PUT /api/v1/segments/<id>`, `POST /api/v1/segments/<id>/archive`, `POST /api/v1/segments/<id>/clone`
- `POST /api/v1/segments/preview` `{definition}` → `{count, sample: [первые 10 id]}` — live-счётчик (прямой count по compile, лимит времени запроса 10с)
- `GET /api/v1/segments/<id>/members?page=` + `GET /api/v1/segments/<id>/export.{csv,xlsx}` — реюз `pb._export_rows`
- `GET /api/v1/segments/fields` — каталог для UI (key, label, type, section, available, needs)
- Пресеты-шаблоны: `GET /api/v1/segments/presets` — 8 кампаний (`pb.SEGMENTS`), RFM-сегменты, архетипы как готовые definition для клонирования (условия переведены в JSON-формат, НЕ сырой SQL)

Материализация — CH-таблица (DDL добавить в `marts.sql`):
```sql
CREATE TABLE IF NOT EXISTS retention.segment_members (
    sys_name LowCardinality(String), casino_player_id UInt32,
    computed_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(computed_at) ORDER BY (sys_name, casino_player_id);
```
Пересчёт: скрипт `materialize_segments.py` (корень, по образцу `load_exports.py`): читает активные сегменты из PG, компилирует, `INSERT INTO segment_members SELECT ...` (предварительно `ALTER TABLE ... DELETE WHERE sys_name=...` — или полная перезапись по сегменту через временный ключ computed_at + чтение argMax); вызов из `run_loop.sh` (суточные — по schedule_at, триггерные — каждый прогон).

- [ ] **Step 1 (TDD компилятора):** написать `tests/test_segment_compiler.py`: (а) простое условие num/eq → WHERE с параметром; (б) all+any вложенность; (в) between; (г) not_segment; (д) event-подзапрос; (е) отказ: неизвестное поле, глубина 3, недопустимый оператор для типа. Запустить — тесты падают (модулей нет).
- [ ] **Step 2:** реализовать `segment_fields.py` + `segment_compiler.py` до зелёных тестов.
- [ ] **Step 3:** миграция 0013 + `segments_store.py` + `segments.py`; применить миграцию (`supabase db push` локально), smoke-curl всех ручек под `API_AUTH_OFF=1`: создать сегмент «тест: 1 депозит, остыл» → preview count > 0 → members → export.
- [ ] **Step 4:** `materialize_segments.py` + вставка в `run_loop.sh`; ручной прогон: строки в `segment_members` появились, повторный прогон не дублирует.
- [ ] **Step 5:** Commit `feat(segments): конструктор сегментов — каталог v1, компилятор, CRUD, материализация`

### Task W4-T0: Каталог Василия → реестр полей (файл ПОЛУЧЕН 17.07, маппинг ГОТОВ)

**Файл пришёл: `new_u/для ЦРМ.xlsx` (1 лист, 173 строки: 15 заголовков разделов + 158 нумерованных фильтров, колонки: номер | описание). Разметка доступности УЖЕ сделана оркестратором: `tools/filter_catalog_map.json`** — по каждому фильтру `{n, section, text, status, note}`, статусы: `ok` 68 · `ml` 8 · `internal` 5 (появятся после фазы 3а: send_log/enrollments) · `partial` 24 · `needs_event` 52 · `needs_ref` 1. Итого доступно сразу/после 3а: 81 из 158 (51%).

**Files:** Modify: `api/segment_fields.py`; Consume: `tools/filter_catalog_map.json`
- [ ] **Step 1:** для каждой записи map-файла со статусом `ok|ml|partial` завести Field в FIELDS (ключ — латинский slug по смыслу, `catalog_n=<n>` для трассировки к номеру Василия; sql-выражения для ok/ml — по реестру v1 из W4-T1, note из map-файла — в описание). `partial` — реализовать доступную часть, в label добавить уточнение из note.
- [ ] **Step 2:** `needs_event|needs_ref` добавить с `available=False, needs=<из note>` — UI показывает серыми с бейджем «ждёт события API». `internal` — `available=False, needs='phase3a'`, включаются задачами W4-T4.
- [ ] **Step 3:** сверка: в реестре ровно 158 полей с `catalog_n` (тест: набор номеров == 1..158). Список needs_event по разделам (уже напечатан оркестратором) — оформить в `new_u/Запрос_казино_фильтры_сегментации.md` как письмо казино (по образцу письма про бонусы из git HEAD). Commit `feat(segments): полный каталог 158 фильтров Василия — статусы доступности + запрос казино`

### Task W4-T2: UI конструктора сегментов

**Files:**
- Create: `crm-spa/app/(app)/segments/page.tsx` (+ loading/error), `crm-spa/components/automation/SegmentsList.tsx`, `SegmentEditor.tsx`, `ConditionRow.tsx`, `useSegmentPreview.ts`
- Modify: `nav.ts` (пункт `segments` в модуль ⚡, роли как у actions), i18n `dictionaries/{ru,en,tr}/automation.ts` (новый домен, подключить в `ru.ts`)

**Interfaces (consumes):** ручки W4-T1. Definition редактируется как дерево: группа И → строки условий и вложенные группы ИЛИ (макс 2 уровня, кнопка «+ группа ИЛИ»).
- [ ] **Step 1:** список сегментов (`DataTable`: имя, sys_name, счётчик, «пересчитан N ч назад», автор, архив) + кнопка «Из шаблона» (пресеты) + «Создать».
- [ ] **Step 2:** редактор: `ConditionRow` = Select поля (сгруппирован по разделам каталога, недоступные — disabled с бейджем) → Select оператора (по типу) → инпут значения (num/date/enum-мультиселект/flag); группы — отступом; live-счётчик через `useSegmentPreview` (debounce 500мс, показ «сейчас подходит N игроков», при ошибке компиляции — текст причины).
- [ ] **Step 3:** имя + sys_name (автотранслит с валидацией `^[a-z][a-z0-9_]+$`) + описание; чекбокс «триггерный (real-time)»; кнопки экспорта. 4 состояния экрана.
- [ ] **Step 4:** i18n ru/en/tr, `npm run build`, скриншоты. Commit `feat(segments): UI конструктора — группы И/ИЛИ, live-счётчик, шаблоны`

### Task W4-T3: Цепочки — миграция 0014, CRUD, версионирование

**Files:**
- Create: `supabase/migrations/0014_chains.sql`, `api/chains.py`, `api/chains_store.py`
- Test: smoke-curl сценарий в шагах

**Interfaces (produces):**
```sql
CREATE TABLE IF NOT EXISTS automation.chains (
    chain_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','active','paused','archived')),
    created_by UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS automation.chain_versions (
    version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id UUID NOT NULL REFERENCES automation.chains ON DELETE CASCADE,
    version_no INT NOT NULL, definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), activated_at TIMESTAMPTZ,
    UNIQUE (chain_id, version_no));
CREATE TABLE IF NOT EXISTS automation.chain_enrollments (
    enrollment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id UUID NOT NULL REFERENCES automation.chains ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES automation.chain_versions,
    casino_player_id BIGINT NOT NULL,
    current_node TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active','done','converted','exited')),
    ab_group TEXT NOT NULL DEFAULT 'main' CHECK (ab_group IN ('main','control')),
    entered_at TIMESTAMPTZ NOT NULL DEFAULT now(), next_wake_at TIMESTAMPTZ,
    exited_at TIMESTAMPTZ, exit_reason TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chain_active_player
    ON automation.chain_enrollments (chain_id, casino_player_id) WHERE state = 'active';
CREATE TABLE IF NOT EXISTS automation.templates (
    template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE, channel_kind TEXT NOT NULL
        CHECK (channel_kind IN ('casino_webhook','email','telegram')),
    texts JSONB NOT NULL DEFAULT '{}',   -- {"ru": "...", "en": "...", "tr": "..."} c {vars}
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
```
JSON-схема `definition` цепочки (линейный поток, ветвление только у condition):
```json
{ "trigger": {"kind": "segment", "sys_name": "second_dep_target", "reentry_days": 30}
             | {"kind": "event", "type": "deposit_failed"} | {"kind": "schedule", "cron": "0 10 * * *"},
  "control_pct": 16,
  "goal": {"event": "deposit", "attribution_days": 14},
  "nodes": [
    {"id": "n1", "kind": "action", "action": "bonus_grant", "bonus": "ml_recommended" },
    {"id": "n2", "kind": "wait", "mode": "ml", "fallback_hours": 24, "window": {"from": "11:00", "to": "22:00"}},
    {"id": "n3", "kind": "condition", "if": {"field": "dep_count", "op": "gte", "value": 2},
       "then": "exit_converted", "else": "n4"},
    {"id": "n4", "kind": "action", "action": "send_message", "channel": "casino_webhook",
       "template": "<template_id>", "params": {"bonus_amount": "{rec_bonus}"}}
  ] }
```
`api/chains.py` (роли записи как у сегментов): CRUD цепочек; `POST /chains/<id>/activate` — создаёт новую версию (изменение активной = новая версия, игроки внутри доходят по старой — версионирование по ТЗ §2.5); pause/archive; `POST /chains/<id>/clone`; `GET /chains/<id>/stats` — счётчики из `retention.chain_events` (вошло/прошло/выпало по узлам, конверсия main vs control).
- [ ] **Step 1:** миграция 0014 + store + blueprint; применить, smoke-curl: create → добавить definition (валидатор: узлы связаны, condition ссылается на существующие id, wait.mode ∈ fixed|event|ml) → activate v1 → изменить → activate v2 (v1 остаётся у активных enrollments).
- [ ] **Step 2:** Commit `feat(chains): схема цепочек — версии, enrollment с анти-дублем, шаблоны`

### Task W4-T4: Chain-runner + каналы + проверки

**Files:**
- Create: `chains/runner.py`, `chains/senders.py`, `chains/checks.py`, `chains/Dockerfile`, `chains/requirements.txt`
- Modify: `docker-compose.yml` (сервис `chain-runner` по образцу `rt-trigger`: тот же env-набор + SUPABASE_DB_URL), `marts.sql` (DDL двух CH-таблиц ниже), `.env.example`

**Interfaces (produces):**
```sql
CREATE TABLE IF NOT EXISTS retention.chain_events (
    ts DateTime64(3), chain_id String, version_no UInt16, node_id LowCardinality(String),
    casino_player_id UInt32, event LowCardinality(String),  -- enter|pass|drop|goal|exit
    reason LowCardinality(String), ab_group LowCardinality(String)
) ENGINE = MergeTree ORDER BY (chain_id, ts);
CREATE TABLE IF NOT EXISTS retention.send_log (
    ts DateTime64(3), casino_player_id UInt32, chain_id String, node_id String,
    channel LowCardinality(String), template_id String,
    status LowCardinality(String),   -- sent|failed|skipped|delivered|opened|clicked (последние 3 — когда казино начнёт слать message_status)
    reason String
) ENGINE = MergeTree ORDER BY (casino_player_id, ts);
```
`chains/runner.py` — цикл ~5с по образцу `rt_trigger.py` (тот же fail-closed `predictions_enabled()`, тот же паттерн watermark/кулдаун/восстановление после рестарта):
1. **Вход:** для активных цепочек с trigger.kind=segment — diff `segment_members` (триггерные сегменты пересчитывать здесь же по компилятору каждый цикл, лимит частоты 60с) минус активные/недавние enrollments (reentry_days) → INSERT enrollment (ab_group: `control`, если `cityHash64(casino_player_id, chain_id) % 100 < control_pct`); event-триггеры — по watermark live_events (как rt_trigger).
2. **Продвижение:** enrollments с `next_wake_at <= now()` (или свежесозданные) → исполнить текущий узел → записать `chain_events`, перейти к следующему / выставить next_wake_at.
3. **Узлы:** `action` — для ab_group=control НЕ исполнять (записать `pass reason=control`); `wait` — fixed: +N часов; event: до события или таймаут; ml: медиана gap из `deposit_ladder`/`repeat_deposit_model` для депозита №N (фолбэк `fallback_hours`); окно 11:00–22:00 по `users.timezone` (фолбэк Europe/Istanbul) — если вне окна, сдвинуть на начало окна; `condition` — компилятор W4-T1 точечно для одного игрока (`WHERE casino_player_id = X AND (<cond>)`); `goal` — проверка целевого события в окне атрибуции (проверяется на каждом wake + финальная по таймауту).
4. **Проверки перед send/bonus (`chains/checks.py`, ВСЕ — из существующих данных):** `marketing_consent AND NOT opt_out AND NOT do_not_contact AND NOT self_excluded` (users); канал существует (email≠''/telegram_id≠0 — для casino_webhook пропуск: контакты у казино); языковая версия шаблона есть (язык: `game_sessions.language` argMax, фолбэк 'tr'); не в игровой сессии сейчас (`live_events`: session_start без session_end за 2ч); fatigue — не больше `FATIGUE_MAX_SENDS` (env, дефолт 3) за `FATIGUE_WINDOW_DAYS` (дефолт 7) по `send_log`; не в сегменте `sys_name='safety_restricted'` (если существует). Непрошедшие → `chain_events drop` с reason.
5. **`chains/senders.py`:** интерфейс `send(channel, player, template, params) -> (ok, reason)`. MVP: `casino_webhook` — POST CALLBACK_URL `{"command": "send_message", "player_id", "channel_hint", "template_id", "params"}` и `{"command": "bonus_grant", "player_id", "bonus_id"|"ml_recommended"}` (Bearer CALLBACK_TOKEN, ретраи как в pusher, DRY_RUN по умолчанию); `email` — SMTP из env (SMTP_HOST/PORT/USER/PASS/FROM), рендер {vars} из texts[lang]; `telegram` — sendMessage через TELEGRAM_BOT_TOKEN на `users.telegram_id`. Всё в `send_log`.
- [ ] **Step 1:** senders + checks с юнит-проверкой рендера шаблонов и fatigue-запроса (pytest, CH-запросы замокать).
- [ ] **Step 2:** runner; локальный прогон на тестовой цепочке из W4-T3 с DRY_RUN=1: enrollment создался, узлы прошли, control не получил действий, chain_events/send_log заполнены.
- [ ] **Step 3:** docker-compose сервис + .env.example переменные. Commit `feat(chains): исполнитель цепочек — узлы, контроль 16%, проверки, каналы MVP`

### Task W4-T5: UI цепочек

**Files:**
- Create: `crm-spa/app/(app)/chains/page.tsx` (+ loading/error), `crm-spa/components/automation/ChainsList.tsx`, `ChainEditor.tsx`, `NodeCard.tsx`, `ChainStats.tsx`, `TemplatesPanel.tsx`
- Modify: `nav.ts` (пункт `chains` в ⚡), i18n `automation.ts`

Линейный редактор (ТЗ фаза 3а: вертикальный поток, БЕЗ свободного холста): столбец `NodeCard` сверху вниз, у condition — две ветки отступом. Каждый узел — существующая `Card` с `Select`-полями по kind. Статусы цепочки — `Badge` (draft/active/paused/archived), версия — `Pill`. `ChainStats`: таблица по узлам вошло/прошло/выпало (+причины drop), конверсия в цель main vs control, деньги (депозиты после прохождения из money_transactions по enrollments). Поиск по списку (по имени/сегменту/статусу).
- [ ] **Step 1:** список + просмотр статистики; **Step 2:** редактор + активация с подтверждением («создаст версию N»); **Step 3:** панель шаблонов сообщений (CRUD, языковые вкладки ru/en/tr, превью подстановки); **Step 4:** 4 состояния, i18n, build, скриншоты. Commit `feat(chains): UI — линейный редактор, версии, аналитика шагов`

### Task W4-T6: Пресеты, DoD, нагрузка

**Files:** Create: `chains/presets.py` (сидер: 3 пресета-черновика при пустой таблице) — «1-й→2-й депозит» (сегмент dep_count=1+cooling → bonus ml_recommended → wait ml → condition dep_count≥2 → send_message), «Winback» (churned+LTV>медианы → нарастающие 2 касания), «VIP→Пульт» (vip_level≥3 + p_churn высокий → действие `desk_task`: INSERT в существующую очередь `crm.player_assignments` — «не бонусом, а человеком»).
- [x] **Step 1:** сидер `chains/presets.py` (3 пресета-черновика + их сегменты preset_second_dep/preset_winback/preset_vip_risk, идемпотентно по sys_name/name) + действие `desk_task` в runner (реализовано в W4-T4). Прогон: 3 пресета в списке (draft), сегменты материализованы 355/1727/9.
- [x] **Step 2:** DoD фазы 3а из ТЗ §6 построчно (10 пунктов) — пройден, вердикты в отчёте W4-T6. Пресет «1-й → 2-й депозит» активирован и прогнан на preset_second_dep (355 игроков, DRY_RUN): вход → бонус-вебхук → проверки → ML-ожидание; контроль без действий; журналы заполнены; после — возврат в draft + чистка.
- [x] **Step 3:** нагрузка замерена: материализация 41 610 игроков — 0.074с (preview API — 0.038с), вход 4 039 enrollments за 0.340с (батч, сплит control 16.07%), advance 4 039 за 19.5с. Commit `feat(chains): пресеты + приёмка DoD фазы 3а`

---

## Что остаётся казино/команде (не наши задачи, отслеживать)
- События: `cashier_opened`, `deposit_failed`(+причина), bonus-цикл, `opt_in_changed`, `message_status`, `call_status` — по списку ТЗ §5. Без них: failed-deposit-триггер, каскад по «нет открытия», раздел 8/11 каталога — `available=false`.
- Справочник бонусов (ID+параметры) для действия «начислить бонус» и валидации `bonus_grant`.
- Ответ казино на команды (`granted/rejected`) — для блока «условие по ответу вебхука» (в MVP ветвление по статусу доставки).
- PII-решение зафиксировать письменно (рекомендация: proxy).
