# 🎰 COHORTS — памятка по сегментации игроков

Справочник всех когорт/сегментов, на которые можно резать базу `retention` (ClickHouse).
Для каждой когорты: **какие колонки**, **как считать**, **что реально в данных** (с цифрами),
**годность** и **готовый SQL**.

- **Датасет:** база `retention` · 4 таблицы · период **2025-12-01 → 2026-06-04** · валюта **TRY**
- **Население:** 39 130 аккаунтов, из них **39 010 real** (`account_type='normal'`), играли **27 977**, депозиторов **3 537** (8.6%)
- **«Клей»:** `casino_player_id` есть во всех 4 таблицах · доп-связь `game_transactions.session_id → game_sessions.session_id`
- **Время:** хранится в UTC → для турецких суток оборачивай `toTimezone(created_at,'Europe/Istanbul')`
- **Privacy:** все запросы — агрегаты; PII-колонки (`email,phone,username,telegram_*,payment_details`) в признаки не брать
- **Базовый фильтр:** `account_type='normal'` (исключает test/service/blocked)

---

## Оглавление (быстрый выбор оси)

| # | Когорта | Ось | Ключевые колонки | Годность |
|---|---|---|---|---|
| 1 | Неделя/месяц регистрации | время | `reg_date` | ✅ |
| 2 | Когорта первой ставки | время | `game_transactions.created_at` | ✅ |
| 3 | Когорта первого депозита | время | `ftd_date` | ✅ (8.6%) |
| 3a | Возраст аккаунта (tenure) | время | `reg_date` | ✅ |
| 3b | Скорость активации | время | `reg_date`,`ftd_date`, first bet | ✅ |
| 4 | Тип аффилиата | канал | `affiliate_account_type` | ✅ |
| 5 | Аффилиат | канал | `affiliate_code` | ✅ (122) |
| 6 | Лендинг/источник | канал | `registration_source`,`traffic_link_code` | ⚠️ грязно |
| 7 | Бонус-кампания | канал | `payment_method` (`campaign:*`) | ✅ |
| 8 | Депозитор vs нет | деньги | `ftd_date` | ✅ топ |
| 9 | Тир FTD | деньги | `ftd_amount` | ✅ |
| 10 | Кол-во депозитов | деньги | `money_transactions` | ✅ |
| 11 | Способ оплаты | деньги | `payment_method` | ✅ |
| 12 | Платёжное трение | деньги | `money_transactions.status` | ✅ сигнал |
| 13 | Winner / Loser | деньги | `bet_amount`,`win_amount` | ✅ |
| 14 | Value-тир (GGR) | деньги | оборот/net | ✅ |
| 14a | Поведение выводов | деньги | `money_transactions` withdrawal | ✅ |
| 14b | Состояние баланса | деньги | `balance`,`bonus_balance` | ✅ |
| 15 | Активных дней | вовлечённость | `game_transactions.created_at` | ✅ топ |
| 16 | Кол-во ставок | вовлечённость | `transaction_type` | ✅ |
| 17 | Средняя ставка | вовлечённость | `bet_amount` | ✅ |
| 18 | Бонусник vs реал | вовлечённость | `transaction_type` | ✅ |
| 19 | Сессии / частота | вовлечённость | `game_sessions` | ✅ |
| 19a | Интенсивность ставок | вовлечённость | bets / active_day | ✅ |
| 19b | Время игры (час/день) | вовлечённость | `created_at` | ✅ |
| 20 | Разнообразие игр | игра | `game_uuid` | ✅ |
| 21 | Хиты vs нишевые | игра | `game_uuid` | ✅ |
| 22 | Провайдер | игра | `aggregator` | ⚠️ |
| 23 | Любимая игра / кластеры | игра | `game_uuid` | ✅ (без имён) |
| 24 | Recency-стадия | цикл | last bet | ✅ топ |
| 25 | activity_status (готовое) | цикл | `activity_status` | ✅ |
| 26 | Стадия активации | цикл | played/sessions | ✅ |
| 26a | Реактивация / win-back | цикл | gaps между днями | ✅ |
| 27 | **RFM** | композит | R+F+M | ✅✅ главный |
| 28 | Value × Lifecycle | композит | net × recency | ✅ |
| 29 | VIP под риском | композит | depositor×stake×recency | ✅ |
| 29a | Канал × удержание | композит | affiliate × retention | ✅ |

> **Не годится** (одно значение/пусто): страна (все TR), device (всё desktop), mode (всё real), валюта, таймзона, верификация (98.5% одинаково), RG/self_excluded/risk_tags (пусто), контактность (пусто), **названия игр** (0.2% ставок). См. приложение.

---

## Формат карточки

```
### N. Название (industry term)
- Вопрос     — что решает
- Колонки    — точные table.column
- Логика     — как считать
- В данных   — реальное распределение
- Годность   — ✅/⚠️/❌
- Применение — churn-признак / реко / кампания / отчёт
- SQL        — готовый запрос
```

