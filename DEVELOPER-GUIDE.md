# Developer Guide - Revenue Autopilot (retain-lab)

Карта всей системы для нового разработчика: что это, как устроено, где что
лежит, как гонять локально и как не сломать прод. Читать сверху вниз, за час
складывается полная картина.

## Что это за продукт

Retention-автопилот для подписочных SaaS: собирает данные о юзерах клиента
(биллинг, поведение на сайте, события продукта), склеивает личности, скорит
риск ухода и намерение купить, и сам ведёт кампании удержания по каналам
(email / in-app / Telegram / WhatsApp / SMS) с офферами, экономика которых
считается по ИЗМЕРЕННОЙ марже. Эффект доказывается против контрольной группы
(holdout), а не кликами. Прод: https://retivo.digital, первый клиент -
hubcontent.ai (боевой автопилот включён 2026-08-26).

Главный документ мышления - **METHODOLOGY.md**: почему офферы считаются от
себестоимости, кого не трогать, §8 тексты, §8a письма-от-человека, §9 запрет
генерик-промптов. Код обязан ему соответствовать.

## Архитектура одним экраном

```
сайт клиента --snippet/ra.js--> /ingest --Kafka(Redpanda)--> ClickHouse
Stripe --webhook--> stripe-webhook:8082 -----------------------^
экспорт продукта клиента --users_sync/product_sync (poll)------^

ClickHouse (retention.*):  saas_events -> identities -> user_event_features
                           -> user_scores -> user_actions (стадии)
                                |
        saas-ops (ops_loop.py, дирижёр DAG):
          stitch / plans / users_sync / product_sync / scoring /
          campaign_tick (15м) / trigger_tick (1м) / uplift / analyst /
          weekly_digest;  журнал -> pipeline_runs -> экран /pipeline
                                |
        касания: saas_senders (Resend email / in-app inbox / TG / WA / SMS)
                                |
crm-spa (Next.js 16) --/api/v1/*--> board (Flask, api/saas.py) --> ClickHouse
Caddy: / лендинг · /home SPA · /api борд · /ingest · /img статика
```

Все сервисы - docker compose на VPS Hostinger 187.77.157.6
(`docker-compose.yml` + `docker-compose.vps.yml`).

## Репозиторий: что где лежит

| Путь | Что это |
|---|---|
| `stripe_sync/` | ВСЁ ядро (флоские python-джобы). Ключевые: `ops_loop.py` (дирижёр), `campaign_tick.py` (движок кампаний: enroll/execute/exit, лестница каналов, тихие часы, частотный колпак, send-time, A/B, прогрев), `trigger_tick.py` (событийные триггеры T0-T3), `stitch.py` (склейка личностей R1-R5), `scoring.py`+`heuristics.py` (heur-v4: скоры + LTV по измеренной когорте), `economics.py`+`offer_gate.py`+`offer_value.py` (экономика офферов, EV-гейт), `segment.py` (аудитории ручных кампаний), `saas_senders.py`+`email_delivery.py`+`email_template.py` (отправка, подпись §8a), `connectors.py`+`users_sync.py`+`product_sync.py` (источники данных), `wa_personal.py` (WhatsApp QR/WAHA), `llm_stage.py` (единственная дверь к LLM, §9), `ab_winner.py`, `launch_check.py`, `weekly_digest.py` |
| `api/` | Flask-борд: `saas.py` (~95% эндпоинтов: экраны, карточка юзера, кампании, чеклист запуска, дашборд), `public.py` (без auth: inbox виджета, unsubscribe, вебхуки WAHA/Resend), `tenants.py` (создание пространств) |
| `crm-spa/` | Next.js CRM. Экраны: `components/saas/*.tsx` (HomeView - дашборд владельца, UsersView+UserCardView, CampaignsView+CampaignBuilder+LaunchCheck, OffersView, PipelineView, ChannelsView, WaInboxView, InsightsView, LeakAuditView, UpliftView). Словари: `lib/i18n/dictionaries/{en,ru,tr}/saas.ts` |
| `ingest/` | Приём событий сниппета -> Kafka (+гео/UA обогащение, `geo.py`, `ua.py`) |
| `snippet/ra.js` | Клиентский сниппет: 40+ сигналов, identify, in-app виджет (поллинг 90с) |
| `saas_schema.sql` | ВСЯ схема ClickHouse: таблицы, вьюхи (`user_event_features` - фичи одним проходом, `user_actions` - стадии multiIf) |
| `stripe_sync/saas_campaigns.json` | Каркас кампаний K1-K6 + триггеры T0-T3 (_default для всех тенантов) |
| `stripe_sync/tests/` | ~410 pytest. Запуск: `python3 -m pytest stripe_sync/tests/ -q` из корня |
| Доки | `METHODOLOGY.md` (методология), `INTEGRATION-SAAS.md` (интеграция клиента), `ONBOARDING-CLIENT.md` (заведение клиента за 10 мин), `PORT-WHATSAPP-QR.md` (перенос WA), `PRODUCT-BRIEF.md` |

## Как работает конвейер данных (за 2 минуты)

1. События падают в `retention.saas_events` тремя путями: сниппет (source=
   snippet), Stripe-вебхуки (stripe), синк экспорта продукта (product/import).
