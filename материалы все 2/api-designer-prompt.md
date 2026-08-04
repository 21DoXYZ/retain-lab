# 2-15 | Генератор API-архитектуры

> **Тип:** Инструкция (промпт для Claude AI)
> **Модуль:** 2 — Спецификация и архитектура
> **Время применения:** 20-40 минут
> **Результат:** Полный дизайн API: эндпоинты, TypeScript-интерфейсы, коды ошибок, паттерны авторизации и пагинации

---

## Философия этого документа

Этот файл — **готовый промпт для Claude AI**. Вы не пишете его сами — копируете и используете.

**Принцип работы:**
- Вы — архитектор и коммуникатор
- Claude — исполнитель: читает промпт, делает работу
- Ваша задача — описать контекст и скопировать правильный промпт

**Workflow:**
```
Вы → копируете промпт → загружаете в Claude AI (web)
       ↓
       прикрепляете свой контекст (SPEC.md + схема БД)
       ↓
Claude → выполняет задачу по промпту
       ↓
Вы → получаете результат (дизайн API) → передаёте в Claude Code
```

Промпт уже отлажен. Не нужно его улучшать с первого раза — просто используйте.

---

## Что это и зачем

API — контракт между фронтендом и бэкендом. Плохо спроектированный API приводит к:
- Дублированию запросов и лишним round-trip'ам
- Несогласованным форматам ответов (фронтендер каждый раз гадает, что придёт)
- Уязвимостям (нет проверки авторизации, утечка данных)

Этот промпт генерирует полный API-дизайн на основе спецификации: методы, пути, параметры, тела запросов, формат ответов с TypeScript-интерфейсами, коды ошибок, правила авторизации.

AI-Архитектор загружает SPEC.md + этот промпт в Claude AI и получает готовый API-контракт, который backend-engineer и frontend-developer используют как единый источник истины.

---

## Когда использовать

- После генерации схемы БД (документ 2-14) — как следующий шаг
- При проектировании нового модуля с API-эндпоинтами
- Для стандартизации API существующего проекта
- При подготовке документации для внешних интеграций

---

## Где загружать

**Claude AI (Web)** — https://claude.ai

1. Открой чат в Claude AI
2. Загрузи SPEC.md (и, при наличии, схему БД из шага 2-14)
3. Скопируй промпт ниже
4. Отправь — Claude сгенерирует полный API-дизайн

---

## Промпт для Claude AI

```
Ты — старший API-архитектор, специализирующийся на Next.js 16 App Router и RESTful-дизайне. Пользователь загрузил спецификацию проекта. Твоя задача — спроектировать ВСЕ API-эндпоинты с полной документацией.

## АРХИТЕКТУРНЫЕ РЕШЕНИЯ

### Два типа серверного кода в Next.js 16

1. **Server Actions (`'use server'`)** — для мутаций данных из UI:
   - Создание, обновление, удаление записей
   - Формы и пользовательские действия
   - Файл: `src/app/actions/{module}.ts`

2. **Route Handlers (`app/api/`)** — для:
   - Вебхуков от внешних сервисов (платёжные системы, Telegram)
   - Публичного API для сторонних интеграций
   - Файл: `src/app/api/{resource}/route.ts`

### Для каждого Server Action определи:
- Имя функции (camelCase)
- Входные параметры (с Zod-схемой)
- Возвращаемый тип
- Проверки авторизации
- Обработку ошибок

### Для каждого Route Handler определи:
- HTTP-метод (GET, POST, PUT, PATCH, DELETE)
- Путь (RESTful, вложенные ресурсы через /)
- Query-параметры (для GET)
- Тело запроса (для POST/PUT/PATCH — TypeScript interface)
- Тело ответа (TypeScript interface для каждого кода)
- Коды ответов (200, 201, 400, 401, 403, 404, 409, 422, 500)
- Требования авторизации

## ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА

### RESTful-конвенции
- Ресурсы — существительные во множественном числе: /api/tasks, /api/projects
- Вложенные ресурсы через /: /api/projects/{id}/tasks
- Максимум 2 уровня вложенности
- Действия не в URL: POST /api/tasks/{id}/archive, НЕ POST /api/archiveTask

### HTTP-методы
- GET — получение (никогда не мутирует данные)
- POST — создание нового ресурса
- PATCH — частичное обновление (не PUT, если не заменяем целиком)
- DELETE — удаление

### Стандартный формат ответа

Успех (единичный ресурс):
```json
{
  "data": { ... },
  "meta": { "timestamp": "2026-04-10T12:00:00Z" }
}
```

Успех (список с пагинацией):
```json
{
  "data": [ ... ],
  "meta": {
    "total": 150,
    "page": 1,
    "per_page": 20,
    "total_pages": 8
  }
}
```

Ошибка:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Название задачи обязательно",
    "details": [
      { "field": "title", "message": "Поле обязательно для заполнения" }
    ]
  }
}
```