---

# A. ВРЕМЯ / ПРИВЛЕЧЕНИЕ

### 1. Когорта недели/месяца регистрации (Acquisition cohort)
- **Вопрос:** качество трафика по периоду набора
- **Колонки:** `users.reg_date`, `casino_player_id`
- **Логика:** `toMonday(reg_date)` или `toStartOfMonth(reg_date)`
- **В данных:** регистрации шли дек 2025 → июнь 2026; пик активности игроков — март
- **Годность:** ✅
- **Применение:** отчёт, основа retention-когорт
```sql
SELECT toStartOfMonth(toTimezone(reg_date,'Europe/Istanbul')) AS cohort_month, count() AS players
FROM retention.users WHERE account_type='normal' AND reg_date IS NOT NULL
GROUP BY cohort_month ORDER BY cohort_month;
```

### 2. Когорта первой ставки (Activity / first-play cohort)
- **Вопрос:** удержание тех, кто реально начал играть (без «мёртвых» регистраций)
- **Колонки:** `game_transactions.created_at`, `casino_player_id`
- **Логика:** `min(toMonday(created_at))` на игрока = неделя активации
- **В данных:** база активированных 27 977
- **Годность:** ✅ (чище, чем регистрационная — нет неигравших)
- **Применение:** retention-кривые, отчёт
```sql
WITH act AS (SELECT casino_player_id, min(toMonday(toTimezone(created_at,'Europe/Istanbul'))) AS fw
  FROM retention.game_transactions WHERE transaction_type IN ('bet','freespins_bet') GROUP BY casino_player_id)
SELECT fw AS first_week, count() AS players FROM act GROUP BY fw ORDER BY fw;
```

### 3. Когорта первого депозита (FTD cohort)
- **Вопрос:** удержание/качество плательщиков по дате FTD
- **Колонки:** `users.ftd_date`, `ftd_amount`
- **Логика:** `toMonday(ftd_date)`
- **В данных:** только 3 537 депозиторов (8.6%)
- **Годность:** ✅ (но малая база)
- **Применение:** отчёт, LTV-когорты
```sql
SELECT toMonday(toTimezone(ftd_date,'Europe/Istanbul')) AS ftd_week, count() AS depositors, round(avg(ftd_amount),0) AS avg_ftd
FROM retention.users WHERE account_type='normal' AND ftd_date IS NOT NULL GROUP BY ftd_week ORDER BY ftd_week;
```

### 3a. Возраст аккаунта / Tenure
- **Вопрос:** новый игрок или старый (разная тактика удержания)
- **Колонки:** `users.reg_date`
- **Логика:** `today − reg_date` → бакеты
- **В данных:** ≤7д 415 · 8-30д 2 036 · 31-90д 14 654 · 91-180д **21 397** · 180д+ 508
- **Годность:** ✅
- **Применение:** кампания (онбординг новых), отчёт
```sql
SELECT multiIf(d<=7,'≤7д',d<=30,'8-30д',d<=90,'31-90д',d<=180,'91-180д','180д+') AS tenure, count() players
FROM (SELECT dateDiff('day', toDate(reg_date), today()) d FROM retention.users WHERE account_type='normal' AND reg_date IS NOT NULL)
GROUP BY tenure ORDER BY min(d);
```

### 3b. Скорость активации (Time-to-activate)
- **Вопрос:** как быстро от регистрации до игры/депозита
- **Колонки:** `users.reg_date`, `ftd_date`, `min(game_transactions.created_at)`
- **Логика:** лаг в днях `reg → первая ставка` и `reg → ftd`
- **В данных:** **80% играют в день регистрации** (медиана лага = 0; 22 506 из 27 977 same-day). Остальные — отложенный старт
- **Годность:** ✅ (мгновенный vs отложенный = разный профиль риска)
- **Применение:** churn-признак, кампания на «зарегался, но не играет»
```sql
WITH fb AS (SELECT casino_player_id, min(toDate(created_at)) fbd FROM retention.game_transactions GROUP BY casino_player_id)
SELECT multiIf(lag=0,'в день рег',lag<=1,'1 день',lag<=7,'2-7 дней','8+ дней') seg, count() players
FROM (SELECT dateDiff('day', toDate(u.reg_date), fb.fbd) lag FROM retention.users u JOIN fb USING(casino_player_id)
      WHERE u.account_type='normal' AND u.reg_date IS NOT NULL)
GROUP BY seg ORDER BY min(lag);
```

---

# B. КАНАЛ ПРИВЛЕЧЕНИЯ

