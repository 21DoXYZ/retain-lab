# Retention Board

Локальный аналитический стек для анализа удержания игроков казино: **ClickHouse + Flask-дашборд**.
Всё работает локально (`127.0.0.1`) — сырые данные не покидают машину.

> ⚠️ **Приватность:** сырые выгрузки (CSV с PII — email/phone/payment_details) и скриншоты
> **не включены** в репозиторий (см. `.gitignore`). Здесь только код веб-морды и SQL/доки.

📖 **Установка с нуля (ClickHouse + схема + перенос данных) → [SETUP.md](SETUP.md)**
Перенос данных из локального ClickHouse на сервер: `./migrate_to_server.sh user@server`

🏗️ **Куда это развивается (сервинг ML, приём данных, real-time трекинг) → [ARCHITECTURE.md](ARCHITECTURE.md)** — живой документ, тут думаем «как и что» дальше.

## Что внутри
| Файл | Назначение |
|---|---|
| `player_board.py` | Flask-дашборд: Пульт · Играют сейчас · Игроки · LTV · Распределения · Воронка · Действия · Бонусы · Отчёт — live из ClickHouse |
| `schema.sql` | DDL: база `retention` + 4 исходные таблицы |
| `player_features.sql` | Витрина `player_features` (1 строка = игрок, ~66 фич) |
| `marts.sql` | Аналитический слой: 10 вьюх + ML-таблицы + `player_games`/`bonus_effectiveness_t` |
| `*_model.py` · `train_all.sh` | 6 CatBoost-моделей (LTV, квантили, P(2-й деп), churn, прогрессия депозитов, бонус-отклик) + раннер |
| `requirements.txt` · `requirements-ml.txt` | Зависимости борда · зависимости обучения моделей |
| `analytics_queries.sql` · `COHORTS.md` | Аналитика и справочник ~38 когорт |
| `ML_PLAN.md` · `DESIGN.md` | План ML-моделей · дизайн-система |
| `ARCHITECTURE.md` | Системная архитектура: сервинг ML, приём данных, real-time трекинг (текущее vs целевое) |
| `dump_ml_tables.sh` · `restore_ml_tables.sh` | Перенос обученных ML-таблиц между серверами без переобучения |
| `SETUP.md` | Установка с нуля (ClickHouse → данные → запуск) |
| `Dockerfile` · `docker-compose.yml` | Контейнеризация (CH + дашборд одной командой) |
| `migrate_to_server.sh` | Перенос данных local→server ClickHouse по SSH |
| `vendor/` | ECharts (локально, без CDN) |

## Данные (4 таблицы, база `retention`)
`users` · `money_transactions` · `game_transactions` · `game_sessions` — связь по `casino_player_id`.
CSV-выгрузки в репо **отсутствуют** — заливаются локально (см. [SETUP.md](SETUP.md)).

## Быстрый старт — Docker (рекомендуется)
```bash
docker compose up -d --build          # ClickHouse (схема создастся сама) + дашборд
# залить данные (см. SETUP.md), затем витрина → аналитический слой:
docker compose exec -T clickhouse clickhouse client --multiquery < player_features.sql
docker compose exec -T clickhouse clickhouse client --multiquery < marts.sql
# обучить модели (с хоста, ClickHouse доступен на 127.0.0.1:8123):
pip install -r requirements-ml.txt && CH_HOST=127.0.0.1 CH_PORT=8123 ./train_all.sh
# дашборд: http://127.0.0.1:8050
```
Basic-auth: создай `.env` с `BOARD_USER=...` и `BOARD_PASS=...` (пусто = без авторизации).

## Быстрый старт — без Docker
```bash
clickhouse client --multiquery < schema.sql            # схема (4 таблицы)
#   … залить данные (см. SETUP.md) …
clickhouse client --multiquery < player_features.sql   # витрина
clickhouse client --multiquery < marts.sql             # вьюхи + ML-таблицы + player_games
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ml.txt && ./train_all.sh   # обучить 6 моделей (наполнить ML-таблицы)
pip install -r requirements.txt
python player_board.py                                 # → http://127.0.0.1:8050
```
> Полная пошаговая инструкция (включая безопасность VPS) — **[SETUP.md](SETUP.md)**.

## ⚠️ Безопасность (критично)
Дашборд **без авторизации** и показывает **PII игроков**. На сервере:
- держи его на `127.0.0.1` (так по умолчанию) — **порт 8050 наружу НЕ открывать**;
- заходи **только через SSH-туннель**: `ssh -L 8050:localhost:8050 user@server` → `http://localhost:8050`;
- нужен общий доступ → включи basic-auth (`BOARD_USER`/`BOARD_PASS`) + HTTPS-прокси (nginx/Caddy).

## Разделы дашборда
- **Обзор** — KPI по реальным игрокам (депозиты, кэш-нетто, GGR, RTP)
- **Игроки** — список с фильтрами + карточка игрока (профиль, деньги, игра, ритм ставок, траектория)
- **Аналитика / Когорты** — 36 срезов базы (ECharts)
- **Аудит выводов** — ручные списания (бонус-клобэки), кто проводил, аномалии
