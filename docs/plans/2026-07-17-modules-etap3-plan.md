# План интеграции: модульная перестройка CRM + задел этапа 3

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перестроить меню CRM в 7 модулей (ТЗ этапы 1–2), добавить 4 новых блока (Бонус-экономика, Вердикты по источникам, Лента флагов, VIP-пресет), заложить фундамент под конструктор отчётов и этап 3.

**Architecture:** Всё делается в существующей архитектуре: Next.js SPA (`crm-spa/`) + headless Flask JSON API (`api/*.py`, blueprint-автодискавери) + ClickHouse `retention.*` (аналитика) + Supabase `crm.*` (app-state, RBAC). Новые экраны собираются ТОЛЬКО из существующих UI-компонентов (`components/ui/*`), дизайн не меняется. Старые URL сохраняются — меняется только группировка меню.

**Tech Stack:** Next.js 16 (App Router), React 19, Tailwind v4 tokens, Flask + clickhouse_connect (HTTP 8123), Supabase Auth/JWT (роли в `app_metadata`), i18n ru/en/tr (ru — базовый словарь).

## Global Constraints

- **Дизайн НЕ менять**: только существующие компоненты `crm-spa/components/ui/` (`SCard`, `Pill`, `Badge`, `DataTable`, `Tabs`, `EmptyState`, `ErrorState`, `Skeleton`, `Banner`, `PageHeader`, `Eyebrow`) и токены из `crm-spa/app/globals.css`. Никаких новых цветов/шрифтов/библиотек.
- **4 состояния обязательны** для каждого нового экрана/блока: loading (скелетон) / empty (пояснение + что сделать) / error (сообщение + повтор) / data. Паттерн: `useFlaskData` + `States.tsx`, либо route-level `loading.tsx`/`error.tsx` (пример: `app/(app)/pool/`).
- **Старые URL работают**: ни один существующий route не удаляется и не переименовывается.
- **i18n 100%**: каждый новый ключ — в ru + en + tr (`crm-spa/lib/i18n/dictionaries/{ru,en,tr}/`). ru — источник ключей, en/tr — переводы (не пустые).
- **Роли не ослаблять**: новые экраны получают role-набор не шире ближайшего существующего аналога (`nav.ts:34-105`, `components/*/guard.ts`, `@require_auth(roles=...)` на Flask).
- **Backend-паттерн**: новый домен = `api/<domain>.py` с `bp = Blueprint('api_<domain>', __name__, url_prefix='/api/v1')`, `@require_auth`, запросы через `pb.q(...)`, ответ через `api_json(...)`. Автоregистрация — без правок `player_board.py`.
- **CH-конвенции**: хранение UTC, бизнес-день = `toTimezone(created_at,'Europe/Istanbul')`; в оконных фильтрах локально НИКАКИХ tz-функций (server tz = Asia/Makassar — см. memory); LEFT JOIN даёт 0, не NULL; `minOrNull` вместо `toString(min())`.
- **Коммиты**: conventional (`feat(nav): ...`, `feat(bonus): ...`), по одному на задачу, в `main` (как в прошлых сессиях). Без Co-Authored-By (attribution отключён глобально).
- **Модель для субагентов**: Opus 4.8 (`model: "opus"` в Agent tool). Верификация после каждой волны — оркестратором (Fable).
- **Файлы**: новые модули держать < 400 строк; большие экраны — компонент на секцию.

## Недостающие входные материалы (зафиксировано 17.07.2026)

| Файл из ТЗ | Статус | Обход |
|---|---|---|
| `Retivo_модули_демо.html` (тексты шапок модулей) | нет в репо, Drive недоступен (re-auth) | Тексты «боль/кресло/действие» написаны в W1-T2 из самих ТЗ — пометить `// TODO согласовать с Василием` |
| `для ЦРМ.xlsx` (158 фильтров, 15 разделов) | нет в репо | Блокер только для этапа 3 (Волна 4). Каталог v1 — из полей `player_features` + ML-таблиц (~60 фильтров, разделы 0–6, 9, 10) |
| `Цепочки_Василий_разбор.md`, `Maestra_референс` | нет в репо | Ключевые требования уже перенесены в текст ТЗ этапа 3 |
| ТЗ Bonus Analytics (первоисточник) | нет в репо | Все цифры и структура есть в ТЗ-1 §3.3 |

---

# ВОЛНА 1 — Этап 1 ТЗ: меню 7 модулей + шапки (2 задачи, параллельно)