### 4. Тип аффилиата (Affiliate type)
- **Вопрос:** через какой тип партнёра пришёл
- **Колонки:** `users.affiliate_account_type`
- **Логика:** GROUP BY значения
- **В данных:** classic **30 212 (77%)** · нет 8 229 (21%) · media_buyer 569 (1.5%)
- **Годность:** ✅
- **Применение:** отчёт по каналам, churn-признак
```sql
SELECT if(affiliate_account_type='','(нет)',affiliate_account_type) AS aff_type, count() players
FROM retention.users WHERE account_type='normal' GROUP BY aff_type ORDER BY players DESC;
```

### 5. Конкретный аффилиат (Affiliate)
- **Вопрос:** какой партнёр даёт каких игроков
- **Колонки:** `users.affiliate_code`, `affiliate_username`
- **Логика:** GROUP BY code (топ + хвост)
- **В данных:** 122 аффилиата, заполнено 79%
- **Годность:** ✅
- **Применение:** отчёт качества партнёров (LTV/retention на affiliate)
```sql
SELECT affiliate_code, count() players FROM retention.users
WHERE account_type='normal' AND affiliate_code!='' GROUP BY affiliate_code ORDER BY players DESC LIMIT 20;
```

### 6. Лендинг / источник регистрации
- **Вопрос:** с какой страницы/зеркала пришёл
- **Колонки:** `users.registration_source`, `traffic_link_code`, `traffic_sub_id`
- **В данных:** 1749 URL (зеркала billionbahis234/243…, с зашитым `aff=AFxxx`); топ-источник лишь 7.5%
- **Годность:** ⚠️ грязно (URL-вариации) — лучше извлекать `aff=` или брать affiliate
- **Применение:** отчёт, извлечение кампании
```sql
SELECT registration_source, count() players FROM retention.users
WHERE account_type='normal' GROUP BY registration_source ORDER BY players DESC LIMIT 15;
```

### 7. Бонус-кампания (Campaign)
- **Вопрос:** под какой бонус/промо зашёл
- **Колонки:** `money_transactions.payment_method` (теги `campaign:XXX`)
- **В данных:** напр. `campaign:BONUSPRIMEBILLIONDAONLINE`, `campaign:BILLIONBAHIS3000`
- **Годность:** ✅
- **Применение:** оценка ROI кампаний
```sql
SELECT payment_method AS campaign, uniqExact(casino_player_id) players, count() tx
FROM retention.money_transactions WHERE payment_method LIKE 'campaign:%' GROUP BY campaign ORDER BY players DESC LIMIT 20;
```

---

# C. ДЕНЬГИ / ЦЕННОСТЬ

### 8. Депозитор vs не-депозитор (NDC / FTD)
- **Вопрос:** завёл ли реальные деньги
- **Колонки:** `users.ftd_date`
- **В данных:** не депозитор **91.4%** · депозитор **8.6%**
- **Годность:** ✅ сильнейший сигнал
- **Применение:** churn-признак, кампания на конверсию в депозит
```sql
SELECT if(ftd_date IS NULL,'не депозитор','депозитор') seg, count() players
FROM retention.users WHERE account_type='normal' GROUP BY seg;
```

### 9. Тир первого депозита (FTD tier)
- **Колонки:** `users.ftd_amount`
- **В данных:** ≤50: 11 · 50-200: 69 · 200-1000: **2 254 (5.8%)** · 1000+: **1 022 (2.6%)**
- **Годность:** ✅
- **Применение:** value-сегмент, VIP-онбординг
```sql
SELECT multiIf(ftd_date IS NULL,'0 нет',ftd_amount<=50,'≤50',ftd_amount<=200,'50-200',ftd_amount<=1000,'200-1000','1000+') tier, count() players
FROM retention.users WHERE account_type='normal' GROUP BY tier ORDER BY tier;
```

### 10. Кол-во депозитов (Single vs Multi-depositor)
- **Колонки:** `money_transactions` type∈(deposit,manual_deposit), status=completed
- **В данных:** 0 деп 28 300 · 1 (single) 2 119 · 2-3: 881 · 4-10: 399 · 10+: 138
- **Годность:** ✅ (повторный депозит = вовлечённый плательщик)
- **Применение:** churn-признак, кампания на 2-й депозит
```sql
WITH m AS (SELECT casino_player_id, countIf(type IN ('deposit','manual_deposit') AND status='completed') dc
  FROM retention.money_transactions GROUP BY casino_player_id)
SELECT multiIf(dc=0,'0',dc=1,'1 single',dc<=3,'2-3',dc<=10,'4-10','10+') seg, count() players
FROM m WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal')
GROUP BY seg ORDER BY seg;
```

### 11. Способ оплаты (Payment method)
- **Колонки:** `money_transactions.payment_method`
- **В данных:** havale-провайдеры — `neopays:bank_transfer`, `fastpay:havale`, `aninda:havale` (турецкий банк-перевод доминирует)
- **Годность:** ✅
- **Применение:** отчёт, оптимизация платёжек
```sql
SELECT payment_method, uniqExact(casino_player_id) players, count() tx
FROM retention.money_transactions WHERE type IN ('deposit','manual_deposit') AND payment_method NOT LIKE 'campaign:%' AND payment_method!=''
GROUP BY payment_method ORDER BY tx DESC LIMIT 15;
```