### Пагинация
- Cursor-based для лент и потоков (cursor, limit)
- Offset-based для таблиц и списков (page, per_page)
- Максимум per_page: 100, дефолт: 20
- Всегда возвращай meta с total, page, per_page, total_pages

### Коды ошибок (стандартные)
- VALIDATION_ERROR (400) — невалидные входные данные
- UNAUTHORIZED (401) — не аутентифицирован
- FORBIDDEN (403) — нет прав доступа
- NOT_FOUND (404) — ресурс не найден
- CONFLICT (409) — конфликт (дублирование)
- UNPROCESSABLE_ENTITY (422) — бизнес-логика не позволяет
- INTERNAL_ERROR (500) — серверная ошибка

### Авторизация
- Каждый эндпоинт помечен: public, authenticated, owner, admin
- Проверка через Supabase Auth: `createServerClient` + `auth.getUser()`
- Никогда не доверяй user_id из тела запроса — берём из сессии

### Валидация
- Все входные данные — через Zod-схемы
- Zod-схемы определены отдельно и переиспользуются (shared между клиентом и сервером)

## ФОРМАТ ВЫВОДА

Для каждого модуля выведи:
1. TypeScript-интерфейсы запросов и ответов
2. Zod-схемы валидации
3. Таблицу эндпоинтов: метод, путь, описание, авторизация
4. Детальное описание каждого эндпоинта

Проанализируй загруженную спецификацию и спроектируй все API-эндпоинты.
```

---

## Пример результата

Ниже — пример вывода для проекта **TaskFlow** (трекер задач для фрилансеров).

### Общие TypeScript-интерфейсы

```typescript
// src/types/api.ts

// Стандартный ответ с данными
export interface ApiResponse<T> {
  data: T;
  meta?: {
    timestamp: string;
  };
}

// Ответ со списком и пагинацией
export interface ApiListResponse<T> {
  data: T[];
  meta: {
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
  };
}

// Стандартная ошибка
export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: Array<{
      field: string;
      message: string;
    }>;
  };
}

// Параметры пагинации
export interface PaginationParams {
  page?: number;    // default: 1
  per_page?: number; // default: 20, max: 100
}
```

### Модуль: Tasks (задачи)

#### Zod-схемы

```typescript
// src/lib/validations/task.ts
import { z } from 'zod';

export const createTaskSchema = z.object({
  project_id: z.string().uuid(),
  title: z.string().min(1, 'Название обязательно').max(200),
  description: z.string().max(5000).optional(),
  priority: z.enum(['low', 'medium', 'high', 'urgent']).default('medium'),
  assignee_id: z.string().uuid().optional(),
  due_date: z.string().date().optional(),
});

