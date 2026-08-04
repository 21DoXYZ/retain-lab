# Интеграция: отправка событий казино в Retention Board

Документ для бэкенд-команды казино. Описывает, **как слать нам события игроков** в реальном
времени. Есть два канала на выбор — **HTTP** (проще) и **Kafka** (для больших объёмов).
Оба ведут в один и тот же приёмник, формат события одинаковый.

```
ваш бэкенд ──HTTP POST── ┐
                          ├─► наш приёмник ─► Kafka (буфер) ─► ClickHouse ─► дашборд /live
ваш бэкенд ──Kafka────────┘
```

> 🔐 **Доступы (токен / SASL-пароль) передаются отдельно безопасным каналом, не в этом документе.**

---

## 1. Контракт события (v2)

Одно сообщение = одно событие. JSON. Помимо real-time мониторинга события питают
**ML-модели** (LTV, отток, отклик на бонусы) — поэтому важны профиль игрока, статусы
денежных операций и разметка фриспинов.

**Общие поля (в каждом событии):**

| Поле | Тип | Обяз. | Описание |
|---|---|:--:|---|
| `event_id` | string (uuid) | ✅ | Уникальный id события — по нему **дедупликация**: при ретраях шлите тот же id. |
| `event_type` | string | ✅ | `user` · `bet` · `win` · `session_start` · `session_end` · `deposit` · `withdrawal` · `bonus` |
| `casino_player_id` | int | ✅ | Ваш внутренний числовой id игрока (`users.id`). |
| `ts` | string | ✅ | Время события, **UTC**, `YYYY-MM-DD HH:MM:SS.mmm`. |
| `currency` | string | ⬜ | Напр. `TRY`. |

**Игровые события — `bet` / `win` / `session_start` / `session_end`:**

| Поле | Тип | Описание |
|---|---|---|
| `session_id` | string | id игровой сессии |
| `game_uuid` | string | код игры провайдера |
| `provider` | string | провайдер/агрегатор игры (pragmatic, evolution, …) |
| `bet_amount` | number | сумма ставки (для `bet`) |
| `win_amount` | number | сумма выигрыша (для `win`) |
| `is_freespin` | bool | ставка/выигрыш за счёт фриспинов (бонусные), а не реальных денег |
| `balance_after` | number | баланс после события |

**Денежные события — `deposit` / `withdrawal` / `bonus`:**

| Поле | Тип | Описание |
|---|---|---|
| `amount` | number | сумма операции |
| `status` | string | **обязательно**: `completed` · `rejected` · `failed` · `pending` |
| `payment_method` | string | способ оплаты (papara, havale, …) |
| `is_manual` | bool | ручная операция (оператором) или автоматическая |
| `balance_after` | number | баланс после операции |

**Профиль игрока — `user`** (шлите при регистрации и при изменении профиля; у нас upsert):

| Поле | Тип | Описание |
|---|---|---|
| `account_type` | string | `normal` / `test` / `service` — по нему фильтруются реальные игроки |
| `account_status` | string | статус аккаунта (active/blocked/…) |
| `activity_status` | string | ваш статус активности |
| `is_active` | string | `true`/`false` |
| `country` | string | ISO-код страны |
| `reg_date` | string | дата регистрации (UTC) |
| `ftd_date` / `ftd_amount` | string / number | первый депозит: когда и сколько (null, если не было) |
| `affiliate_code` / `affiliate_type` | string | атрибуция трафика |
| `phone_verified` / `email_verified` | string | `true`/`false` |
| `balance` / `bonus_balance` | number | текущие балансы |
| `last_login` / `last_active` | string | последний вход / последняя активность |

Примеры:
```json
{"event_id":"…uuid…","event_type":"bet","casino_player_id":40,"ts":"2026-06-20 16:30:00.123",
 "session_id":"sess-abc123","game_uuid":"pragmatic/gates-of-olympus","provider":"pragmatic",
 "bet_amount":12.50,"is_freespin":false,"currency":"TRY","balance_after":100.00}
```
```json
{"event_id":"…uuid…","event_type":"deposit","casino_player_id":40,"ts":"2026-06-20 16:31:02.001",
 "amount":250.00,"status":"completed","payment_method":"papara","is_manual":false,
 "currency":"TRY","balance_after":350.00}
```
```json
{"event_id":"…uuid…","event_type":"user","casino_player_id":40,"ts":"2026-06-20 16:29:00.000",
 "account_type":"normal","account_status":"active","is_active":"true","country":"TR",
 "currency":"TRY","reg_date":"2026-01-15 12:00:00.000","ftd_date":"2026-01-16 09:30:00.000",
 "ftd_amount":200.00,"affiliate_code":"aff_gold","affiliate_type":"cpa",
 "phone_verified":"true","email_verified":"true","balance":350.00,"bonus_balance":25.00,
 "last_login":"2026-06-20 16:00:00.000","last_active":"2026-06-20 16:29:00.000"}
```

