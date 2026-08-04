# 4-22 | Code Review Prompt — Ревью кода после сборки

> **Тип:** Instruction
> **Когда использовать:** После завершения автономной сборки (Kickoff) или после реализации крупной фичи
> **Результат:** Список проблем с приоритетами и конкретными исправлениями

---

## Философия этого документа

Этот файл — **готовый промпт для Claude Code**. Вы не пишете его сами — копируете и используете.

**Принцип работы:**
- Вы — архитектор и коммуникатор
- Claude Code — исполнитель: читает промпт, делает работу
- Ваша задача — указать scope ревью и скопировать правильный промпт

**Workflow:**
```
Вы → копируете промпт → вставляете в Claude Code (VS Code)
       ↓
       указываете, что ревьюить (всё / конкретная фича / директория)
       ↓
Claude Code → проходит по коду, выдаёт структурированный отчёт
       ↓
Вы → получаете список проблем → правите по приоритетам
```

Промпт уже отлажен. Не нужно его улучшать с первого раза — просто используйте.

---

## Что это такое

Промпт для запуска code review через Claude Code. Проверяет код по 8 категориям: TypeScript-ошибки, безопасность, производительность, стилевая консистентность, мёртвый код, обработка ошибок, доступность, структура проекта.

**Важно:** Это НЕ замена security review (см. 4-23). Code review проверяет качество кода, security review — уязвимости.

---

## Промпт для копирования

```
Проведи полный code review проекта. Проверь каждую категорию ниже и составь отчёт.

## Категории проверки

### 1. TypeScript строгость
- Нет ли `any` типов (кроме обоснованных случаев)
- Все функции имеют явные return types
- Интерфейсы вместо inline types для переиспользуемых структур
- Нет `// @ts-ignore` или `// @ts-expect-error` без комментария
- Запусти: tsc --noEmit и покажи все ошибки

### 2. Обработка ошибок
- Все async функции обёрнуты в try/catch
- Server Actions возвращают { success, error } — не бросают исключения
- API routes возвращают правильные HTTP-статусы (400, 401, 403, 404, 500)
- Пользователь видит понятные сообщения об ошибках, не stack traces
- Сетевые ошибки обрабатываются (fetch может упасть)

### 3. Производительность
- Нет N+1 запросов к базе (цикл с запросом внутри)
- Большие списки используют пагинацию
- Изображения оптимизированы (next/image)
- Нет лишних ререндеров (проверь зависимости useEffect)
- dynamic imports для тяжёлых компонентов

### 4. Стилевая консистентность
- Единый паттерн именования файлов (kebab-case для файлов, PascalCase для компонентов)
- Единый паттерн импортов (абсолютные через @/)
- Tailwind v4 — нет устаревших v3 классов
- shadcn/ui компоненты используются консистентно

### 5. Мёртвый код
- Неиспользуемые импорты
- Закомментированный код (удалить или объяснить зачем)
- Неиспользуемые переменные и функции
- Файлы, которые нигде не импортируются
- Console.log оставленные после дебага

### 6. Структура проекта
- Файлы в правильных папках по CLAUDE.md
- Нет бизнес-логики в компонентах (вынесено в actions/utils)
- Нет дублирования кода (DRY)
- Общие утилиты вынесены в src/lib/

### 7. Доступность (a11y)
- Формы имеют label для каждого input
- Кнопки имеют aria-label если нет текста
- Правильная семантика (button для действий, a для навигации)
- Контраст текста достаточный

### 8. Соответствие спецификации
- Все фичи из SPEC.md реализованы
- Edge cases из спецификации обработаны
- UI соответствует описанию экранов

## Формат отчёта

Для каждой найденной проблемы:
- **Файл:** путь к файлу
- **Строка:** номер строки
- **Категория:** [TypeScript|Errors|Perf|Style|DeadCode|Structure|A11y|Spec]
- **Серьёзность:** CRITICAL / WARNING / INFO
- **Проблема:** что не так
- **Исправление:** конкретный код или инструкция

После отчёта — исправь все CRITICAL и WARNING проблемы. INFO — только перечисли.
```

---

## Пример результата review для TaskFlow

```markdown
# Code Review Report — TaskFlow

Дата: 2026-04-10
Файлов проверено: 47
Проблем найдено: 12 (3 CRITICAL, 5 WARNING, 4 INFO)

---

## CRITICAL

### 1. Отсутствует обработка ошибок в Server Action
- **Файл:** src/app/actions/tasks.ts
- **Строка:** 23
- **Категория:** Errors
- **Проблема:** createTask() не обёрнута в try/catch. Если Supabase недоступен — пользователь увидит необработанную ошибку.
- **Исправление:**
```typescript
// БЫЛО
export async function createTask(data: TaskInput) {
  const supabase = await createClient()
  const { data: task } = await supabase
    .from('tasks')
    .insert(data)
    .select()
    .single()
  return task
}

// СТАЛО
export async function createTask(data: TaskInput) {
  try {
    const supabase = await createClient()
    const { data: task, error } = await supabase
      .from('tasks')
      .insert(data)
      .select()
      .single()

    if (error) {
      return { success: false, error: error.message }
    }

    revalidatePath('/tasks')
    return { success: true, data: task }
  } catch (e) {
    return { success: false, error: 'Не удалось создать задачу' }
  }
}
```

