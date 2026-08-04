# Установка с нуля (сервер или новая машина)

Полная сборка дашборда из этого репозитория: ClickHouse → схема → данные → витрина → веб-морда.

> ⚠️ Данные (CSV с PII) в репозитории отсутствуют. Их заливаешь сам — из своего
> локального ClickHouse (рекомендуется) или из CSV-выгрузок.

---

## 0. Что нужно на сервере
- Linux (Ubuntu/Debian — примеры ниже) или macOS
- ~30–40 ГБ диска (исходные таблицы ~15 ГБ + индексы/витрина)
- Python 3.10+
- SSH-доступ

---

## 1. Установить и запустить ClickHouse (на сервере)

```bash
# Debian/Ubuntu
curl https://clickhouse.com/ | sh
sudo ./clickhouse install            # ставит clickhouse-server + clickhouse-client
sudo clickhouse start                # запустить сервер

# проверка
clickhouse client -q "SELECT version()"
```
По умолчанию слушает `127.0.0.1` (HTTP 8123, native 9000) — это правильно, наружу не открываем.

---

## 2. Склонировать репозиторий

```bash
git clone https://github.com/21DoXYZ/retention-board.git
cd retention-board
```

---

## 3. Создать схему (база + 4 таблицы)

```bash
clickhouse client --multiquery < schema.sql
```
Создаёт базу `retention` и пустые таблицы: `users`, `money_transactions`,
`game_transactions`, `game_sessions`.

---

## 4. Залить данные — два пути

### Путь А (рекомендуется): из твоего ЛОКАЛЬНОГО ClickHouse → на сервер
Запускать **на локальной машине** (где данные уже есть). Один скрипт сделает всё —
схему, перенос 4 таблиц напрямую (Native, без CSV) и сборку витрины:

```bash
./migrate_to_server.sh user@server
```
Большой `game_transactions` (~15 ГБ) идёт через gzip по SSH. На медленном канале — долго,
но надёжно. (Скрипт уже вызывает schema.sql и player_features.sql на сервере — шаги 3 и 5
делать вручную не нужно.)

### Путь Б: из CSV-выгрузок (если переносишь файлами)
Положи CSV рядом и залей (заголовок в файле → `CSVWithNames` матчит колонки по имени):

```bash
for t in users money_transactions game_sessions game_transactions; do
  clickhouse client -q "INSERT INTO retention.$t FORMAT CSVWithNames" \
    < retention_${t}_*.csv
done
```

---

## 5. Собрать витрину player_features
(если шёл путём Б — выполнить вручную; путь А уже сделал)

```bash
clickhouse client --multiquery < player_features.sql
# проверка
clickhouse client -q "SELECT count() FROM retention.player_features"   # ~39130
```

---

## 5b. Аналитический слой — вьюхи + ML-таблицы + производные данные

```bash
clickhouse client --multiquery < marts.sql      # ~1 мин (внутри тяжёлый джойн для bonus_effectiveness_t)
# проверка: 4 базовые + player_features + player_games + 8 ML/опер.таблиц + 10 вьюх
clickhouse client -q "SELECT count() FROM system.tables WHERE database='retention'"   # ~24
clickhouse client -q "SELECT count() FROM retention.player_games"                      # ~152130
```
Создаёт все вьюхи (`player_actions`, `player_ltv`, `deposit_ladder`, `ltv_deciles`, …), наполняет
`player_games` и `bonus_effectiveness_t`, и создаёт ПУСТЫЕ ML-таблицы (наполнит шаг 5c).
**Обязательно после `player_features.sql`** — вьюхи на неё ссылаются.

---

## 5c. Наполнить ML-таблицы — два пути

Без этого шага страницы `/ltv /actions /desk /live /funnel /bonus /dist` будут пустыми.
ML-таблицы — выход моделей; модели **не хранятся в файлах**, их результат живёт только
строками в ClickHouse. На новый сервер их можно либо переобучить (Путь А), либо перенести
готовыми (Путь Б — быстрее и без тяжёлого ML-стека).