### 12. Платёжное трение (Payment friction) ⚠️ драйвер оттока
- **Вопрос:** были ли проблемы с депозитами/выводами
- **Колонки:** `money_transactions.status` (rejected/failed)
- **В данных:** у депозитов высокая доля rejected; reject-rate **выводов 39.4%**
- **Годность:** ✅ сильный churn-сигнал (игрок не смог занести/снять → ушёл)
- **Применение:** churn-признак, фрод/UX-алерт
```sql
WITH m AS (SELECT casino_player_id,
   countIf(type IN ('deposit','manual_deposit')) dep_req,
   countIf(type IN ('deposit','manual_deposit') AND status IN ('rejected','failed')) dep_fail
  FROM retention.money_transactions GROUP BY casino_player_id)
SELECT multiIf(dep_req=0,'нет деп-попыток',dep_fail=0,'без отказов',dep_fail*2>=dep_req,'много отказов','были отказы') seg, count() players
FROM m WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg;
```

### 13. Winner / Loser
- **Колонки:** `game_transactions.bet_amount`, `win_amount`
- **Логика:** net = Σwin − Σbet (минус = игрок проиграл = GGR казино)
- **В данных:** в минусе **87%** (0-1000: 69.7%, >1000: 17.6%) · в плюсе 13%
- **Годность:** ✅
- **Применение:** отчёт, аномалии (стабильные winners = фрод/арбитраж)
```sql
WITH pp AS (SELECT casino_player_id, sumIf(win_amount,transaction_type IN ('win','freespins_win'))-sumIf(bet_amount,transaction_type IN ('bet','freespins_bet')) net
  FROM retention.game_transactions GROUP BY casino_player_id)
SELECT multiIf(net>1000,'плюс >1000',net>0,'плюс 0-1000',net>-1000,'минус 0-1000','минус >1000') seg, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg ORDER BY seg;
```

### 14. Value-тир / GGR (High value … Minnow)
- **Колонки:** оборот `Σbet_amount`, net
- **Логика:** квантильные тиры по обороту/GGR
- **В данных:** медиана оборота ~2 215₺, p90 ~15 196₺ (топ 1% даёт основной GGR)
- **Годность:** ✅
- **Применение:** VIP-выделение, реко, кампания
```sql
WITH pp AS (SELECT casino_player_id, sumIf(bet_amount,transaction_type IN ('bet','freespins_bet')) turnover
  FROM retention.game_transactions GROUP BY casino_player_id HAVING turnover>0)
SELECT multiIf(turnover>=quantile(0.99)(turnover) OVER(),'VIP top1%',
               turnover>=quantile(0.9)(turnover) OVER(),'High p90-99',
               turnover>=quantile(0.5)(turnover) OVER(),'Mid','Low') tier, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY tier;
```

### 14a. Поведение выводов (Withdrawal behaviour)
- **Колонки:** `money_transactions` type∈(withdrawal,manual_withdrawal)
- **В данных:** выводящих **4 088** (даже больше депозиторов 3 537 — выводят бонусные выигрыши) · reject-rate выводов **39.4%**
- **Годность:** ✅
- **Применение:** churn-сигнал (отклонённый вывод → уход), кэш-аналитика
```sql
WITH m AS (SELECT casino_player_id,
   sumIf(amount,type IN ('withdrawal','manual_withdrawal') AND status='completed') wd,
   sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') dep
  FROM retention.money_transactions GROUP BY casino_player_id)
SELECT multiIf(wd=0,'не выводил',dep=0,'вывод без деп (бонусы)',wd>dep,'вывел больше чем внёс','вывел меньше') seg, count() players
FROM m WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg;
```

### 14b. Состояние баланса (Balance state)
- **Колонки:** `users.balance`, `bonus_balance`
- **В данных:** `balance>0` у **58%**, `bonus_balance>0` у **23%**
- **Годность:** ✅ (деньги/бонус на счету = причина вернуться)
- **Применение:** кампания «у тебя остались деньги/фриспины»
```sql
SELECT multiIf(balance>0 AND bonus_balance>0,'кэш+бонус',balance>0,'только кэш',bonus_balance>0,'только бонус','пусто') seg, count() players
FROM retention.users WHERE account_type='normal' GROUP BY seg ORDER BY players DESC;
```

---

# D. ВОВЛЕЧЁННОСТЬ / ПОВЕДЕНИЕ