### Task W1-T1: Перестройка NAV_GROUPS в 7 модулей

**Files:**
- Modify: `crm-spa/components/ui/nav.ts` (NAV_GROUPS: строки 107-200; типы 17-32)
- Modify: `crm-spa/components/ui/AppShell.tsx` (рендер секций: цикл групп на 59-88)
- Modify: `crm-spa/lib/i18n/dictionaries/ru/nav.ts`, `en/nav.ts`, `tr/nav.ts`
- Test: ручная проверка + `npm run build` + существующий рендер `/dev/ui`

**Interfaces:**
- Produces: `NavGroup` получает опциональное поле `section?: MessageKey` (секция-разделитель над группой). `NAV_GROUPS` — ровно 7 групп в порядке ТЗ. Все существующие `key`/`href`/`roles` элементов сохраняются без изменений.
- Consumes: `canSee()`, `activeKeyForPath()` — не менять.

Целевая структура (все элементы — существующие, ни один не удаляется):

```
[nav.section.entry «Вход»]
  1. nav.group.traffic «📡 Трафик и аффилиаты»: affiliates, affiliate (кабинет), channels(W2-T5), verdicts(W2-T2)
  2. nav.group.vip «🐋 VIP-радар»: ltv, dist, vip-risk, vip-queue(W2-T4, href /desk?act=SAVE&tier=cd)
[nav.section.expand «Расширение»]
  3. nav.group.bonuseco «🎁 Бонус-экономика»: bonus, bonuses, campaigns, ggr-bonus(W2-T5, href /ggr#bonus)
  4. nav.group.risk «🛡 Риск и фрод»: audit(=nav.risk), flags(W2-T3)
[nav.section.core «Ядро»]
  5. nav.group.core «⚡ Retention-автоматизация»: players, desk, queue, calendar, live, report, actions, games, exports,
     + вся группа звонков (8 экранов call-analysis — подзаголовком внутри модуля, title calls.nav.group сохранить)
[nav.section.layer «Слой / фундамент»]
  6. nav.group.analytics «📊 Аналитика»: overview, analytics, funnel, rfm, cohorts, archetypes, ggr, cash(#cash)
  7. nav.group.data «🧱 Данные / API»: schema, formulas, glossary, signals, keys, admin(users)
```

- [ ] **Step 1:** В `nav.ts` добавить `section?: MessageKey` в `NavGroup`; пересобрать `NAV_GROUPS` по структуре выше. Элементы, помеченные W2-*, НЕ добавлять в этой задаче (появятся в своих задачах) — только 7 групп из существующих элементов. Роль-наборы элементов не трогать.
- [ ] **Step 2:** В `AppShell.tsx` перед группой с `section` рендерить разделитель — маленький uppercase-лейбл в стиле существующего заголовка группы (`--color-sb-grp`), визуально чуть заметнее отступом. Ничего нового в CSS не изобретать.
- [ ] **Step 3:** i18n: ключи `nav.section.{entry,expand,core,layer}`, `nav.group.{traffic,vip,bonuseco,risk,core,analytics,data}` в ru/en/tr. Старые ключи групп (`nav.group.main` и т.д.) не удалять (обратная совместимость словаря).
- [ ] **Step 4:** `cd crm-spa && npm run build` — зелёный. Прокликать все пункты меню: каждый старый URL открывается, active-подсветка работает (проверить `activeKeyForPath` на `/ggr#bonus` — hash игнорируется, это ок: активным будет ggr-bonus по exact href? Нет — hash строится в `href`, а matcher его отрезает; допустимо, чтобы активным подсвечивался `ggr`).
- [ ] **Step 5:** Commit `feat(nav): 7 модулей по ТЗ перестройки — секции вход/расширение/ядро/слой`

### Task W1-T2: Шапки модулей «чья боль / боль / действие»

**Files:**
- Create: `crm-spa/components/ui/ModuleHeader.tsx`
- Create: `crm-spa/lib/i18n/dictionaries/ru/modules.ts` (+ en, tr; подключить в `dictionaries/ru.ts:27-41` и зеркала)
- Modify (вставка одной строки в каждый «главный» экран модуля): `components/affiliates/AffiliatesScreen.tsx`, `app/(app)/ltv/*` (главный экран), `components/marketing/BonusScreen.tsx`, `app/(app)/audit/AuditScreen.tsx`, `app/(app)/desk/*` (экран Пульта), `app/(app)/overview/OverviewScreen.tsx`, `app/(app)/schema/*`

