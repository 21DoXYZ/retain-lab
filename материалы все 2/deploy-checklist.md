# 6-33 | Deploy Checklist

> Тип: Reference
> Фаза: 6 — Deploy
> Для кого: AI-Архитектор перед выкаткой проекта в production

---

## Философия этого документа

Этот файл — **проверочный список после действия Claude или вашего перед деплоем**. Вы не прожимаете его руками каждый раз — вы используете его как:

1. **Чек-лист валидации** — пробежаться по пунктам перед тем как сказать Claude "деплой"
2. **Reference для Claude** — загрузить в проект, чтобы Claude сам проверял все пункты (tsc, env, smoke tests) автоматически через скилл `/deploy`
3. **Страховка от фейлов** — 80% production-проблем это забытые env-переменные и деплой не в тот проект

**Принцип работы:**
- Вы — архитектор: решаете, когда проект готов к деплою
- Claude Code — исполнитель: гоняет checks, деплоит, делает smoke-тесты
- Этот документ — общий язык между вами

**Как применять:**
```
Сценарий 1: Claude деплоит через скилл
  Вы → /deploy → Claude идёт по checklist автоматически → рапортует о результате

Сценарий 2: Вы деплоите вручную
  Вы → открываете checklist → галочка за галочкой → деплой

Сценарий 3: Post-deploy проверка
  Claude → задеплоил → Вы → сверяете smoke-тесты с разделом POST-DEPLOY → подтверждаете успех
```

---

## Зачем нужен чеклист

80% проблем на продакшене — это забытые переменные окружения, не проверенные эндпоинты и деплой не в тот проект. Этот чеклист предотвращает типичные фейлы.

---

## PRE-DEPLOY (до деплоя)

### Код и сборка

- [ ] `npx tsc --noEmit` проходит с НУЛЁМ ошибок
- [ ] `npm run build` завершается успешно (без warnings в критичных местах)
- [ ] Все TODO и placeholder'ы убраны из кода
- [ ] `.env.local` НЕ попадёт в git (проверить `.gitignore`)
- [ ] Нет hardcoded API-ключей, токенов, паролей в коде

### Переменные окружения

- [ ] Все переменные из `.env.local` добавлены в целевую среду:
  - Vercel: `vercel env ls` — проверить наличие
  - VPS: файл `.env` на сервере актуален
- [ ] Supabase URL и anon key указывают на PRODUCTION проект (не на dev!)
- [ ] API-ключи внешних сервисов (ЮKassa, Deepgram, Claude API) — production, не тестовые

### База данных

- [ ] Все миграции применены на production Supabase
- [ ] RLS-политики включены на всех таблицах с пользовательскими данными
- [ ] Индексы созданы для частых запросов
- [ ] Тестовые данные удалены из production БД

### Целевой проект

- [ ] Деплой идёт в ПРАВИЛЬНЫЙ проект (не в другой!)
  - Vercel: `vercel whoami` + `vercel project ls`
  - Supabase: `supabase projects list` — сверить project ref
  - VPS: подключение по SSH к правильному серверу

---

## DEPLOY (деплой)

### Vercel (фронтенд / Next.js)

```bash
# Проверить текущий проект
vercel whoami
vercel project ls

# Деплой в production
vercel --prod

# Следить за логами сборки
# Ошибки SWC, missing dependencies — исправлять сразу
```

### VPS (бэкенд / Node.js)

```bash
# Подключиться к серверу
ssh user@your-server-ip

# Обновить код
cd /var/www/taskflow-bot
git pull origin main

# Установить зависимости
npm ci --production

# Перезапустить через PM2
pm2 restart taskflow-bot
pm2 logs taskflow-bot --lines 20
```

### Supabase (БД / миграции)

```bash
# Применить миграции
supabase db push

# Или через SQL-редактор в dashboard
# Проверить через MCP: execute_sql
```

---

## POST-DEPLOY (после деплоя)

### Проверка работоспособности

- [ ] Health endpoint возвращает 200:
  ```bash
  curl -s https://taskflow.ru/api/health | jq .
  ```