### 15. Активных дней (Engagement / activity tier) ⭐
- **Колонки:** `game_transactions.created_at`, `casino_player_id`
- **Логика:** `uniqExact(toDate(created_at))` на игрока → бакеты
- **В данных:** 1 день **64.7%** (18 089) · 2-3: 24.4% · 4-7: 8.6% · 8-30: 2.3% · 30+: 0.1% (21)
- **Годность:** ✅ топ-сигнал (определяет почти всё; «один день» = уже почти ушёл)
- **Применение:** churn-признак, ядро сегментации
```sql
WITH pp AS (SELECT casino_player_id, uniqExact(toDate(toTimezone(created_at,'Europe/Istanbul'))) d
  FROM retention.game_transactions WHERE transaction_type IN ('bet','freespins_bet') GROUP BY casino_player_id)
SELECT multiIf(d=1,'1 день',d<=3,'2-3 дня',d<=7,'4-7 дней',d<=30,'8-30 дней','30+ дней') seg, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg ORDER BY min(d);
```

### 16. Кол-во ставок (Bet volume)
- **Колонки:** `transaction_type IN ('bet','freespins_bet')`
- **В данных:** медиана 366 ставок, p90 1 898
- **Годность:** ✅
- **Применение:** churn-признак, value
```sql
WITH pp AS (SELECT casino_player_id, countIf(transaction_type IN ('bet','freespins_bet')) b
  FROM retention.game_transactions GROUP BY casino_player_id HAVING b>0)
SELECT multiIf(b<=50,'≤50',b<=200,'51-200',b<=1000,'201-1000',b<=5000,'1001-5000','5000+') seg, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg ORDER BY min(b);
```

### 17. Средняя ставка (Stake level / high-roller)
- **Колонки:** `game_transactions.bet_amount`
- **В данных:** ≤5₺ micro 39.6% · 5-50₺ **55%** · 50-200₺ 4.1% · 200-1000₺ 1.1% · **1000₺+ хайроллер 0.2% (51 чел)**
- **Годность:** ✅ (хайроллеры редки, но огромная ценность)
- **Применение:** VIP-таргет, реко, value
```sql
WITH pp AS (SELECT casino_player_id, avgIf(bet_amount,transaction_type IN ('bet','freespins_bet')) ab
  FROM retention.game_transactions GROUP BY casino_player_id HAVING ab>0)
SELECT multiIf(ab<=5,'≤5 micro',ab<=50,'5-50',ab<=200,'50-200',ab<=1000,'200-1000','1000+ хайроллер') seg, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg ORDER BY min(ab);
```

### 18. Бонусник vs реал (Bonus-hunter vs real-money)
- **Колонки:** `transaction_type` (freespins_bet доля)
- **В данных:** только реал **50%** · в осн. реал 23.5% · в осн. бонусы 22.6% · только бонусы 3.9%
- **Годность:** ✅
- **Применение:** churn-признак (бонусники уходят быстрее), бонус-политика
```sql
WITH pp AS (SELECT casino_player_id, countIf(transaction_type='freespins_bet') fs, countIf(transaction_type='bet') rb
  FROM retention.game_transactions GROUP BY casino_player_id HAVING (fs+rb)>0)
SELECT multiIf(rb=0,'только бонусы',fs=0,'только реал',fs>rb,'в осн. бонусы','в осн. реал') seg, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg ORDER BY players DESC;
```

### 19. Сессии / частота (Session frequency)
- **Колонки:** `game_sessions` count, `duration_minutes` (⚠️ часто пусто)
- **В данных:** 270 421 сессия на 29 055 игроков; устройство — всё desktop
- **Годность:** ✅ (по числу сессий) / ⚠️ duration разрежён
- **Применение:** вовлечённость, отчёт
```sql
SELECT multiIf(s=1,'1 сессия',s<=5,'2-5',s<=20,'6-20','20+') seg, count() players FROM (
  SELECT casino_player_id, count() s FROM retention.game_sessions
  WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY casino_player_id
) GROUP BY seg ORDER BY min(s);
```

### 19a. Интенсивность ставок (Bet intensity / grinder)
- **Колонки:** ставок / активный день
- **В данных:** ≤20/д 3.4% · 21-100 15.4% · 101-500 **59.2%** · 501-2000 20.6% · 2000+/д грайндер 1.4% (395)
- **Годность:** ✅ (грайндеры — высокий риск/ценность)
- **Применение:** churn-признак, RG-сигнал, реко
```sql
WITH pp AS (SELECT casino_player_id, countIf(transaction_type IN ('bet','freespins_bet'))/uniqExact(toDate(created_at)) bpd
  FROM retention.game_transactions GROUP BY casino_player_id HAVING bpd>0)
SELECT multiIf(bpd<=20,'≤20/д',bpd<=100,'21-100',bpd<=500,'101-500',bpd<=2000,'501-2000','2000+ грайндер') seg, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg ORDER BY min(bpd);
```