> Неизвестные вам поля можно опускать — но `status` у денежных операций, `is_freespin`
> у игровых и событие `user` критичны для качества прогнозов.

---

## 2. Канал A — HTTP (рекомендуется для старта)

POST на наш эндпоинт. Можно слать **одно событие** (объект) или **батч** (массив, до 1000).

```
URL:    https://cas.21do.xyz/ingest/events
Метод:  POST
Заголовки:
        Authorization: Bearer <INGEST_TOKEN>   (выдаётся отдельно)
        Content-Type: application/json
Тело:   событие  ИЛИ  массив событий
```

Одно событие:
```bash
curl -X POST https://cas.21do.xyz/ingest/events \
  -H "Authorization: Bearer <INGEST_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"...","event_type":"bet","casino_player_id":40,"ts":"2026-06-20 16:30:00.123","bet_amount":12.5,"currency":"TRY"}'
```

Батч (эффективнее — меньше запросов):
```bash
curl -X POST https://cas.21do.xyz/ingest/events \
  -H "Authorization: Bearer <INGEST_TOKEN>" -H "Content-Type: application/json" \
  -d '[{"event_id":"a",...}, {"event_id":"b",...}]'
```

**Ответы:**
| Код | Значение | Что делать |
|---|---|---|
| `200 {"status":"ok","accepted":N}` | принято и сохранено в буфер | ок |
| `400` | нет обязательных полей / битый JSON | поправить payload (не ретраить как есть) |
| `401` | неверный/нет токена | проверить `Authorization` |
| `413` | батч > 1000 событий | разбить на части |
| `503` | приёмник временно не смог сохранить | **повторить запрос** (с теми же `event_id`) |

> `200` приходит **только** после того, как событие надёжно записано в буфер. Любой не-`200`
> (особенно `503`/таймаут/сетевая ошибка) ⇒ **ретрайте** тот же запрос.

---

## 3. Канал B — Kafka (для больших объёмов / стриминга)

Продюс напрямую в Kafka-совместимый брокер (Redpanda).

```
bootstrap.servers:  cas.21do.xyz:19092
security.protocol:  SASL_SSL          (TLS — Let's Encrypt, ca-файл НЕ нужен)
sasl.mechanism:     SCRAM-SHA-256
sasl.username:      <SASL_USER>        (выдаётся отдельно)
sasl.password:      <SASL_PASS>        (выдаётся отдельно)
topic:              casino.events
key:                casino_player_id   (события игрока -> одна партиция, порядок сохраняется)
value:              JSON события (см. §1)
```

Пример (Python, `confluent-kafka`):
```python
from confluent_kafka import Producer
import json, uuid

p = Producer({
    "bootstrap.servers": "cas.21do.xyz:19092",
    "security.protocol": "SASL_SSL",
    "sasl.mechanism": "SCRAM-SHA-256",
    "sasl.username": "<SASL_USER>",
    "sasl.password": "<SASL_PASS>",
    "enable.idempotence": True,   # без дублей/потерь
    "acks": "all",
})

evt = {"event_id": str(uuid.uuid4()), "event_type": "bet",
       "casino_player_id": 40, "ts": "2026-06-20 16:30:00.123",
       "bet_amount": 12.5, "currency": "TRY"}
p.produce("casino.events", key="40", value=json.dumps(evt))
p.flush()
```

Готовая референс-реализация продюсера — наш проект `casino-event-simulator` (можем прислать).

---

## 4. Требования к доставке (важно для обоих каналов)

1. **`event_id` на каждое событие** (uuid) — у нас включена дедупликация, повторы безопасны.
2. **At-least-once + ретраи.** При ошибке/таймауте — повторить (тот же `event_id`). Лучше дубль, чем потеря.
3. **Локальный буфер / outbox** на вашей стороне — если наш приём недоступен, копить и досылать
   (а не терять). Идеально — писать событие в outbox-таблицу в той же транзакции, что и бизнес-запись.
4. **Время `ts`** — UTC, миллисекунды.
5. **Порядок** (Kafka) — ключ по `casino_player_id`.