**Interfaces:**
- Produces: `<ModuleHeader module="traffic" />` — компонент: свёрнутая плашка-карточка (существующий `Card` + `Pill`) с тремя полями: `modules.<key>.chair` (Чья боль — кресло), `modules.<key>.pain` (Боль), `modules.<key>.action` (Действие из экрана). Ключи модулей: `traffic|vip|bonuseco|risk|core|analytics|data`.
- Тексты писать из ТЗ (карта п.3.1–3.7) — короткие, 1 предложение на поле. Пример для traffic: chair = «Хед аффилиат-отдела», pain = «Куда уходит бюджет: какие источники дают игроков, а какие — фрод», action = «Решение по источнику: масштабировать · наблюдать · отключить». Пометить в PR-описании: тексты черновые, согласовать с Василием (оригинал — в недоступном демо-файле).

- [ ] **Step 1:** Создать `ModuleHeader.tsx`: обычная `Card` с тремя колонками `Eyebrow`+текст (на мобильном — столбиком, `grid md:grid-cols-3`). Никаких новых стилей.
- [ ] **Step 2:** Словарь `modules.ts` ru/en/tr: 7×3 ключей + `modules.header.chair/pain/action` (подписи полей).
- [ ] **Step 3:** Вставить `<ModuleHeader module="..."/>` под `PageHeader` на 7 главных экранах (по одному на модуль, список в Files).
- [ ] **Step 4:** `npm run build` зелёный; скриншот одного экрана — плашка визуально неотличима от существующих карточек.
- [ ] **Step 5:** Commit `feat(nav): шапки модулей — чья боль / боль / действие`

---

# ВОЛНА 2 — Этап 2 ТЗ: экранные доработки (6 задач, параллельно; W2-T5 после W1-T1)

### Task W2-T1: Бонус-экономика — реструктуризация /bonus (KPI P&L + воронка)

**Files:**
- Create: `api/bonus_economics.py`
- Modify: `crm-spa/components/marketing/BonusScreen.tsx` (реструктуризация; текущие секции — строки 78-157), `crm-spa/components/marketing/types.ts`
- Create: `crm-spa/components/marketing/BonusEconomicsKpi.tsx`, `crm-spa/components/marketing/BonusFunnel.tsx` (секции — отдельными файлами, чтобы BonusScreen не разбухал)
- Modify: i18n `dictionaries/{ru,en,tr}/marketing.ts`

**Interfaces:**
- Produces: `GET /api/v1/bonus/economics?from&to&type&campaign&aff&vip` → `{ kpi: [...7 плашек...], funnel: [...7 этапов...], abuse: {personas: N, share_pct: X}, filters: {applied: {...}} }`, roles = `MARKETING_ROLES` (те же, что у `/bonus` — `api/marketing.py`).
- KPI-элемент: `{key: 'issued'|'cost'|'incr_deposits'|'ggr'|'ngr'|'roi'|'uplift', value: number|null, status: 'ok'|'partial'|'needs_event', event?: 'bonus_converted'|...}`.
- Funnel-этап: `{stage: 'issued'|'activated'|'wagering_started'|'wagering_done'|'converted_or_expired'|'deposit_14d'|'retained_30d', status: 'ok'|'missing'|'indirect', value: number|null, note_key?: string}`.
- Существующие блоки uplift (ATT +1.4 п.п., CI) и таблица типов НЕ пересчитываются — берутся из существующего `/api/v1/bonus` (`api/marketing.py:174-207`), математику не трогать (ТЗ §3.3.3).