### Путь А: обучить на этом сервере
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-ml.txt        # catboost, scikit-learn, pandas, numpy, scipy
./train_all.sh                            # обучает 6 моделей по порядку, ~5–10 мин
```
Скрипты подключаются к ClickHouse через env (по умолчанию `127.0.0.1:8123`, без пароля):
`CH_HOST CH_PORT CH_USER CH_PASSWORD CH_DB`. Если ClickHouse с паролем/на другом хосте — задай их.
Повторный запуск безопасен (модели переобучаются — ставь в cron для обновления).
⚠️ `churn_model.py` использует фиксированные даты срезов (`T_TRAIN/T_TEST`) — по мере роста данных их правят.
⚠️ Нужен CatBoost + RAM/CPU. На слабом VPS обучение может уйти в OOM — тогда выбирай Путь Б.

### Путь Б: перенести уже обученные таблицы (без CatBoost на сервере)
Где данные модели уже обучены (твоя локальная машина) — снять дамп 7 ML-таблиц и залить на сервер.
Таблицы крошечные (~1 МБ суммарно), переобучение и ML-зависимости на сервере НЕ нужны.
```bash
# 1) на машине-источнике (где ClickHouse с обученными таблицами):
./dump_ml_tables.sh                                    # → каталог ml_dump/ (DDL + Native)

# 2) перенести на сервер:
scp -r ml_dump/ user@server:/path/retention-board/