2. `stitch.py` склеивает в `identities` (по client_user_id / stripe_customer_id
   / email_hash; правило R4: юзер без email получает свою identity).
3. Вьюха `user_event_features` считает ~40 фич ОДНИМ проходом по дедуп-потоку
   (`saas_events_deduped` - вход для ЛЮБЫХ витрин, сырой поток содержит дубли
   пересинков!).
4. `scoring.py` пишет 5 скоров (p_churn/p_convert/ltv/power/buy_intent) +
   `tenant_lifecycle` (измеренный отток когорты, конверсия триала) в knowledge.
5. Вьюха `user_actions` даёт КАЖДОМУ юзеру ровно одну из 7 стадий
   (DUNNING>WINBACK>CONVERT>SAVE>UPGRADE>ACTIVATE>MONITOR) - live, без лага.
6. `campaign_tick` зачисляет по стадиям/гейтам, исполняет шаги со всеми
   предохранителями; `trigger_tick` бьёт по событиям за минуты.
7. Всё меряется: `campaign_send_log`, `offers_issued`, `uplift_reports`
   (target vs holdout), `pipeline_runs` (здоровье), `llm_runs`.

## Доступы

- **Код**: https://github.com/21DoXYZ/retain-lab (private) - попросить у
  владельца invite в collaborators. `git clone` по HTTPS.
- **CRM (прод)**: https://retivo.digital/login - учётку выдаёт владелец
  (или супер-админ создаёт роль в /admin/users; роли от viewer до director).
- **VPS**: только по SSH-ключу у владельца. Разработчику обычно не нужен:
  весь код в репо, все секреты - НЕ в репо (см. ниже).

## Секреты и конфиги (в git их НЕТ)

| Где | Что |
|---|---|
| VPS `/opt/retain-lab/.env` | Ключи платформы: CH_PASSWORD, RESEND, OPENAI, SIGNALS_DRY_RUN (рубильник живых отправок!) |
| VPS `/opt/retain-lab/secrets/tenants.json` | ВСЁ состояние тенанта: ключи Stripe/Resend клиента, email_from + email_identity (подпись §8a), autopilot, users_source, launch_confirms |
| VPS `/opt/retain-lab/secrets/tokens.json` | Ingest-токены (ключ = tenant_id) |
| VPS `/opt/retain-lab/secrets/overrides.json` | Правки текстов из CRM + ручные кампании (M_*) + A/B-победители |

## Локальная разработка

- Python-ядро: правится и тестируется без инфраструктуры -
  `python3 -m pytest stripe_sync/tests/ -q` (чистые функции, FakeCH в тестах).
- SPA: `cd crm-spa && npm i && npm run dev` (порт 3012; .env.local с
  placeholder-ключами уже в репо). `npx tsc --noEmit` перед пушем.
- Полный стек локально НЕ поднимать без нужды (см. SETUP.md) - прод-стек
  живёт на VPS, обкатка джобов - `docker compose exec saas-ops python <job>.py`
  с `TENANT_ID=<тестовый тенант>`. **hubcontent руками не трогать.**

## Деплой

ТОЛЬКО `./deploy.sh <сервисы>` (например `./deploy.sh board saas-ops crm-spa`).
Внутри rsync ОДИН источник на вызов - НИКОГДА не rsync'ить несколько каталогов
одной командой (уже дважды разваливало прод). `site/` и `ops_guard.sh` деплоятся
отдельным rsync/scp. Каталоги `ch_users.d/`, `ch_config.d/` на VPS не трогать -
там серверные секреты.

## Главные ловушки (сэкономят день каждая)

1. Джобы в `stripe_sync/` - ПЛОСКИЕ модули (`from executors import ...`),
   борд импортирует ПАКЕТОМ (`from stripe_sync import ...`). Модуль для обоих
   миров пишется с try/except импортами. `campaign_tick` борду импортировать
   НЕЛЬЗЯ (нужное - дублируется, см. `_ab_stats` и golden-тест хэша).
2. ClickHouse 24.10: алиас не может совпадать с именем колонки агрегата;
   `_current`-вьюхи для JOIN с Replacing-таблицами; makeDate(y,m,1);
   Date-колонки хотят datetime.date.
3. Счётчики - только по `saas_events_deduped`: сырой поток завышает до 11x.
4. Два рубильника отправок: платформенный SIGNALS_DRY_RUN (env) и autopilot
   тенанта. Письмо уходит только когда оба боевые.
5. Тексты: никаких длинных тире (валидатор зарежет), плейсхолдеры только из
   известного набора (fail-closed), письма по стандарту §8a.
6. i18n: любой новый UI-текст - сразу в en+ru+tr словари, иначе ключ на экране.
7. Правки промптов LLM - только с eval-прогоном (`eval_prompts.py`, см.
   память по «мастер-промпты»); генерация без business_context кидает
   MissingContext by design.

## С чего начать разбор (порядок чтения)

1. METHODOLOGY.md - 30 минут, объясняет «почему» всего.
2. `saas_schema.sql` - вьюхи `user_event_features` и `user_actions`.
3. `stripe_sync/campaign_tick.py` - сердце; читать сверху, комментарии
   объясняют каждое решение.
4. `api/saas.py` - по экрану за раз, параллельно щёлкая их в CRM.
5. Экран /pipeline в CRM - живое здоровье всего конвейера.