Расчёты (все источники уже есть):
- `issued`: `sum(abs(amount)), count(), uniqExact(player)` по `money_transactions WHERE BONUS_OK` (константа `player_board.py:121`) + фильтры: период по `created_at` (Istanbul), тип — классификатор `multiIf` как в `api/money.py:326-328`, кампания — `payment_method LIKE 'campaign:%'`, аффилиат — join `users.affiliate_code`, vip — join `player_features.vip_level`. status `ok`.
- `ngr`: как в `api/money.py:150-153` (`calc_ngr`); при активных фильтрах по кампании/аффилиату — status `partial` (провайдерские косты не делятся по срезам), иначе `ok`.
- `incr_deposits`/`uplift`: из `bonus_uplift` (метрики `att_pp/ci_lo_pp/ci_hi_pp`), фильтры игнорируют → status `partial`, в подписи «модельная оценка, весь период».
- `cost`, `roi`: value null, status `needs_event`, event `bonus_converted` — плашка рендерит EmptyState-текст «нужно событие bonus_converted — см. спецификацию» (ТЗ §4.1).
- Воронка: `issued` ✅ из money_transactions; `activated/wagering_*` — `SELECT count() FROM bonus_status_current WHERE status=...` (сейчас 0 строк → status `missing`, подпись «ждёт события API»); `converted_or_expired` — status `indirect`, value = сумма списаний `type='manual_withdrawal' AND status='completed'` (≈22.5 Mn, запрос как `api/money.py:424`); `deposit_14d`/`retained_30d` ✅ — из `bonus_effectiveness_t` (`dep_resp_14d_pct`, `retained_30d_pct`, взвешенные по `bonus_events`).
- `abuse`: count персоны `🎁 Бонусник` (запрос как `api/segmentation.py:258-262` с `PERSONA_SQL`), ссылка на `/flags?kind=bonus_abuse` (экран W2-T3).

- [ ] **Step 1 (test-first):** smoke-тест API до реализации: `curl -s localhost:8050/api/v1/bonus/economics` (при `API_AUTH_OFF=1`) → ожидание 404. После реализации — 200, в `kpi` ровно 7 ключей, `cost.status=='needs_event'`, `funnel` ровно 7 этапов, `issued.value > 0`.
- [ ] **Step 2:** Реализовать `api/bonus_economics.py` по контракту (blueprint-паттерн из Global Constraints; SQL через `pb.q`; период naive-арифметикой Istanbul → UTC как в `api/affiliates.py:94-122`).
- [ ] **Step 3:** Фронт: перекомпоновать `BonusScreen.tsx` в порядок ТЗ §3.3: (1) `BonusEconomicsKpi` — `SCardGrid` из 7 `SCard` с бейджем статуса (`Badge`: считается/частично/нужно событие); (2) `BonusFunnel` — `DataTable` этапов, строки `missing` — приглушённые с бейджем «ждёт события API»; (3) существующий uplift-блок; (4) существующая таблица типов; (5) фильтры (`Select`/`DateInput` в `ChipBar`-строке, состояние в URL `?from&to&type&campaign&aff&vip` по паттерну b_* из `BonusSection.tsx:113-118` — читать после гидратации!); (6) плашка abuse со ссылкой в `/flags`.
- [ ] **Step 4:** 4 состояния: loading — `SCard loading`; error — `ErrorState`+reload; empty (нет данных за период) — `EmptyState` с текстом «за период нет выдач»; у `needs_event`-плашек — постоянный поясняющий текст (это НЕ error-state).
- [ ] **Step 5:** i18n все новые ключи ru/en/tr; `npm run build`; скриншот.
- [ ] **Step 6:** Commit `feat(bonus): Бонус-экономика — KPI P&L с бейджами доступности + воронка бонуса`

### Task W2-T2: Трафик — экран «Вердикты по источникам»

**Files:**
- Create: `api/traffic.py`
- Create: `crm-spa/app/(app)/verdicts/page.tsx` (+ `loading.tsx`, `error.tsx` по образцу `app/(app)/pool/`)
- Create: `crm-spa/components/affiliates/VerdictsScreen.tsx`
- Modify: `crm-spa/components/ui/nav.ts` (пункт `verdicts` в группу traffic), i18n

**Interfaces:**
- Produces: `GET /api/v1/traffic/verdicts?dim=source|affiliate&days=30` → `{rows: [{source, players, players_7d, ftd, ftd_sum, deposits, pred_d90_sum, pred_d90_avg, p10_sum, p90_sum, ggr_real, verdict: 'scale'|'watch'|'disable'|'maturing', confidence: 'high'|'mid'|'low', age_days}], meta:{asof}}`. Roles — как у `/affiliates` (`api/affiliates.py`, `AFF_ROLES`-набор).
- Consumes: `retention.player_ltv` (`pred_ltv_d90`, `marts.sql:64`), `player_ltv_quantiles` (`ltv_p10/p90`), `users.registration_source/affiliate_code` (`schema.sql:50-64`).

