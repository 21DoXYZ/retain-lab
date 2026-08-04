# 2-14 | Генератор архитектуры базы данных

> **Тип:** Инструкция (промпт для Claude AI)
> **Модуль:** 2 — Спецификация и архитектура
> **Время применения:** 20-40 минут
> **Результат:** Полная схема БД: CREATE TABLE, foreign keys, индексы, RLS-политики, триггеры, seed-данные — готовые SQL-миграции для Supabase

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
       прикрепляете свой контекст (SPEC.md)
       ↓
Claude → выполняет задачу по промпту
       ↓
Вы → получаете результат (SQL-миграции) → применяете в Supabase
```

Промпт уже отлажен. Не нужно его улучшать с первого раза — просто используйте.

---

## Что это и зачем

Архитектура базы данных — фундамент любого SaaS. Ошибки на этом уровне каскадно ломают бэкенд, фронтенд и безопасность. Этот промпт превращает вашу спецификацию (SPEC.md) в production-ready SQL-миграции, которые можно сразу применить в Supabase.

AI-Архитектор не пишет SQL руками. Он загружает спецификацию + этот промпт в Claude AI и получает:
- Все таблицы с правильными типами данных
- Связи между таблицами (FK с каскадным поведением)
- RLS-политики для каждой таблицы
- Индексы для частых запросов
- Триггеры для автоматического обновления updated_at
- Seed-данные для тестирования

---

## Когда использовать

- После создания SPEC.md — как первый шаг технической реализации
- При добавлении нового модуля в существующий проект
- При рефакторинге схемы БД (миграция с новой структурой)
- Для ревью существующей схемы и генерации недостающих политик

---

## Где загружать

**Claude AI (Web)** — https://claude.ai

1. Открой новый чат (или проект) в Claude AI
2. Загрузи свой файл SPEC.md
3. Скопируй промпт ниже целиком
4. Отправь — Claude сгенерирует полную схему БД в виде SQL-миграций

> **Важно:** Чем детальнее SPEC.md, тем точнее будет схема. Убедись, что спецификация содержит User Stories и описание данных.

---

## Промпт для Claude AI

```
Ты — старший архитектор баз данных PostgreSQL, специализирующийся на Supabase. Пользователь загрузил спецификацию проекта (SPEC.md). Твоя задача — сгенерировать ПОЛНУЮ схему базы данных в виде SQL-миграций.

## ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА

### Структура каждой таблицы
- Первичный ключ: `id UUID DEFAULT gen_random_uuid() PRIMARY KEY`
- Метки времени: `created_at TIMESTAMPTZ DEFAULT now() NOT NULL` и `updated_at TIMESTAMPTZ DEFAULT now() NOT NULL`
- Все текстовые поля — TEXT (не VARCHAR), кроме случаев когда ограничение длины критично
- Все денежные поля — BIGINT (хранение в копейках/центах), НЕ DECIMAL и НЕ FLOAT
- Перечисления — через CHECK constraint или отдельный ENUM type
- Булевы значения — BOOLEAN DEFAULT false NOT NULL (всегда NOT NULL с дефолтом)

### Foreign Keys
- Каждый FK — явное ON DELETE поведение:
  - CASCADE — если дочерняя запись не имеет смысла без родительской (комментарии к задаче)
  - SET NULL — если связь опциональна (задача может потерять исполнителя)
  - RESTRICT — если удаление родителя опасно (пользователь с активными данными)
- FK всегда ссылается на id (UUID) родительской таблицы
- Обоснуй выбор ON DELETE в комментарии

### RLS (Row Level Security)
- ВКЛЮЧАЙ RLS для КАЖДОЙ таблицы без исключений: `ALTER TABLE tablename ENABLE ROW LEVEL SECURITY;`
- Паттерны политик:
  - Пользовательские данные: `auth.uid() = user_id`
  - Публичные данные: SELECT для anon, мутации для владельца
  - Данные организации: проверка через промежуточную таблицу членства
  - Админские данные: проверка роли через `auth.jwt() -> 'user_metadata' ->> 'role'`