export const updateTaskSchema = z.object({
  title: z.string().min(1).max(200).optional(),
  description: z.string().max(5000).nullable().optional(),
  status: z.enum(['backlog', 'todo', 'in_progress', 'review', 'done']).optional(),
  priority: z.enum(['low', 'medium', 'high', 'urgent']).optional(),
  assignee_id: z.string().uuid().nullable().optional(),
  due_date: z.string().date().nullable().optional(),
  position: z.number().int().min(0).optional(),
});

export const taskFiltersSchema = z.object({
  status: z.enum(['backlog', 'todo', 'in_progress', 'review', 'done']).optional(),
  priority: z.enum(['low', 'medium', 'high', 'urgent']).optional(),
  assignee_id: z.string().uuid().optional(),
  search: z.string().max(100).optional(),
  page: z.coerce.number().int().min(1).default(1),
  per_page: z.coerce.number().int().min(1).max(100).default(20),
});

export type CreateTaskInput = z.infer<typeof createTaskSchema>;
export type UpdateTaskInput = z.infer<typeof updateTaskSchema>;
export type TaskFilters = z.infer<typeof taskFiltersSchema>;
```

#### Таблица эндпоинтов

| Метод | Путь | Описание | Авторизация |
|-------|------|----------|-------------|
| GET | `/api/projects/{projectId}/tasks` | Список задач проекта (с фильтрацией и пагинацией) | member |
| POST | Server Action: `createTask` | Создание задачи | editor+ |
| PATCH | Server Action: `updateTask` | Обновление задачи | editor+ |
| DELETE | Server Action: `deleteTask` | Удаление задачи | owner |
| POST | Server Action: `reorderTasks` | Изменение порядка задач (drag-and-drop) | editor+ |
| POST | Server Action: `archiveTask` | Архивация задачи | editor+ |

#### Server Actions — детальное описание

```typescript
// src/app/actions/tasks.ts
'use server';

import { createServerClient } from '@/lib/supabase/server';
import { createTaskSchema, updateTaskSchema } from '@/lib/validations/task';
import { revalidatePath } from 'next/cache';

// ---- Создание задачи ----
// Авторизация: editor или owner проекта
// Ошибки: VALIDATION_ERROR, UNAUTHORIZED, FORBIDDEN, NOT_FOUND (проект)
export async function createTask(input: CreateTaskInput): Promise<{
  data?: Task;
  error?: { code: string; message: string };
}> {
  // 1. Валидация через Zod
  // 2. Проверка авторизации (auth.getUser + проверка членства в проекте)
  // 3. INSERT в tasks
  // 4. revalidatePath(`/projects/${input.project_id}`)
  // 5. Возврат созданной задачи
}

// ---- Обновление задачи ----
// Авторизация: editor или owner проекта
// Ошибки: VALIDATION_ERROR, UNAUTHORIZED, FORBIDDEN, NOT_FOUND
export async function updateTask(
  taskId: string,
  input: UpdateTaskInput
): Promise<{
  data?: Task;
  error?: { code: string; message: string };
}> {
  // 1. Валидация taskId (uuid) и input через Zod
  // 2. Проверка авторизации
  // 3. UPDATE tasks SET ... WHERE id = taskId
  // 4. revalidatePath
  // 5. Возврат обновлённой задачи
}

// ---- Удаление задачи ----
// Авторизация: только owner проекта
// Ошибки: UNAUTHORIZED, FORBIDDEN, NOT_FOUND
export async function deleteTask(taskId: string): Promise<{
  success?: boolean;
  error?: { code: string; message: string };
}> {
  // 1. Проверка авторизации (только owner)
  // 2. DELETE FROM tasks WHERE id = taskId
  // 3. revalidatePath
}