### 19b. Время игры (Time-of-day / day-of-week)
- **Колонки:** `game_transactions.created_at` (Istanbul)
- **В данных:** 🌙 пик ставок **00:00–06:00** (турки играют ночью!) · по дням ровно, чуть выше пн и вс
- **Годность:** ✅
- **Применение:** тайминг кампаний/пушей, отчёт
```sql
SELECT toHour(toTimezone(created_at,'Europe/Istanbul')) hr, count() bets
FROM retention.game_transactions WHERE transaction_type IN ('bet','freespins_bet') GROUP BY hr ORDER BY hr;
```

---

# E. ИГРОВОЕ ПОВЕДЕНИЕ (ключ `game_uuid` — 100%, 55 932 игры)

> Названий игр в данных нет (только uuid-хеши; см. приложение). Для сегментации/реко имена не нужны.

### 20. Разнообразие игр (Game diversity)
- **Колонки:** `game_transactions.game_uuid`
- **В данных:** 1 игра 34.9% · 2-3 35.8% · 4-10 24.2% · 11-30 4.3% · 30+ 0.8%
- **Годность:** ✅
- **Применение:** реко (моногамным — похожие игры), churn-признак
```sql
WITH pp AS (SELECT casino_player_id, uniqExact(game_uuid) g FROM retention.game_transactions
  WHERE transaction_type IN ('bet','freespins_bet') AND game_uuid!='' GROUP BY casino_player_id)
SELECT multiIf(g=1,'1 игра',g<=3,'2-3',g<=10,'4-10',g<=30,'11-30','30+') seg, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg ORDER BY min(g);
```

### 21. Хиты vs нишевые (Hit affinity)
- **Колонки:** `game_uuid` vs топ-10 игр
- **В данных:** смешанно 44.3% · только хиты 33.4% · только нишевые 22.3%
- **Годность:** ✅
- **Применение:** реко, контент-стратегия
```sql
WITH hits AS (SELECT game_uuid FROM retention.game_transactions WHERE transaction_type IN ('bet','freespins_bet') AND game_uuid!=''
  GROUP BY game_uuid ORDER BY uniqExact(casino_player_id) DESC LIMIT 10),
pp AS (SELECT casino_player_id, countIf(game_uuid IN hits) h, count() t FROM retention.game_transactions
  WHERE transaction_type IN ('bet','freespins_bet') AND game_uuid!='' GROUP BY casino_player_id HAVING t>0)
SELECT multiIf(h=0,'только нишевые',h=t,'только хиты','смешанно') seg, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg ORDER BY players DESC;
```

### 22. Провайдер (Game provider)
- **Колонки:** `game_transactions.aggregator`
- **В данных:** slotegrator **99%** · atom 2 274 игрока · fundist 124
- **Годность:** ⚠️ слабо (один доминирует)
- **Применение:** отчёт
```sql
SELECT aggregator, uniqExact(casino_player_id) players, formatReadableQuantity(count()) bets
FROM retention.game_transactions WHERE transaction_type IN ('bet','freespins_bet') GROUP BY aggregator ORDER BY players DESC;
```

### 23. Любимая игра / игровые кластеры (для рекомендаций)
- **Колонки:** `game_uuid` × `casino_player_id` = матрица взаимодействий
- **В данных:** топ-игра `f5470d59…` — 12 735 игроков
- **Годность:** ✅ (по uuid; имён нет)
- **Применение:** **рекомендации** (item-item «кто играл X, играл и Y»)
```sql
-- любимая игра игрока (по числу ставок)
SELECT casino_player_id, argMax(game_uuid, cnt) favourite_game FROM (
  SELECT casino_player_id, game_uuid, count() cnt FROM retention.game_transactions
  WHERE transaction_type IN ('bet','freespins_bet') AND game_uuid!='' GROUP BY casino_player_id, game_uuid
) GROUP BY casino_player_id LIMIT 20;
```

---

# F. ЖИЗНЕННЫЙ ЦИКЛ

### 24. Recency-стадия (Lifecycle by recency) ⭐
- **Колонки:** последняя ставка `max(created_at)`
- **В данных:** 🟢 активен 0-7д 2.2% · 🟡 остывает 8-30д 6.7% · 🟠 под риском 31-60д 16.5% · 🔵 спящий 61-90д 35.8% · ⚫ отток 90д+ 38.7%
- **Годность:** ✅ топ — это основа метки оттока
- **Применение:** churn-метка, win-back кампании
```sql
WITH pp AS (SELECT casino_player_id, dateDiff('day', toDate(max(created_at)), today()) rec
  FROM retention.game_transactions GROUP BY casino_player_id)
SELECT multiIf(rec<=7,'1 активен',rec<=30,'2 остывает',rec<=60,'3 под риском',rec<=90,'4 спящий','5 отток') stage, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY stage ORDER BY stage;
```