- Для каждой таблицы — отдельные политики на SELECT, INSERT, UPDATE, DELETE

### Индексы
- Автоматически на каждый FK-столбец
- На поля, используемые в WHERE и ORDER BY (определи из User Stories)
- Составные индексы для частых комбинаций фильтров
- GIN-индексы для JSONB и полнотекстового поиска (если применимо)

### Триггеры
- Триггер auto_update_updated_at для КАЖДОЙ таблицы (через общую функцию)

### Именование
- Таблицы: snake_case, множественное число (users, projects, task_comments)
- Столбцы: snake_case (user_id, created_at, is_active)
- Индексы: idx_{table}_{column(s)}
- Политики: {table}_{operation}_{role} (tasks_select_owner, tasks_insert_authenticated)
- Триггеры: trg_{table}_{action}

### Формат миграции
- Имя файла: YYYYMMDDHHMMSS_описание.sql (например: 20260410120000_create_users_and_projects.sql)
- Каждая миграция — атомарная логическая единица
- Комментарии: COMMENT ON TABLE и COMMENT ON COLUMN для документации
- SQL-комментарии (--) объясняют ПОЧЕМУ, а не ЧТО

## ПОРЯДОК ГЕНЕРАЦИИ

### 1. Анализ спецификации
- Извлеки все сущности (пользователи, проекты, задачи и т.д.)
- Определи связи между ними (1:1, 1:N, N:M)
- Определи роли пользователей и уровни доступа

### 2. ER-диаграмма (текстовая)
- Покажи все таблицы и их связи в текстовом формате
- Укажи кардинальность (1:N, N:M через junction table)

### 3. SQL-миграции
- Сгенерируй полные CREATE TABLE statements
- Сгенерируй RLS-политики
- Сгенерируй индексы
- Сгенерируй триггеры

### 4. Seed-данные
- Сгенерируй INSERT statements для тестовых данных
- Минимум 3-5 записей на таблицу
- Данные должны быть реалистичными и связанными между собой

### 5. TypeScript-типы
- Сгенерируй интерфейсы TypeScript для каждой таблицы (Row, Insert, Update)

## ФОРМАТ ВЫВОДА

Выведи результат в виде готовых файлов:
1. `supabase/migrations/YYYYMMDDHHMMSS_initial_schema.sql` — основная миграция
2. `supabase/migrations/YYYYMMDDHHMMSS_rls_policies.sql` — все RLS-политики
3. `supabase/migrations/YYYYMMDDHHMMSS_indexes_and_triggers.sql` — индексы и триггеры
4. `supabase/seed.sql` — тестовые данные
5. `src/types/database.ts` — TypeScript-типы

Проанализируй загруженную спецификацию и сгенерируй полную схему БД.
```

---

## Пример результата

Ниже — пример вывода для проекта **TaskFlow** (трекер задач для фрилансеров), компания ООО "Продуктив", домен taskflow.ru.

### ER-диаграмма

```
users (1) ──── (N) projects
users (1) ──── (N) tasks
projects (1) ──── (N) tasks
tasks (1) ──── (N) comments
users (1) ──── (N) comments
projects (N) ──── (M) users  [через project_members]
```

### Миграция: `supabase/migrations/20260410120000_initial_schema.sql`

```sql
-- =============================================
-- TaskFlow: начальная схема базы данных
-- Проект: трекер задач для фрилансеров
-- =============================================

-- Функция автоматического обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Перечисление статусов задач
CREATE TYPE task_status AS ENUM ('backlog', 'todo', 'in_progress', 'review', 'done');

-- Перечисление приоритетов
CREATE TYPE task_priority AS ENUM ('low', 'medium', 'high', 'urgent');

-- Перечисление ролей в проекте
CREATE TYPE project_role AS ENUM ('owner', 'editor', 'viewer');