# 3) на сервере (ПОСЛЕ шагов 5b marts.sql):
./restore_ml_tables.sh                                 # DROP+CREATE+INSERT 7 таблиц
```
Оба скрипта читают конфиг CH из тех же env (`CH_HOST CH_PORT CH_DB CH_USER CH_PASSWORD`).
`restore` ретаргетит БД и идемпотентен (повторный запуск перезатирает). Round-trip проверен 1:1.
`ml_dump/` в `.gitignore` — содержит предсказания по `casino_player_id`, в репозиторий не коммитим.

---

## 6. Поднять веб-морду (дашборд)

> Сначала должны быть выполнены шаги 5b (marts.sql) и 5c (модели) — иначе ML-страницы пустые.

```bash
# venv уже создан в 5c; борду хватает requirements.txt (flask, clickhouse-connect, markupsafe)
source .venv/bin/activate
pip install -r requirements.txt
python player_board.py            # → http://127.0.0.1:8050
```

---

## 7. Доступ к дашборду (БЕЗОПАСНО — обязательно прочитать)

Дашборд показывает **PII** (email/phone/payment_details) и по умолчанию **без авторизации**
(`BOARD_USER` пуст → auth выключена). Единственное, что отделяет PII от интернета — бинд на
`127.0.0.1` И фаервол. Нужны ОБА.

**7.1 Фаервол — закрыть всё кроме SSH (обязательно на публичном VPS):**
```bash
sudo ufw default deny incoming
sudo ufw allow OpenSSH
sudo ufw enable
# НЕ открывать 8050 / 8123 / 9000 наружу. На облаке — то же в security group.
```

**7.2 Пароль ClickHouse** (по умолчанию пользователь `default` без пароля):
```bash
# задать пароль и передавать борду/скриптам через env CH_PASSWORD
clickhouse client -q "SELECT * FROM system.server_settings WHERE name='listen_host'"  # должно быть loopback
```

**7.3 Доступ — два варианта:**

*Вариант А (просто и безопасно) — SSH-туннель:*
```bash
ssh -L 8050:localhost:8050 user@server      # http://localhost:8050 у себя
```
SSH-хардненинг: ключи вместо паролей (`PasswordAuthentication no`), желательно не из-под root.

*Вариант Б (доступ команде) — basic-auth борда + TLS-прокси:*
```bash
# 1) включить auth борда: .env → BOARD_USER=... BOARD_PASS=...
# 2) Caddy перед бордом (авто-TLS), апстрим строго на loopback:
#    Caddyfile:
#      board.example.com {
#        basicauth { teamuser JDJ... }   # хеш: caddy hash-password
#        reverse_proxy 127.0.0.1:8050
#      }
# ClickHouse (8123/9000) ЗА прокси НИКОГДА не выставлять.
```
basic-auth поверх HTTP — открытый текст, всегда только с TLS-прокси.

---

## 7b. CRM-SPA (crm-spa/) — ОСНОВНОЙ интерфейс

**SPA — единственный рабочий интерфейс.** HTML-страницы старого борда (шаг 6) выведены из
эксплуатации: всё, что они показывали, есть в SPA (список с фильтрами сегментов/игр/аффилиатов,
карточка игрока с подсказками, экран расследования выводов `/audit` → оператор, «что делать
сейчас» на `/live`, экспорты и т.д.). Проверять паритет по HTML-борду больше не нужно.

Процесс `player_board.py` при этом **остаётся жить — но как headless-API**: SPA ходит в него
по HTTP за аналитикой (`/api/v1/*`, там же все выверенные формулы GGR/NGR/LTV и ML-скоры) и
напрямую в Supabase за операционными данными (заметки, звонки, назначения). Формулы НЕ
дублируются в TS — один источник, одни цифры.

> ⚠️ **Безопасность при выносе борда наружу.** `/api/*` защищён Supabase-JWT (по ролям), а вот
> legacy HTML-страницы борда — только basic-auth (`BOARD_USER`/`BOARD_PASS`) и показывают PII.
> Если выставляешь хост борда для API SPA (`board.example.com`, §7b ниже) — обязательно задай
> `BOARD_USER`/`BOARD_PASS`, иначе HTML-страницы с PII окажутся открыты. Идеально — вообще не
> отдавать HTML наружу (прокси пропускает только `/api/`).

```bash
cd crm-spa
npm ci
npm run build
npm run start                     # → http://127.0.0.1:3000
```

**Переменные окружения SPA** (`crm-spa/.env.local`, файл в .gitignore — создать руками):

| переменная | пример | зачем |
|---|---|---|
| `NEXT_PUBLIC_FLASK_API_URL` | `https://board.example.com` | адрес борда, куда SPA шлёт запросы из браузера |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xxx.supabase.co` | проект Supabase |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `eyJ...` | публичный ключ (RLS защищает данные) |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJ...` | **только сервер**, НИКОГДА не с префиксом `NEXT_PUBLIC_` |

**Переменная борда, без которой SPA не заработает:**

```bash
# .env борда (или EnvironmentFile в systemd, шаг 8)
CORS_ORIGINS=https://crm.example.com          # ← ДОМЕН SPA, через запятую если их несколько
```

> ⚠️ **Частая ловушка.** `NEXT_PUBLIC_FLASK_API_URL` и `CORS_ORIGINS` — парные: запросы идут
> **из браузера**, поэтому борд обязан явно разрешить домен SPA. Не задашь `CORS_ORIGINS` —
> борд разрешит только `http://localhost:3000` (дефолт для разработки), и на VPS браузер
> зарежет **каждый** запрос преполётом. Симптом обманчивый: бэкенд жив и по curl отвечает,
> а все экраны SPA показывают ошибку загрузки. Смотри лог борда при старте — он печатает
> `api: CORS разрешён для: ...`.

Оба сервиса за одним TLS-прокси (Caddy из 7.3): `crm.example.com` → 3000, `board.example.com`
→ 8050. Наружу — только 80/443; 3000/8050/8123/9000 остаются на loopback.

---

## 7c. Call Analyzer — анализ звонков колл-центра

Модуль «Анализ звонков» (спеки `call_analyzer_dev_spec.md` + `call_analyzer_interface_spec_FINAL.md`):
запись из звонилки → распознавание турецкой речи → оценка по рубрике → экраны в SPA
(раздел «Анализ звонков»: обзор, очередь проверки, карточка звонка, покрытие, сводка…).

**Шаг 1 — миграции Supabase** (обе обязательны, применяются к боевой базе):

```bash
psql "$SUPABASE_DB_URL" -f supabase/migrations/0007_call_analyzer.sql        # схема analyzer + роль translation_reviewer
psql "$SUPABASE_DB_URL" -f supabase/migrations/0008_call_recommendations.sql # фиксация рекомендаций «когда звонить»
psql "$SUPABASE_DB_URL" -f supabase/migrations/0009_translation_check_fix.sql # очередь проверки перевода
psql "$SUPABASE_DB_URL" -f supabase/migrations/0010_script_groups.sql       # A/B: разные скрипты разным группам операторов
```

> ⚠️ Схему `analyzer` НЕ добавлять в exposed schemas PostgREST — браузер туда не ходит,
> читает только Flask. Это осознанная граница: транскрипты содержат речь игроков
> (уже редактированную от PII), поверхность доступа держим минимальной.

**Шаг 2 — портальный API** уже внутри борда (`api/call_analysis.py`, авто-регистрация).
Отдельно поднимать не нужно — только задать env для связи с пайплайном (ниже).

**Шаг 3 — пайплайн-сервис** (три docker-контейнера):

```bash
docker compose up -d redis analyzer-api analyzer-worker analyzer-beat
```

**Переменные окружения** (в `.env` борда/анализатора):

| переменная | обяз. | что |
|---|---|---|
| `OPENROUTER_API_KEY` | да | LLM-оценка + переводы (Gemini 3 Flash, fallback Qwen — не Anthropic) |
| `GLADIA_API_KEY` | да | распознавание турецкой речи |
| `ASR_PROVIDER` | да | `gladia` в бою; `mock` для проверки без ключей |
| `ANALYZER_SERVICE_TOKEN` | да | внутренний токен (`openssl rand -hex 32`); ОДИН и тот же у борда и пайплайна |
| `ANALYZER_URL` | да | адрес пайплайна для борда — в docker `http://analyzer-api:8090` |
| `REDIS_URL` | авто | брокер очереди (в compose уже прописан) |
| `SUPABASE_DB_URL`, `CH_*` | те же | что у борда |

> **Turnkey** (как звонилка). Без `OPENROUTER_API_KEY`/`GLADIA_API_KEY` контейнеры
> поднимутся, но на обработке звонка отдадут понятный `ConfigError`. Вставил ключи →
> заработало, код не трогать. Покупных ключа два: OpenRouter и Gladia (у Gladia есть
> бесплатные 10 ч/мес на пробу); `ANALYZER_SERVICE_TOKEN` — просто своя строка.

**Как оживает.** Оператор звонит через Tegsoft → вебхук пишет звонок в `crm.calls`
(с `recording_ref`) → пайплайн каждые 60с забирает дозвоны с записями, качает аудио
у Tegsoft, распознаёт, оценивает → экраны «Анализ звонков» в SPA наполняются. До
ключей модуль показывает пустые экраны с честным «0 дозвонов» — ничего не падает.

**Тест пайплайна** (без внешних ключей, нужен только локальный Postgres):

```bash
ASR_PROVIDER=mock SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres \
  .venv/bin/python call_analyzer/test_analyzer.py     # 29 passed
```

---

## 8. (Опц.) Автозапуск через systemd

```ini
# /etc/systemd/system/retention-board.service
[Unit]
Description=Retention Board
After=clickhouse-server.service

[Service]
WorkingDirectory=/home/user/retention-board
# креды в файле с правами 600 (BOARD_USER/BOARD_PASS включают basic-auth, CH_PASSWORD — пароль ClickHouse)
EnvironmentFile=/etc/retention-board.env
ExecStart=/home/user/retention-board/.venv/bin/python player_board.py
Restart=on-failure
User=user

[Install]
WantedBy=multi-user.target
```
```bash
sudo install -m600 /dev/stdin /etc/retention-board.env <<'ENV'
BOARD_USER=team
BOARD_PASS=смени-меня
CH_PASSWORD=
ENV
sudo systemctl enable --now retention-board
```
Без `EnvironmentFile` борд поднимется **без авторизации** — тогда доступ только через SSH-туннель (§7.3 А).

---

## Чек-лист
- [ ] ClickHouse запущен (`SELECT version()`)
- [ ] `schema.sql` применён (4 таблицы)
- [ ] Данные залиты (путь А или Б)
- [ ] `player_features` собрана (~39130 строк)
- [ ] **`marts.sql` применён** (≈24 объекта; `player_games` ~152130 строк, `bonus_effectiveness_t` непустая)
- [ ] **ML-таблицы наполнены** — обучены (`./train_all.sh`) ИЛИ перенесены (`./restore_ml_tables.sh`): `player_ltv_ml`, `player_ltv_quantiles`, `player_repeat_ml`, `player_churn_ml`, `player_next_deposit_ml`, `player_bonus_ml`, `bonus_uplift` непустые
- [ ] `pip install -r requirements.txt` (борд) + `requirements-ml.txt` (обучение)
- [ ] `python player_board.py` → 8050, ML-страницы (/ltv /actions /desk /live) с данными
- [ ] **Фаервол включён** (ufw: только SSH; 8050/8123/9000 наружу закрыты)
- [ ] Доступ через SSH-туннель, либо basic-auth борда + TLS-прокси (§7)
- [ ] **CRM-SPA** (§7b): `npm ci && npm run build`, `.env.local` заполнен, `SUPABASE_SERVICE_ROLE_KEY` БЕЗ префикса `NEXT_PUBLIC_`
- [ ] **`CORS_ORIGINS` борда = домен SPA** — иначе браузер зарежет все запросы, хотя curl отвечает (§7b)
- [ ] **Call Analyzer** (§7c): миграции 0007+0008 применены; `analyzer` НЕ в exposed schemas; `docker compose up -d redis analyzer-api analyzer-worker analyzer-beat`; ключи OpenRouter/Gladia + `ANALYZER_SERVICE_TOKEN` в `.env` (без них — пустые экраны, не падение)

## Обновление (refresh)
Данные дозалиты → `player_features.sql` пересобрать → `clickhouse client --multiquery < marts.sql`
(пересчитает `player_games`/`bonus_effectiveness_t`) → `./train_all.sh` (переобучит модели)
**или** `./restore_ml_tables.sh` (залить свежий дамп, если модели обучаешь не на этом сервере).
Можно в cron. По мере роста данных править даты срезов в `churn_model.py`.