---

## 5. Что нам нужно от вас (согласовать перед стартом)

- Какие из 8 типов событий (`user`, `bet`, `win`, `session_start`, `session_end`, `deposit`, `withdrawal`, `bonus`) можете слать? Каких нет?
- Ваш идентификатор игрока == наш `casino_player_id`? Если нет — как маппится?
- Денежные операции: сможете передавать `status` (completed/rejected/failed) и `payment_method`?
- Игровые: сможете размечать `is_freespin` и передавать `provider`?
- Профиль (`user`): шлёте при регистрации и при изменениях (ftd, балансы, статусы)?
- Суммы — в основной валюте или в minor units (копейки)? Сколько знаков?
- Формат `game_uuid` (код игры) с вашей стороны.
- Ожидаемый объём: событий/сек в среднем и на пике.
- С каких **исходящих IP** будете подключаться (добавим в allowlist).
- Нужен ли нам бэкафилл истории, или только поток вперёд?
- Технический контакт и сроки.

---

## 6. Тестовое подключение (первый шаг)

1. Мы выдаём вам тестовые доступы (HTTP-токен и/или SASL-логин).
2. Вы шлёте **5–10 фейковых событий** по контракту (HTTP или Kafka).
3. Мы подтверждаем, что приняли их.
4. После этого подключаете реальный поток.

---

## 7. Бэкфилл истории (разовая выгрузка)

Живой поток покрывает события **с момента включения (T)**. Историю до T присылайте
**дампом** (не через ingest-эндпоинт) — она грузится в аналитические таблицы, на которых
обучаются модели.

- **Период:** с `2026-06-04 00:00` (конец наших текущих данных) до T. Перекрытие в
  несколько часов не страшно — дубли уберём.
- **Состав:** транзакции за период (`money_transactions`, `game_transactions`,
  `game_sessions`) + **полный свежий снапшот `users`**.
- **Формат:** Parquet (предпочтительно) или CSV, структура — как в первой выгрузке.
- **Порядок против «дырки»:** сначала включаем живой поток (фиксируем T) → затем
  присылаете дамп `[2026-06-04 → T]` → мы заливаем и пересчитываем модели.

---

## 8. Сигналы модели — обратный канал (мы → вы)

Отдельный этап (включается после согласования формата и получения callback-токена).
Мы POST'им предсказания моделей на ваш эндпоинт, вы триггерите бонусы/CRM.

```
POST   https://billionbahis.com/api/retention-board/signals
GET    https://billionbahis.com/api/retention-board/health   (проверка перед отправкой)
Заголовок: Authorization: Bearer <RETENTION_BOARD_CALLBACK_TOKEN>   (генерируете вы)
Тело:   батч сигналов (JSON)
```

Конверт:
```json
{
  "model_version": "2026-06-20",
  "scored_at": "2026-06-20 14:37:00",
  "signals": [
    {
      "casino_player_id": 40,
      "pred_ltv_d90": 12345.60,
      "p_churn_30d": 0.87,
      "p_next_deposit": 0.42,
      "ltv_tier": "D",
      "recommended_action": "SAVE",
      "recommended_bonus": "cashback",
      "priority": 9876
    }
  ]
}
```

Поля сигнала:
| Поле | Тип | Смысл |
|---|---|---|
| `casino_player_id` | int | ваш `users.id` |
| `pred_ltv_d90` | number (TRY) | прогноз депозитов за след. 90 дней |
| `p_churn_30d` | number 0..1 / null | вероятность оттока в 30 дней |
| `p_next_deposit` | number 0..1 / null | вероятность следующего депозита |
| `ltv_tier` | string / null | ценностный тир `A`/`B`/`C`/`D` (D = кит) |
| `recommended_action` | string | enum: `CONVERT` · `NUDGE` · `SAVE` · `WINBACK` · `NURTURE` · `MONITOR` |
| `recommended_bonus` | string | enum: `first_deposit_bonus` · `second_deposit_reload` · `reload_cashback` · `vip_offer` · `freespins` · `other` |
| `priority` | int | приоритет (больше = важнее) |

Все значения — стабильные машиночитаемые коды (ASCII), можно матчить программно.

**Доставка:** at-least-once, батчами; идемпотентность по `casino_player_id` в рамках одного
`scored_at` (берите последний по времени). `RETENTION_BOARD_CALLBACK_TOKEN` генерируете вы
(защита вашего эндпоинта) и передаёте нам.