Логика (в плане — черновые пороги, агенту пометить их константами вверху файла с комментарием «пороги согласовать»):
- Когорты: игроки с регистрацией за последние `days`, группировка по `dim`. `age_days` = дней с медианной даты регистрации когорты.
- `maturing`: `age_days < 5` ИЛИ `players < 10` — вердикт не выносим, фронт показывает «зреет · вердикт через N дн» (ТЗ §4.1).
- `disable`: `ggr_real < 0` (уже готовый флаг «игроки бьют игры», логика `api/affiliates.py:144`) ИЛИ `pred_d90_avg < 0.5 × глобальная медиана pred_ltv_d90`.
- `scale`: `pred_d90_avg > 1.5 × медиана` И `ftd/players ≥ глобальный FTD-rate`.
- `watch`: остальное. `confidence`: high если `players ≥ 50` и `(p90_sum-p10_sum)/pred_d90_sum < 1.5`; low если `players < 20`.
- [ ] **Step 1:** Реализовать endpoint; проверить `curl`-ом: у когорт моложе 5 дней verdict=`maturing`.
- [ ] **Step 2:** Экран: `DataTable` (колонки из ТЗ §3.1: игроков 7д, FTD, депозиты, прогноз LTV D90, уверенность, вердикт-бейдж — `Badge` с существующими тонами pos/neg/нейтральный), переключатель `dim` (`Tabs`), 4 состояния. Empty — «за период нет новых регистраций».
- [ ] **Step 3:** nav-пункт `verdicts` (emoji 🔮 или из `icons.tsx` ближайший), i18n ru/en/tr, build, скриншот.
- [ ] **Step 4:** Commit `feat(traffic): вердикты по источникам — прогноз качества когорты на 5-й день`

### Task W2-T3: Риск — «Лента флагов»

**Files:**
- Create: `api/risk.py`
- Create: `crm-spa/app/(app)/flags/page.tsx` (+ loading/error), `crm-spa/components/money/FlagsScreen.tsx`
- Modify: `nav.ts` (пункт `flags` в группу risk), i18n

**Interfaces:**
- Produces: `GET /api/v1/risk/flags?kind=` → `{rows: [{kind, entity: 'player'|'operator'|'affiliate', id, label, amount_try, count, severity: 1|2|3, href, details}], totals: {by_kind}, checked_at}`. Roles = `AUDIT_ROLES` (`api/money.py:50`, включает risk_officer).
- Consumes (всё уже посчитано, задача — агрегация в одну ленту):
  - `no_deposit_withdrawal`: запрос `zd` из `api/money.py:432-436` (manual_withdrawal > 50k при dep < 10%) — href `/player/{id}`.
  - `suspicious_operator`: reviewers с `unclear_pct >= 40` из `api/money.py:425,451-453` — href `/audit`.
  - `affiliate_players_win` / `affiliate_cash_drain`: строки с `pw`/`cd` из логики `api/affiliates.py:144-145` — href `/affiliates/{code}`.
  - `bonus_abuse`: игроки персоны Бонусник с `net > 0` (профит на фриспинах): `PERSONA_SQL` + `player_features.net` — href `/player/{id}`.
- Сортировка: `severity desc, amount_try desc`.
- [ ] **Step 1:** Endpoint + curl-проверка: без `kind` — все виды, totals сходятся с источниками (сверить числа с `/api/v1/audit` и `/api/v1/affiliates`).
- [ ] **Step 2:** Экран: KPI-строка по видам (`SCardGrid`, клик = фильтр по kind — паттерн горячих плиток `AffiliatesScreen.tsx:87-101,192-199`), `DataTable` ленты, бейдж вида, ссылки на карточки. **Empty-state по ТЗ §4.1**: «флагов нет — всё чисто, последняя проверка N мин назад» (использовать `checked_at`).
- [ ] **Step 3:** nav, i18n, build, скриншот. Commit `feat(risk): лента флагов — единая очередь «требует проверки»`

### Task W2-T4: VIP-пресет Пульта

**Files:**
- Modify: `api/monitor.py` (эндпоинт `/desk`, WHERE-карта: строки 84-91, запрос 108-113)
- Modify: экран Пульта (`app/(app)/desk/` компонент — читать параметр из URL, показать чип активного пресета)
- Modify: `nav.ts` (пункт `vip-queue`, href `/desk?act=SAVE&tier=cd`), i18n