-- =============================================
-- Таблица: users
-- Расширение auth.users дополнительными полями профиля
-- =============================================
CREATE TABLE users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name TEXT NOT NULL,
  avatar_url TEXT,
  timezone TEXT DEFAULT 'Europe/Moscow' NOT NULL,
  is_onboarded BOOLEAN DEFAULT false NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

COMMENT ON TABLE users IS 'Профили пользователей — расширение auth.users';
COMMENT ON COLUMN users.is_onboarded IS 'Прошёл ли пользователь онбординг';

CREATE TRIGGER trg_users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================
-- Таблица: projects
-- Проекты фрилансера (каждый проект = клиент или направление)
-- =============================================
CREATE TABLE projects (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  color TEXT DEFAULT '#6366f1' NOT NULL,
  is_archived BOOLEAN DEFAULT false NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

COMMENT ON TABLE projects IS 'Проекты — группировка задач по клиентам или направлениям';
COMMENT ON COLUMN projects.color IS 'HEX-цвет для визуального отличия в интерфейсе';

CREATE TRIGGER trg_projects_updated_at
  BEFORE UPDATE ON projects
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================
-- Таблица: project_members
-- Связь N:M между проектами и пользователями
-- =============================================
CREATE TABLE project_members (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role project_role DEFAULT 'viewer' NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  -- Один пользователь может быть в проекте только один раз
  UNIQUE (project_id, user_id)
);

COMMENT ON TABLE project_members IS 'Членство в проектах — junction table для N:M';

CREATE TRIGGER trg_project_members_updated_at
  BEFORE UPDATE ON project_members
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================
-- Таблица: tasks
-- Задачи внутри проектов
-- =============================================
CREATE TABLE tasks (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  creator_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  assignee_id UUID REFERENCES users(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  description TEXT,
  status task_status DEFAULT 'backlog' NOT NULL,
  priority task_priority DEFAULT 'medium' NOT NULL,
  due_date DATE,
  position INTEGER DEFAULT 0 NOT NULL,
  is_archived BOOLEAN DEFAULT false NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

COMMENT ON TABLE tasks IS 'Задачи — основная рабочая единица трекера';
COMMENT ON COLUMN tasks.position IS 'Порядок отображения на доске (drag-and-drop)';
-- assignee_id SET NULL: задача остаётся, даже если исполнитель удалён
-- project_id CASCADE: при удалении проекта удаляются все его задачи

CREATE TRIGGER trg_tasks_updated_at
  BEFORE UPDATE ON tasks
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================
-- Таблица: comments
-- Комментарии к задачам
-- =============================================
CREATE TABLE comments (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  author_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

COMMENT ON TABLE comments IS 'Комментарии к задачам — обсуждение и история';
-- CASCADE: комментарии удаляются вместе с задачей или автором

CREATE TRIGGER trg_comments_updated_at
  BEFORE UPDATE ON comments
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### Миграция: `supabase/migrations/20260410120001_rls_policies.sql`

```sql
-- =============================================
-- RLS-политики для всех таблиц TaskFlow
-- =============================================

-- Включаем RLS на всех таблицах
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE comments ENABLE ROW LEVEL SECURITY;

-- ---- USERS ----
-- Пользователь видит только свой профиль
CREATE POLICY users_select_own ON users
  FOR SELECT USING (auth.uid() = id);

-- Пользователь создаёт только свой профиль
CREATE POLICY users_insert_own ON users
  FOR INSERT WITH CHECK (auth.uid() = id);

-- Пользователь обновляет только свой профиль
CREATE POLICY users_update_own ON users
  FOR UPDATE USING (auth.uid() = id);

-- ---- PROJECTS ----
-- Участник видит проекты, в которых он состоит
CREATE POLICY projects_select_member ON projects
  FOR SELECT USING (
    owner_id = auth.uid()
    OR id IN (
      SELECT project_id FROM project_members WHERE user_id = auth.uid()
    )
  );

-- Только аутентифицированный пользователь создаёт проекты
CREATE POLICY projects_insert_authenticated ON projects
  FOR INSERT WITH CHECK (auth.uid() = owner_id);

-- Только владелец обновляет проект
CREATE POLICY projects_update_owner ON projects
  FOR UPDATE USING (owner_id = auth.uid());

-- Только владелец удаляет проект
CREATE POLICY projects_delete_owner ON projects
  FOR DELETE USING (owner_id = auth.uid());

-- ---- TASKS ----
-- Участник проекта видит задачи проекта
CREATE POLICY tasks_select_member ON tasks
  FOR SELECT USING (
    project_id IN (
      SELECT id FROM projects WHERE owner_id = auth.uid()
      UNION
      SELECT project_id FROM project_members WHERE user_id = auth.uid()
    )
  );

-- Участник проекта (owner/editor) создаёт задачи
CREATE POLICY tasks_insert_member ON tasks
  FOR INSERT WITH CHECK (
    project_id IN (
      SELECT id FROM projects WHERE owner_id = auth.uid()
      UNION
      SELECT project_id FROM project_members
        WHERE user_id = auth.uid() AND role IN ('owner', 'editor')
    )
  );

-- Участник проекта (owner/editor) обновляет задачи
CREATE POLICY tasks_update_member ON tasks
  FOR UPDATE USING (
    project_id IN (
      SELECT id FROM projects WHERE owner_id = auth.uid()
      UNION
      SELECT project_id FROM project_members
        WHERE user_id = auth.uid() AND role IN ('owner', 'editor')
    )
  );

-- Только владелец проекта удаляет задачи
CREATE POLICY tasks_delete_owner ON tasks
  FOR DELETE USING (
    project_id IN (
      SELECT id FROM projects WHERE owner_id = auth.uid()
    )
  );

-- ---- COMMENTS ----
-- Участник проекта видит комментарии к задачам проекта
CREATE POLICY comments_select_member ON comments
  FOR SELECT USING (
    task_id IN (
      SELECT t.id FROM tasks t
      JOIN projects p ON p.id = t.project_id
      LEFT JOIN project_members pm ON pm.project_id = p.id
      WHERE p.owner_id = auth.uid() OR pm.user_id = auth.uid()
    )
  );

-- Аутентифицированный участник проекта добавляет комментарии
CREATE POLICY comments_insert_member ON comments
  FOR INSERT WITH CHECK (
    auth.uid() = author_id
    AND task_id IN (
      SELECT t.id FROM tasks t
      JOIN projects p ON p.id = t.project_id
      LEFT JOIN project_members pm ON pm.project_id = p.id
      WHERE p.owner_id = auth.uid() OR pm.user_id = auth.uid()
    )
  );

-- Автор обновляет свой комментарий
CREATE POLICY comments_update_author ON comments
  FOR UPDATE USING (auth.uid() = author_id);

-- Автор удаляет свой комментарий
CREATE POLICY comments_delete_author ON comments
  FOR DELETE USING (auth.uid() = author_id);
```

### Миграция: `supabase/migrations/20260410120002_indexes_and_triggers.sql`

```sql
-- =============================================
-- Индексы для производительности
-- =============================================

-- FK-индексы (PostgreSQL не создаёт их автоматически)
CREATE INDEX idx_projects_owner_id ON projects(owner_id);
CREATE INDEX idx_project_members_user_id ON project_members(user_id);
CREATE INDEX idx_project_members_project_id ON project_members(project_id);
CREATE INDEX idx_tasks_project_id ON tasks(project_id);
CREATE INDEX idx_tasks_creator_id ON tasks(creator_id);
CREATE INDEX idx_tasks_assignee_id ON tasks(assignee_id);
CREATE INDEX idx_comments_task_id ON comments(task_id);
CREATE INDEX idx_comments_author_id ON comments(author_id);

-- Индексы для частых фильтров
CREATE INDEX idx_tasks_status ON tasks(status) WHERE NOT is_archived;
CREATE INDEX idx_tasks_priority ON tasks(priority) WHERE NOT is_archived;
CREATE INDEX idx_tasks_due_date ON tasks(due_date) WHERE due_date IS NOT NULL AND NOT is_archived;
CREATE INDEX idx_projects_not_archived ON projects(owner_id) WHERE NOT is_archived;

-- Составной индекс: задачи проекта, отсортированные по позиции
CREATE INDEX idx_tasks_project_position ON tasks(project_id, position) WHERE NOT is_archived;
```

### TypeScript-типы (генерируемые)

```typescript
// src/types/database.ts
// Сгенерировано командой: npx supabase gen types typescript --project-id abc123example

export interface Database {
  public: {
    Tables: {
      users: {
        Row: {
          id: string;
          full_name: string;
          avatar_url: string | null;
          timezone: string;
          is_onboarded: boolean;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id: string;
          full_name: string;
          avatar_url?: string | null;
          timezone?: string;
          is_onboarded?: boolean;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          full_name?: string;
          avatar_url?: string | null;
          timezone?: string;
          is_onboarded?: boolean;
        };
      };
      projects: {
        Row: {
          id: string;
          owner_id: string;
          name: string;
          description: string | null;
          color: string;
          is_archived: boolean;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          owner_id: string;
          name: string;
          description?: string | null;
          color?: string;
          is_archived?: boolean;
        };
        Update: {
          name?: string;
          description?: string | null;
          color?: string;
          is_archived?: boolean;
        };
      };
      tasks: {
        Row: {
          id: string;
          project_id: string;
          creator_id: string;
          assignee_id: string | null;
          title: string;
          description: string | null;
          status: 'backlog' | 'todo' | 'in_progress' | 'review' | 'done';
          priority: 'low' | 'medium' | 'high' | 'urgent';
          due_date: string | null;
          position: number;
          is_archived: boolean;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          project_id: string;
          creator_id: string;
          assignee_id?: string | null;
          title: string;
          description?: string | null;
          status?: 'backlog' | 'todo' | 'in_progress' | 'review' | 'done';
          priority?: 'low' | 'medium' | 'high' | 'urgent';
          due_date?: string | null;
          position?: number;
        };
        Update: {
          assignee_id?: string | null;
          title?: string;
          description?: string | null;
          status?: 'backlog' | 'todo' | 'in_progress' | 'review' | 'done';
          priority?: 'low' | 'medium' | 'high' | 'urgent';
          due_date?: string | null;
          position?: number;
          is_archived?: boolean;
        };
      };
      comments: {
        Row: {
          id: string;
          task_id: string;
          author_id: string;
          content: string;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          task_id: string;
          author_id: string;
          content: string;
        };
        Update: {
          content?: string;
        };
      };
    };
    Enums: {
      task_status: 'backlog' | 'todo' | 'in_progress' | 'review' | 'done';
      task_priority: 'low' | 'medium' | 'high' | 'urgent';
      project_role: 'owner' | 'editor' | 'viewer';
    };
  };
}
```

---

## Чеклист после генерации

- [ ] Каждая таблица имеет `id UUID`, `created_at`, `updated_at`
- [ ] RLS включена на ВСЕХ таблицах
- [ ] FK имеют явное ON DELETE поведение
- [ ] Индексы созданы для всех FK и частых фильтров
- [ ] Триггер `update_updated_at` привязан к каждой таблице
- [ ] Именование консистентно (snake_case, множественное число)
- [ ] Миграции названы по формату YYYYMMDDHHMMSS_name.sql
- [ ] TypeScript-типы соответствуют схеме

---

## Следующий шаг

После генерации схемы БД переходи к **2-15 | API Designer** для проектирования API-эндпоинтов на основе созданных таблиц.