// ---- Перестановка задач (drag-and-drop) ----
// Авторизация: editor или owner
export async function reorderTasks(
  projectId: string,
  tasks: Array<{ id: string; position: number; status: string }>
): Promise<{
  success?: boolean;
  error?: { code: string; message: string };
}> {
  // 1. Валидация входных данных
  // 2. Проверка авторизации
  // 3. Batch UPDATE через transaction
  // 4. revalidatePath
}
```

#### Route Handler — список задач (GET)

```typescript
// src/app/api/projects/[projectId]/tasks/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { createServerClient } from '@/lib/supabase/server';
import { taskFiltersSchema } from '@/lib/validations/task';

// GET /api/projects/{projectId}/tasks?status=todo&page=1&per_page=20
//
// Ответ 200:
// {
//   "data": [
//     {
//       "id": "uuid",
//       "title": "Настроить CI/CD",
//       "status": "todo",
//       "priority": "high",
//       "assignee": { "id": "uuid", "full_name": "Иван Петров", "avatar_url": null },
//       "due_date": "2026-04-15",
//       "comments_count": 3,
//       "created_at": "2026-04-10T12:00:00Z"
//     }
//   ],
//   "meta": { "total": 42, "page": 1, "per_page": 20, "total_pages": 3 }
// }
//
// Ответ 401: { "error": { "code": "UNAUTHORIZED", "message": "Требуется авторизация" } }
// Ответ 403: { "error": { "code": "FORBIDDEN", "message": "Нет доступа к проекту" } }
// Ответ 404: { "error": { "code": "NOT_FOUND", "message": "Проект не найден" } }

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
) {
  const { projectId } = await params;
  const searchParams = request.nextUrl.searchParams;

  // 1. Парсинг и валидация query-параметров
  const filters = taskFiltersSchema.parse(
    Object.fromEntries(searchParams.entries())
  );

  // 2. Проверка авторизации (является ли пользователь участником проекта)
  const supabase = await createServerClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json(
      { error: { code: 'UNAUTHORIZED', message: 'Требуется авторизация' } },
      { status: 401 }
    );
  }

  // 3. Запрос задач с пагинацией и фильтрами
  // 4. Подсчёт total для мета-данных
  // 5. Возврат ответа
}
```

### Модуль: Projects (проекты)

#### Таблица эндпоинтов

| Метод | Путь | Описание | Авторизация |
|-------|------|----------|-------------|
| GET | `/api/projects` | Список проектов пользователя | authenticated |
| GET | `/api/projects/{id}` | Детали проекта | member |
| POST | Server Action: `createProject` | Создание проекта | authenticated |
| PATCH | Server Action: `updateProject` | Обновление проекта | owner |
| DELETE | Server Action: `deleteProject` | Удаление проекта | owner |
| POST | Server Action: `addProjectMember` | Добавление участника | owner |
| DELETE | Server Action: `removeProjectMember` | Удаление участника | owner |

### Модуль: Comments (комментарии)

#### Таблица эндпоинтов

| Метод | Путь | Описание | Авторизация |
|-------|------|----------|-------------|
| GET | `/api/tasks/{taskId}/comments` | Комментарии к задаче (cursor-based) | member |
| POST | Server Action: `createComment` | Добавление комментария | member |
| PATCH | Server Action: `updateComment` | Редактирование комментария | author |
| DELETE | Server Action: `deleteComment` | Удаление комментария | author |

---

## Чеклист после генерации

- [ ] Каждый эндпоинт имеет явную авторизацию (public/authenticated/owner/admin)
- [ ] Формат ответов единообразен (ApiResponse / ApiListResponse / ApiError)
- [ ] Пагинация определена для всех списочных эндпоинтов
- [ ] Zod-схемы покрывают все входные данные
- [ ] Коды ошибок стандартизированы (VALIDATION_ERROR, UNAUTHORIZED и т.д.)
- [ ] TypeScript-интерфейсы определены для всех запросов и ответов
- [ ] Server Actions используются для мутаций из UI
- [ ] Route Handlers используются только для вебхуков и внешних API

---

## Следующий шаг

После проектирования API переходи к **2-16 | UI/UX Brief** для создания технического задания на интерфейс.