**Interfaces:**
- Produces: `GET /api/v1/desk?act=&w=&tier=cd` — новый параметр `tier=cd` добавляет `AND early_tier IN ('C','D')` (поле уже есть в `player_actions`, `marts.sql:78`). Ничего другого в выдаче не меняется.
- [ ] **Step 1:** Параметр на бэке (whitelist: только `cd`), curl-проверка: с `tier=cd` все строки имеют tier C/D.
- [ ] **Step 2:** Фронт: пробросить параметр, чип «🐋 VIP-пресет» с крестиком-сбросом (существующий `Chip`).
- [ ] **Step 3:** nav-пункт в VIP-радар. Commit `feat(desk): VIP-пресет очереди — tier C/D`

### Task W2-T5: Переносы существующего (Каналы-вкладка, ggr#bonus, риск-часть аффилиатов)

**Files:**
- Create: `crm-spa/app/(app)/channels/page.tsx` — рендерит существующий `CohortsView` с фильтром группы `B · Канал` (данные из существующего `/api/v1/cohorts`, клиентская фильтрация `groups[].name`)
- Modify: `crm-spa/components/segmentation/CohortsView.tsx` — опциональный prop `onlyGroups?: string[]`
- Modify: `crm-spa/components/affiliates/AffiliatesScreen.tsx` — риск-плитки/чипы (строки 87-101, 192-199, 255-268) вынести во вкладку «Риск» (`Tabs`: «Качество» | «Риск»); дефолт — «Качество» без риск-колонок
- Modify: `crm-spa/app/(app)/ggr/GgrScreen.tsx` — поддержать `#bonus` (открывать бонус-таб по hash; таб уже есть: строки 70, 394)
- Modify: `nav.ts` (`channels` в traffic, `ggr-bonus` в bonuseco), i18n

- [ ] **Step 1:** `CohortsView` prop + страница `/channels` (4 среза B4–B7). На `/cohorts` группа B остаётся (ТЗ: в Аналитике убрать срезы B — по карте §3.6 они уезжают в Трафик; решение: на `/cohorts` скрыть группу B через `onlyGroups`-инверсию, оставив подпись-ссылку «Каналы → Трафик»).
- [ ] **Step 2:** Вкладки на `/affiliates`; риск-контент без изменения логики.
- [ ] **Step 3:** hash-обработка в GgrScreen (`useEffect` по `window.location.hash` после гидратации).
- [ ] **Step 4 (ТЗ §3.7):** Roadmap-блок в модуле Данные/API: на `/schema` под шапкой — `Card` со списком пунктов и `Badge`-статусами: мультибренд «скоро» · роли «готово» · коннекторы платформ «скоро» · события бонусов «ждёт казино». Статические i18n-тексты, без бэка.
- [ ] **Step 5:** nav + i18n + build + прокликать. Commit `feat(nav): переносы — каналы в Трафик, риск-вкладка аффилиатов, ggr#bonus, roadmap в Данные/API`

### Task W2-T6: Названия игр локально (dict_game_names DDL)

**Files:**
- Modify: `schema.sql` (после 149: DDL `retention.game_names` + `CREATE DICTIONARY retention.dict_game_names`)
- Modify: `player_board.py:996` (комментарий-предупреждение обновить)

**Interfaces:** `GN()` (`player_board.py:93-99`) уже резолвит имена через словарь и фолбэкается на «id …» — менять его не нужно. Задача только про DDL, чтобы локальная база не отличалась от прода.
- [ ] **Step 1:** DDL: `game_names(game_uuid String, game_name String, provider String, updated_at DateTime) ENGINE=ReplacingMergeTree(updated_at) ORDER BY game_uuid` + `DICTIONARY dict_game_names ... LAYOUT(COMPLEX_KEY_HASHED()) SOURCE(CLICKHOUSE(TABLE 'game_names')) LIFETIME(300)` — сверить сигнатуру с фактическим прод-вызовом `dictGet('retention.dict_game_names','game_name',tuple(uuid))`.
- [ ] **Step 2:** Применить локально (`clickhouse client < ...` фрагмент), проверить `/api/v1/games` — не падает, имена или фолбэк. Commit `feat(schema): DDL справочника имён игр — паритет локали с продом`

---

# ВОЛНА 3 — Задел (1 задача + 1 ops)

### Task W3-T1: player_state_daily — точка-в-времени снапшот (задел отчётов и исторических сегментов)

Конструктор отчётов по его ТЗ «в разработку пока не берём», но его дифференциатор — историческая корректность сегментов («VIP в феврале = кто БЫЛ VIP в феврале»). Сегодня истории нет (`player_features` — DROP+CREATE текущего среза; единственный прецедент — `retention.segment_exports`). Прошлое частично реконструируемо из raw-фактов, но дешевле начать копить снапшот сейчас.