### 25. Готовый статус активности (activity_status)
- **Колонки:** `users.activity_status` (производное поле)
- **В данных:** dormant_30_90d 14 384 · active_30d 9 316 · dormant_90_180d 9 054 · registered_no_activity 6 110 · dormant_180d_plus 146
- **Годность:** ✅ (быстрый готовый срез; но это снапшот на момент экспорта)
- **Применение:** отчёт
```sql
SELECT activity_status, count() players FROM retention.users WHERE account_type='normal' GROUP BY activity_status ORDER BY players DESC;
```

### 26. Стадия активации (Activation funnel)
- **Колонки:** наличие в `game_transactions` / `game_sessions` / `money_transactions`
- **В данных:** никогда не играл ~11 033 (из них мёртвых 6 949) · 1 день 18 089 · многодневный ~9 888
- **Годность:** ✅
- **Применение:** кампания на активацию (отдельно от оттока!)
```sql
WITH played AS (SELECT DISTINCT casino_player_id FROM retention.game_transactions WHERE transaction_type IN ('bet','freespins_bet'))
SELECT if(casino_player_id IN played,'играл','не активирован') seg, count() players
FROM retention.users WHERE account_type='normal' GROUP BY seg;
```

### 26a. Реактивация / win-back
- **Вопрос:** возвращался ли после паузы
- **Колонки:** разрывы (gaps) между активными днями `game_transactions`
- **В данных:** вернулись после паузы ≥14д — **5 888**, ≥30д — 3 182 (из 9 874 многодневных)
- **Годность:** ✅ (доказали, что игрок «воскрешаем»)
- **Применение:** win-back кампании, churn-признак
```sql
WITH days AS (SELECT casino_player_id, toDate(created_at) d FROM retention.game_transactions
   WHERE transaction_type IN ('bet','freespins_bet') GROUP BY casino_player_id, d),
gaps AS (SELECT casino_player_id, max(dateDiff('day', prev_d, d)) max_gap FROM (
   SELECT casino_player_id, d, lagInFrame(d) OVER (PARTITION BY casino_player_id ORDER BY d) prev_d FROM days
) WHERE prev_d!=toDate('1970-01-01') GROUP BY casino_player_id)
SELECT multiIf(max_gap>=30,'вернулся после 30д+',max_gap>=14,'вернулся после 14-30д','без больших пауз') seg, count() players
FROM gaps WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal') GROUP BY seg;
```

---

# G. КОМПОЗИТНЫЕ (главные для ретеншна)

### 27. RFM ⭐⭐ (Recency · Frequency · Monetary)
- **Вопрос:** золотой стандарт сегментации — кто ценный и кто уходит
- **Колонки:** R=`max(created_at)`, F=активные дни/ставки, M=оборот или депозиты
- **Логика:** каждую ось бьём на квинтили 1-5 → именованные сегменты
- **Сегменты:** Champions · Loyal · Potential Loyalist · New · Promising · Need Attention · At-Risk · Can't-Lose-Them · Hibernating · Lost
- **Годность:** ✅✅ главный инструмент
- **Применение:** всё — кампании, реко, приоритизация удержания
```sql
WITH pp AS (
  SELECT casino_player_id,
    dateDiff('day', toDate(max(created_at)), today()) AS recency,
    uniqExact(toDate(created_at)) AS frequency,
    sumIf(bet_amount,transaction_type IN ('bet','freespins_bet')) AS monetary
  FROM retention.game_transactions
  WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal')
  GROUP BY casino_player_id),
scored AS (
  SELECT *,
    6 - ntile(5) OVER (ORDER BY recency)   AS R,   -- меньше дней = выше балл
    ntile(5) OVER (ORDER BY frequency)     AS F,
    ntile(5) OVER (ORDER BY monetary)      AS M
  FROM pp)
SELECT multiIf(
  R>=4 AND F>=4 AND M>=4,'Champions',
  R>=3 AND F>=3,'Loyal',
  R>=4 AND F<=2,'New/Promising',
  R<=2 AND F>=4 AND M>=4,'Cant-Lose-Them',
  R<=2 AND F>=3,'At-Risk',
  R<=2,'Hibernating/Lost','Need-Attention') AS rfm_segment,
  count() players, round(avg(monetary),0) avg_turnover
FROM scored GROUP BY rfm_segment ORDER BY players DESC;
```

### 28. Value × Lifecycle матрица
- **Логика:** ценность (net/оборот) × recency-стадия
- **Применение:** приоритизация — «High-value под риском» спасать первыми
```sql
WITH pp AS (SELECT casino_player_id,
   sumIf(bet_amount,transaction_type IN ('bet','freespins_bet')) turnover,
   dateDiff('day', toDate(max(created_at)), today()) rec
  FROM retention.game_transactions GROUP BY casino_player_id)
SELECT if(turnover>=quantile(0.9)(turnover) OVER(),'High value','Rest') value_tier,
   multiIf(rec<=30,'активен',rec<=90,'под риском','отток') lifecycle, count() players
FROM pp WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal')
GROUP BY value_tier, lifecycle ORDER BY value_tier, lifecycle;
```