### 2. Тип `any` в ключевом интерфейсе
- **Файл:** src/types/database.ts
- **Строка:** 15
- **Категория:** TypeScript
- **Проблема:** `metadata: any` — потенциальный источник runtime ошибок
- **Исправление:**
```typescript
// БЫЛО
metadata: any

// СТАЛО
metadata: Record<string, string | number | boolean> | null
```

### 3. N+1 запрос при загрузке проектов
- **Файл:** src/app/(dashboard)/projects/page.tsx
- **Строка:** 18
- **Категория:** Perf
- **Проблема:** Для каждого проекта делается отдельный запрос на подсчёт задач
- **Исправление:**
```typescript
// БЫЛО
const projects = await getProjects()
for (const project of projects) {
  project.taskCount = await getTaskCount(project.id)
}

// СТАЛО — один запрос с подсчётом
const { data: projects } = await supabase
  .from('projects')
  .select('*, tasks(count)')
  .eq('user_id', userId)
```

---

## WARNING

### 4. Console.log в production коде
- **Файл:** src/lib/supabase/client.ts
- **Строка:** 8
- **Категория:** DeadCode
- **Проблема:** `console.log('Supabase client created')` — дебаг-лог
- **Исправление:** Удалить строку

### 5. Неиспользуемый импорт
- **Файл:** src/app/(dashboard)/tasks/page.tsx
- **Строка:** 3
- **Категория:** DeadCode
- **Проблема:** `import { formatDate } from '@/lib/utils'` — нигде не используется
- **Исправление:** Удалить импорт

### 6. Отсутствует aria-label на иконке-кнопке
- **Файл:** src/components/tasks/TaskCard.tsx
- **Строка:** 42
- **Категория:** A11y
- **Проблема:** `<Button size="icon"><Trash2 /></Button>` без aria-label
- **Исправление:** `<Button size="icon" aria-label="Удалить задачу"><Trash2 /></Button>`

### 7. Устаревший класс Tailwind v3
- **Файл:** src/components/layout/Sidebar.tsx
- **Строка:** 11
- **Категория:** Style
- **Проблема:** `bg-opacity-50` — в Tailwind v4 используется `bg-black/50`
- **Исправление:** Заменить `bg-gray-900 bg-opacity-50` на `bg-gray-900/50`

### 8. Inline type вместо интерфейса
- **Файл:** src/app/actions/projects.ts
- **Строка:** 7
- **Категория:** TypeScript
- **Проблема:** Один и тот же тип `{ name: string; color: string; deadline: Date }` повторяется в 3 функциях
- **Исправление:** Вынести в `src/types/project.ts` как `ProjectInput`

---

## INFO

### 9-12.
- Файл README.md не обновлён после добавления фич
- Несколько TODO-комментариев без тикетов
- Можно объединить два похожих компонента (TaskCard и TaskRow)
- Рекомендуется добавить loading.tsx для каждого route segment
```

---

## Автоматические команды для быстрой проверки

Запусти эти команды перед полным review для быстрой оценки:

```bash
# TypeScript ошибки
npx tsc --noEmit 2>&1 | head -50

# Поиск any типов
grep -rn ": any" src/ --include="*.ts" --include="*.tsx" | grep -v node_modules

# Поиск console.log
grep -rn "console\.\(log\|debug\|info\)" src/ --include="*.ts" --include="*.tsx"

# Поиск @ts-ignore
grep -rn "@ts-ignore\|@ts-expect-error" src/ --include="*.ts" --include="*.tsx"

# Неиспользуемые экспорты (приблизительно)
grep -rn "^export " src/lib/ --include="*.ts" | while read line; do
  func=$(echo "$line" | grep -oP '(?<=export (function|const) )\w+')
  if [ -n "$func" ]; then
    count=$(grep -rn "$func" src/ --include="*.ts" --include="*.tsx" | wc -l)
    if [ "$count" -le 1 ]; then
      echo "POSSIBLY UNUSED: $line"
    fi
  fi
done

# Поиск устаревших классов Tailwind v3
grep -rn "bg-opacity-\|text-opacity-\|border-opacity-" src/ --include="*.tsx"
```

---

## Когда запускать

| Ситуация | Нужен review? |
|----------|---------------|
| После полной автономной сборки (Kickoff) | Да, обязательно |
| После добавления крупной фичи (5+ файлов) | Да |
| После исправления бага | Нет (достаточно проверить конкретный файл) |
| Перед деплоем в production | Да + Security Review (4-23) |
| После рефакторинга | Да |

---

*После code review запусти [4-23 Security Review](4-23-SECURITY_REVIEW_PROMPT.md) перед деплоем.*