- [ ] 2-3 критичных API-маршрута протестированы:
  ```bash
  curl -s https://taskflow.ru/api/tasks | jq .status
  curl -s https://taskflow.ru/api/auth/me -H "Authorization: Bearer TOKEN"
  ```
- [ ] Фронтенд загружается без ошибок в консоли
- [ ] Авторизация работает (регистрация, вход, выход)

### Логи

- [ ] Первые 20 строк логов без ошибок:
  ```bash
  # Vercel
  vercel logs --follow

  # VPS / PM2
  pm2 logs taskflow-bot --lines 20
  ```
- [ ] Нет 500-ых ошибок в Supabase Logs (Dashboard → Logs)

### Регрессия

- [ ] Существующие фичи работают (быстрый smoke test)
- [ ] Данные пользователей не потеряны
- [ ] Webhook'и работают (ЮKassa, Telegram, etc.)

---

## Таблица типичных ошибок деплоя

| Проблема | Причина | Решение |
|----------|---------|---------|
| SWC parser error | Backtick'и или спецсимволы в regex | Экранировать backtick'и в коде |
| Build failed: module not found | Пакет в devDependencies, а не в dependencies | `npm install package-name --save` |
| 500 на всех API-маршрутах | Переменные окружения не установлены | Проверить `vercel env ls` или `.env` на VPS |
| 401 Unauthorized | Просроченный или неверный API-ключ | Перегенерировать ключ, обновить env |
| Деплой ушёл в другой проект | Закешированный project ref | `vercel link` → выбрать правильный проект |
| Timeout на API-маршрутах | Длинные AI-вызовы с дефолтным таймаутом | В `vercel.json`: `"maxDuration": 60` |
| CORS ошибки на фронте | Бэкенд не настроен для фронтового домена | Добавить домен в `Access-Control-Allow-Origin` |
| SSL не работает на VPS | Certbot не настроен для нового домена | `sudo certbot --nginx -d taskflow.ru` |
| PM2 не перезапускает при краше | Не настроен `--max-restarts` | `pm2 start app.js --max-restarts 10` |
| БД: permission denied | RLS включен, но политики не созданы | Создать RLS-политики для всех CRUD-операций |
| Миграция не применилась | Конфликт с существующей схемой | Проверить порядок миграций, откатить при необходимости |
| Static файлы 404 | Неверный `output` в next.config | Проверить `output: 'standalone'` для VPS |

---

## Шаблон отчёта о деплое

```markdown
## Deploy Report — [Название проекта]

**Дата:** ДД.ММ.ГГГГ
**Версия:** v1.0.0
**Деплоил:** [Имя]

### Что задеплоено
- [ ] Фронтенд (Vercel)
- [ ] Бэкенд (VPS)
- [ ] База данных (миграции)

### Проверки после деплоя
- [ ] Health endpoint: OK / FAIL
- [ ] Авторизация: OK / FAIL
- [ ] Основной функционал: OK / FAIL
- [ ] Логи чистые: OK / FAIL

### Проблемы
- (нет / описание)

### Время деплоя
- Начало: HH:MM
- Конец: HH:MM
```

---

## Автоматизация через Claude Code

Добавь в `.claude/skills/deploy/SKILL.md`:

```markdown
# Deploy Skill

## Триггер
Пользователь говорит "задеплой" или "деплой в прод"

## Действия
1. Запустить `npx tsc --noEmit`
2. Запустить `npm run build`
3. Проверить `.env` переменные
4. Выполнить `vercel --prod` или SSH-деплой
5. Проверить health endpoint
6. Показать логи (первые 20 строк)
```

---

## Чеклист отката (Rollback)

Если после деплоя всё сломалось:

1. **Vercel:** откатить на предыдущий деплой в Dashboard → Deployments → Promote
2. **VPS:** `git checkout HEAD~1 && npm ci && pm2 restart all`
3. **БД:** восстановить из бэкапа Supabase (Dashboard → Database → Backups)
4. **Сообщить команде:** "Откат выполнен, причина: [описание]"

---

*Файл курса "AI-Архитектор" — Фаза 6: Deploy*