**Files:**
- Create: `player_state_daily.sql` (DDL + INSERT-запрос)
- Modify: `run_loop.sh` (после rebuild `player_features` — строка 155: раз в сутки INSERT среза)

**Interfaces:**
- Produces: `retention.player_state_daily(snap_date Date, casino_player_id UInt32, vip_level UInt8, lifecycle LowCardinality(String), dep_sum Float64, dep_count UInt32, net Float64, early_tier LowCardinality(String), p_churn Nullable(Float32), pred_ltv_d90 Nullable(Float64)) ENGINE=ReplacingMergeTree() PARTITION BY toYYYYMM(snap_date) ORDER BY (snap_date, casino_player_id)`.
- [ ] **Step 1:** DDL + INSERT `SELECT today(), ... FROM player_features LEFT JOIN player_churn_ml ... LEFT JOIN player_ltv ...`; идемпотентность — ReplacingMergeTree по ключу (повторный запуск в день не плодит дубли после OPTIMIZE/FINAL-чтения).
- [ ] **Step 2:** Вставка в `run_loop.sh` c гардом «раз в сутки» (маркер-файл или `WHERE NOT EXISTS` по snap_date). Проверить локальный прогон вручную. Commit `feat(data): ежедневный снапшот состояния игрока — задел исторических сегментов`

### Ops (не агентская задача — деплой-чеклист):
- Сменить пароль basic-auth Flask-борда (`rotate_crm_password.sh`, `BOARD_PASS` в `.env` на VPS) — ТЗ п.5.2; текущий засвечен в переписке. SPA не затрагивается (Supabase-auth).
- Роли (ТЗ п.5.1) — УЖЕ ЕСТЬ (14 ролей, Supabase RLS + guard'ы) — в чек-листе приёмки просто зафиксировать соответствие.

---

# ВОЛНА 4 — Этап 3, фаза 3а

> **ДЕТАЛЬНЫЙ ПЛАН: `docs/plans/2026-07-17-etap3-phase3a-plan.md`** (задачи W4-T0…W4-T6 с миграциями, JSON-схемами, контрактами). Каталог фильтров сделан подключаемым: волна стартует БЕЗ файла «для ЦРМ.xlsx» на каталоге v1 (~60 полей из текущих данных); файл домерживается задачей W4-T0. Ниже — краткий скелет для контекста.

**Entry criteria (до запуска волны):** 1) решение PII-режима (рекомендация ТЗ и Соломона: proxy); 2) файл «для ЦРМ.xlsx» или подтверждение каталога v1 (~60 фильтров из текущих данных); 3) справочник бонусов казино (ID+параметры) — для действия «начислить бонус»; 4) подтверждение каналов пилотных брендов.

Фундамент уже есть: `_players_filter` (URL→WHERE, `player_board.py:1015-1040`) — прообраз компилятора сегментов; `SEGMENTS`/RFM/personas — шаблоны для клонирования; `rt_trigger.py` — прообраз real-time входа в цепочку (+ `trigger_log`); `pusher.py` + `CALLBACK_URL/TOKEN` — прообраз исходящих команд; consent/contact-поля в `users` (`schema.sql:32-49`) — для проверок перед отправкой; `expected_gap`(churn-модель) и `rec_bonus`(`player_bonus_ml`) — ML-точки №1 и №2 готовы как данные.

