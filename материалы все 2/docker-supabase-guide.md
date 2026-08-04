# 6-36 | Docker + Self-Hosted Supabase Guide

> Тип: Reference
> Фаза: 6 — Deploy
> Для кого: AI-Архитектор, разворачивающий Supabase на VPS в РФ

---

## Философия этого документа

Этот файл — **загружаемый reference + пошаговая инструкция при ручной работе**. Вы не разворачиваете Supabase в Docker по памяти — вы используете его как:

1. **Reference для Claude** — загрузить в проект, чтобы Claude сам развернул self-hosted Supabase на VPS по правильной последовательности (Docker → compose → миграции → проверка)
2. **Пошаговая инструкция** — когда вы идёте сами в SSH-сессии
3. **Чек-лист 152-ФЗ соответствия** — проверить, что данные действительно остаются в РФ

**Принцип работы:**
- Вы — архитектор: решили, что нужен self-hosted из-за 152-ФЗ или экономии
- Claude Code — исполнитель: ставит Docker, настраивает docker-compose, поднимает сервисы, проверяет
- Этот документ — общий язык между вами

**Как применять:**
```
Сценарий 1: Claude разворачивает Supabase
  Вы → даёте Claude SSH-доступ + этот файл → Claude проходит все шаги

Сценарий 2: Вы разворачиваете сами
  Вы → открываете файл → копируете docker-compose.yml → поднимаете

Сценарий 3: Миграция с Cloud на Self-Hosted
  Вы/Claude → следуете разделу про экспорт/импорт данных → проверяете соответствие 152-ФЗ
```

---

## Зачем self-hosted Supabase

По 152-ФЗ персональные данные граждан РФ должны храниться на территории России. Cloud Supabase хранит данные за рубежом (AWS, EU/US). Решение — развернуть Supabase на своём VPS (Beget, Санкт-Петербург).

---

## Требования к VPS

| Параметр | Минимум | Рекомендуется |
|----------|---------|---------------|
| CPU | 2 ядра | 4 ядра |
| RAM | 4 ГБ | 8 ГБ |
| SSD | 40 ГБ | 80 ГБ |
| ОС | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |

Supabase в Docker — ресурсоёмкий. На минимальном VPS (1 CPU / 1 GB) работать не будет.

---

## Шаг 1: Установка Docker и Docker Compose

### Docker

```bash
# Обновить пакеты
sudo apt update && sudo apt upgrade -y

# Установить зависимости
sudo apt install -y ca-certificates curl gnupg

# Добавить GPG-ключ Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Добавить репозиторий
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установить Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Добавить пользователя в группу docker (чтобы не писать sudo)
sudo usermod -aG docker $USER

# Перелогиниться
exit
# Заново подключиться по SSH

# Проверить
docker --version
docker compose version
```

---

## Шаг 2: Клонирование Supabase

```bash
# Создать директорию
sudo mkdir -p /opt/supabase
sudo chown $USER:$USER /opt/supabase
cd /opt/supabase

# Клонировать репозиторий
git clone --depth 1 https://github.com/supabase/supabase.git

# Перейти в директорию Docker
cd supabase/docker
```

---

## Шаг 3: Настройка переменных окружения

```bash
# Скопировать пример .env
cp .env.example .env

# Открыть для редактирования
nano .env
```

### Обязательные изменения в `.env`

```bash
############
# Secrets — ОБЯЗАТЕЛЬНО СМЕНИТЬ!
############

# Сгенерировать случайные значения:
# openssl rand -base64 32

# JWT Secret (минимум 32 символа)
JWT_SECRET=your-super-secret-jwt-token-at-least-32-chars

# Anon Key — сгенерировать на https://supabase.com/docs/guides/self-hosting#api-keys
ANON_KEY=your-generated-anon-key

# Service Role Key — сгенерировать там же
SERVICE_ROLE_KEY=your-generated-service-role-key

# Dashboard
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=your-strong-dashboard-password

# PostgreSQL
POSTGRES_PASSWORD=your-strong-postgres-password

############
# URLs
############

# Внешний URL (ваш домен)
SITE_URL=https://taskflow.ru
API_EXTERNAL_URL=https://api.taskflow.ru

# Studio (Dashboard) — можно оставить на поддомене
SUPABASE_PUBLIC_URL=https://supabase.taskflow.ru

############
# SMTP (для отправки email: подтверждение, сброс пароля)
############
SMTP_HOST=smtp.yandex.ru
SMTP_PORT=465
SMTP_USER=noreply@taskflow.ru
SMTP_PASS=your-smtp-password
SMTP_SENDER_NAME=TaskFlow
SMTP_ADMIN_EMAIL=admin@taskflow.ru
```

### Генерация JWT-ключей

```bash
# Сгенерировать JWT_SECRET
openssl rand -base64 32

# Для ANON_KEY и SERVICE_ROLE_KEY используйте:
# https://supabase.com/docs/guides/self-hosting#api-keys
# Или утилиту:
# npx supabase-jwt --secret YOUR_JWT_SECRET --role anon
# npx supabase-jwt --secret YOUR_JWT_SECRET --role service_role
```