### 29. VIP под риском (срочно спасать)
- **Логика:** депозитор × хайроллер/high-value × под риском/спящий
- **Применение:** приоритетный список на ручной retention
```sql
WITH pp AS (SELECT t.casino_player_id,
   avgIf(t.bet_amount,t.transaction_type IN ('bet','freespins_bet')) avg_bet,
   dateDiff('day', toDate(max(t.created_at)), today()) rec
  FROM retention.game_transactions t GROUP BY t.casino_player_id)
SELECT count() vip_at_risk FROM pp
JOIN retention.users u USING(casino_player_id)
WHERE u.account_type='normal' AND u.ftd_date IS NOT NULL AND pp.avg_bet>=200 AND pp.rec BETWEEN 14 AND 90;
```

### 29a. Канал × удержание
- **Логика:** affiliate_account_type × retention/recency — какой канал даёт удерживаемых
- **Применение:** перераспределение бюджета на качественные каналы
```sql
WITH pp AS (SELECT casino_player_id, dateDiff('day', toDate(max(created_at)), today()) rec
  FROM retention.game_transactions GROUP BY casino_player_id)
SELECT u.affiliate_account_type, count() players,
   round(100*countIf(pp.rec<=30)/count(),1) pct_still_active_30d
FROM retention.users u LEFT JOIN pp USING(casino_player_id)
WHERE u.account_type='normal' GROUP BY u.affiliate_account_type ORDER BY players DESC;
```

---

# Приложение 1 — что НЕ годится для когорт (и почему)

| Поле/ось | Почему нельзя |
|---|---|
| Страна (`country_iso_estimated`,`country_name`) | у всех **TR** |
| Устройство (`game_sessions.device`) | всё **desktop** (мобайла нет) |
| Режим (`game_sessions.mode`) | всё **real** (demo нет) |
| Валюта (`currency`) | по сути всё **TRY** (205 строк TL) |
| Таймзона (`timezone`) | одно значение |
| Верификация (`phone_verified`,`email_verified`) | **98.5%** одинаково (verified) |
| RG / `self_excluded` / `risk_tags` | пусто / одно значение |
| Контактность (`marketing_consent`,`opt_out`,`telegram_*`,`has_whatsapp/viber`) | **0% заполнено** |
| Названия игр (`gameName`) | только **0.2% ставок**, топ-игры без имён → нужен каталог провайдера |
| Возраст / пол | в данных отсутствуют |

# Приложение 2 — все колонки таблиц

**users (55):** casino_player_id, display_id, username, email, phone, phone_country_code, country_iso_estimated, country_name, currency, reg_date, ftd_date, ftd_amount, last_active, activity_status, account_type, account_type_reason, role, status, is_active, is_real_player_candidate, phone_verified, email_verified, timezone, marketing_consent(+at/source), service_consent(+at/source), self_excluded, rg_flag, risk_tags, opt_out, do_not_contact, telegram_id, telegram_username, has_whatsapp, has_viber, affiliate_db_id, affiliate_code, affiliate_username, affiliate_account_type, traffic_link_code, traffic_sub_id, balance, bonus_balance, total_deposits_lifetime, total_withdrawals_lifetime, total_bets_lifetime, total_wins_lifetime, created_at, last_login, registration_source, click_id, aggregate_id

**money_transactions (26):** transaction_row_id, transaction_id, casino_player_id, type, status, amount, currency, payment_method, payment_details, reference_id, balance_before, balance_after, bonus_balance_before, bonus_balance_after, fees, exchange_rate, assigned_bank_id, assigned_bank_name, description, rejection_reason, reviewed_by, notes, created_at, updated_at, processed_at, sent_at

**game_sessions (15):** session_row_id, session_id, casino_player_id, aggregator, game_uuid, mode, device, language, currency, status, is_active, created_at, started_at, ended_at, duration_minutes

**game_transactions (22):** source_table, transaction_row_id, casino_player_id, session_id, aggregator, game_uuid, game_code, round_id, external_transaction_id, reference_transaction_id, transaction_type, bet_amount, win_amount, amount, currency, status, balance_before, balance_after, balance_source, raw_game_data, created_at, processed_at

# Приложение 3 — связь со следующими шагами

**Признаки CatBoost churn** (берём из когорт): recency (24), частота/активные дни (15,16), скорость активации (3b), депозит-флаг (8) + FTD-тир (9) + кол-во депозитов (10), средняя ставка (17), бонус-доля (18), интенсивность (19a), платёжное трение (12), поведение выводов (14a), разнообразие игр (20), канал (4).

**Для отчётов/кампаний/реко:** RFM (27), Value×Lifecycle (28), VIP-под-риском (29), реактивация (26a), любимые игры (23), время игры (19b).

**Маршрут:** этот файл (оси) → RFM-сегментация → витрина `player_features` → CatBoost churn → рекомендации.