Задачи (каждая станет полноценной задачей отдельного плана после закрытия entry criteria):
1. **0013_segments.sql** — `crm.segments(id, name, sys_name, description, author_id, definition jsonb, is_trigger bool, schedule, archived_at)` + RLS; определение = дерево групп И/ИЛИ (2 уровня) из условий `{field, op, value}` + `not_in_segment`.
2. **api/segments.py** — CRUD + `POST /segments/preview` (компиляция jsonb→CH WHERE по whitelist-каталогу полей; live-счётчик) + экспорт списка (реюз `_export_rows`). Каталог v1: поля `player_features` + ML-таблиц + `users` (разделы 0–6, 9, 10 ТЗ) — реестр в `api/segment_fields.py` (name, type: num/date/enum/flag, sql-expr, раздел).
3. **UI конструктора** — `/segments`: список (+клонирование пресетов из 8 кампаний/RFM/архетипов), редактор групп условий, live-счётчик (debounce 500мс), 4 состояния.
4. **0014_chains.sql + api/chains.py** — цепочки: `chains`, `chain_versions(definition jsonb)`, `chain_enrollments(player, version, node, entered_at, exited_at, exit_reason)`; линейный редактор (вертикальный поток, ТЗ фаза 3а); анти-дубль на enrollment.
5. **chain-runner** — сервис по образцу `rt_trigger.py` (poll live_events + пересчёт сегментов-триггеров): исполняет узлы триггер/действие/условие/ожидание (fixed/dynamic/ML=`expected_gap`-медиана)/сплит/контроль 16%; лог шагов в CH `retention.chain_events` (аналитика вошло/прошло/выпало).
6. **Каналы MVP** — proxy-вебхук `send_message` (формализация pusher: очередь команд + статусы), email SMTP, Telegram-бот (расширение `tg_bot.py`); шаблоны `crm.templates` с `{vars}` и языковыми версиями; проверки перед отправкой (consent-поля + «не в сессии» по live_events + fatigue-счётчик).
7. **Приёмка по DoD ТЗ §6** — включая нагрузочный тест: пересчёт сегмента на 40k, вход 3–5k игроков.

---

# Протокол верификации (оркестратор, после каждой волны)

1. **Сборка/линт:** `cd crm-spa && npm run build && npx eslint . --max-warnings=0` (строгие react-hooks правила — см. memory: set-state-in-effect паттерны).
2. **i18n-аудит:** скрипт-сверка ключей по префиксам новых доменов: каждый ключ ru присутствует в en и tr (по образцу аудита сессии 17.07).
3. **Смоук API:** локальный борд `API_AUTH_OFF=1 ... player_board.py` (memory: команда запуска) + curl всех новых эндпоинтов; сверка чисел: flags.totals ↔ /audit и /affiliates; economics.issued ↔ GGR-бонус-таб.
4. **UI-обход (Playwright MCP):** прокликать 7 модулей, все старые URL из as-is таблицы ТЗ п.1, скриншоты новых экранов; проверить 4 состояния (error — обрубить Flask; empty — фильтр в пустой период).
5. **Роли:** curl новых эндпоинтов под ролью без доступа → 403; UI: пункт меню скрыт.
6. **DoD-чеклист ТЗ п.6 (этапы 1–2)** — прогнать построчно, приложить к отчёту.
7. **Код-ревью:** code-reviewer агент по диффу каждой волны; критичные находки — фикс до следующей волны.

Порядок исполнения: Волна 1 → верификация → Волна 2 (6 задач параллельно, изолировать по файлам; W2-T5 стартует после W1-T1 из-за общего `nav.ts`) → верификация → Волна 3 → финальная приёмка по DoD. Волна 4 (этап 3) — детальный план `2026-07-17-etap3-phase3a-plan.md`. Волна 5 (конструктор отчётов) — детальный план `2026-07-17-report-constructor-plan.md`, зависит только от W3-T1, запускается по команде владельца. Деплой VPS — по чек-листу из memory (миграции 0011+0012 всё ещё не накатаны на прод!).

# Ранбук запуска агентов (для оркестратора)

- Каждая задача = один субагент **Opus 4.8** (`model: "opus"`), тип `general-purpose`. В промпт агента копировать: (1) блок Global Constraints целиком, (2) полный текст его задачи из плана, (3) строку «Дизайн не менять, писать в существующем стиле кода; коммит один, по формату из задачи».
- Параллельность: только задачи без общих файлов. Общие точки конфликта: `nav.ts` и i18n-словари (W1-T1, W2-T2, W2-T3, W2-T4, W2-T5, W4-T2, W4-T5, W5-T4 — все трогают `nav.ts`): пускать последовательно ИЛИ в worktree с ручным мержем nav/i18n. Рекомендуемые пары: {W2-T1 ∥ W2-T6}, {W2-T2 ∥ W2-T3} (у обоих новый api-файл + свой route), потом {W2-T4, W2-T5} последовательно.
- После каждой волны — Протокол верификации выше; находки code-review чинятся ДО следующей волны.
- Волна 4: W4-T1 ∥ W4-T3 → W4-T2 ∥ W4-T4 → W4-T5 → W4-T6. W4-T0 — сразу после получения «для ЦРМ.xlsx».
- Волна 5: W5-T1 ∥ W5-T2 → W5-T3 → W5-T4; W5-T5 — отдельной командой.
- Статусы для владельца: после волны — короткая сводка (что сделано, скриншоты, что проверено, отклонения от плана).