---

## Шаг 4: Запуск Supabase

```bash
cd /opt/supabase/supabase/docker

# Запустить все сервисы
docker compose up -d

# Проверить статус
docker compose ps
```

### Ожидаемые контейнеры

```
NAME                    STATUS
supabase-auth           Up
supabase-db             Up
supabase-kong           Up
supabase-meta           Up
supabase-realtime       Up
supabase-rest           Up
supabase-storage        Up
supabase-studio         Up
supabase-vector         Up
supabase-functions      Up
```

### Проверка работоспособности

```bash
# Health check — REST API
curl -s http://localhost:8000/rest/v1/ \
  -H "apikey: YOUR_ANON_KEY" | head -c 200

# Health check — Auth
curl -s http://localhost:8000/auth/v1/health

# Studio (Dashboard) — по умолчанию на порту 8000
# Открыть в браузере: http://YOUR_SERVER_IP:8000
```

---

## Шаг 5: Nginx Reverse Proxy для Supabase

```bash
sudo nano /etc/nginx/sites-available/supabase
```

```nginx
# Supabase API
server {
    listen 80;
    server_name api.taskflow.ru;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Для больших файлов (Storage)
        client_max_body_size 50M;
    }
}

# Supabase Studio (Dashboard) — опционально
server {
    listen 80;
    server_name supabase.taskflow.ru;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Активировать
sudo ln -s /etc/nginx/sites-available/supabase /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# SSL
sudo certbot --nginx -d api.taskflow.ru -d supabase.taskflow.ru
```

---

## Шаг 6: Подключение из приложения

### Переменные окружения в Next.js / Node.js

```bash
# .env.local
NEXT_PUBLIC_SUPABASE_URL=https://api.taskflow.ru
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

### Код подключения (TypeScript)

```typescript
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);
```

---

## Шаг 7: Бэкапы

### Автоматический бэкап PostgreSQL

Создать скрипт `/opt/supabase/backup.sh`:

```bash
#!/bin/bash

BACKUP_DIR="/opt/supabase/backups"
DATE=$(date +%Y-%m-%d_%H-%M)
CONTAINER="supabase-db"

mkdir -p $BACKUP_DIR

# Создать дамп
docker exec $CONTAINER pg_dump -U postgres -Fc > "$BACKUP_DIR/supabase_$DATE.dump"

# Удалить бэкапы старше 7 дней
find $BACKUP_DIR -name "*.dump" -mtime +7 -delete

echo "Backup created: supabase_$DATE.dump"
```

```bash
chmod +x /opt/supabase/backup.sh
```

### Настройка cron (ежедневно в 3:00)

```bash
crontab -e

# Добавить строку:
0 3 * * * /opt/supabase/backup.sh >> /opt/supabase/backup.log 2>&1
```

### Восстановление из бэкапа

```bash
# Скопировать дамп в контейнер
docker cp backup.dump supabase-db:/tmp/backup.dump

# Восстановить
docker exec supabase-db pg_restore -U postgres -d postgres --clean /tmp/backup.dump
```

---

## Шаг 8: Обновление Supabase

```bash
cd /opt/supabase/supabase/docker

# Остановить контейнеры
docker compose down

# Обновить код
git pull

# Пересобрать и запустить
docker compose pull
docker compose up -d

# Проверить
docker compose ps
```

---

## Управление контейнерами

```bash
# Остановить
docker compose down

# Запустить
docker compose up -d

# Перезапустить конкретный сервис
docker compose restart supabase-auth

# Логи конкретного сервиса
docker compose logs -f supabase-auth --tail 50

# Общие логи
docker compose logs -f --tail 20

# Использование ресурсов
docker stats
```

---

## Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| Контейнеры падают с OOM | Мало RAM (< 4 ГБ) | Увеличить RAM на VPS |
| Port 8000 already in use | Другой сервис на порту | `sudo lsof -i :8000`, остановить конфликт |
| Auth не отправляет email | SMTP не настроен | Проверить SMTP_* переменные в `.env` |
| "Invalid JWT" ошибки | Ключи не совпадают | Перегенерировать ANON_KEY с правильным JWT_SECRET |
| Studio не загружается | Kong не проксирует | `docker compose logs supabase-kong` |
| Realtime не работает | WebSocket не проксируется | Проверить `Upgrade` заголовки в Nginx |
| Бэкап пустой | Неверное имя контейнера | `docker ps` — проверить имя |

---

## Безопасность

- [ ] Изменены все дефолтные пароли в `.env`
- [ ] Dashboard (Studio) закрыт за HTTP Basic Auth или VPN
- [ ] Порты 5432 (PostgreSQL), 8000 (Kong) НЕ открыты в firewall наружу
- [ ] Доступ к Supabase только через Nginx (HTTPS)
- [ ] Бэкапы работают и проверены (тестовое восстановление)
- [ ] SSH-доступ по ключу, вход по паролю отключен

---

*Файл курса "AI-Архитектор" — Фаза 6: Deploy*
