# 5-29 | Определения инструментов (Tool Use) — Справочник структуры

> Reference-документ: что Claude генерирует для определений tools AI-агента.
> Используйте для валидации результата и формулирования требований — не для ручного заполнения.

---

## Философия этого документа

**Вы не пишете определения tools вручную.** Claude сам генерирует их из вашего описания задач агента (через `5-30-AGENT_ARCHITECT_PROMPT.md` или в паре с системным промптом из `5-28`).

Зачем тогда этот справочник?

1. **Валидация** — понять, правильно ли Claude описал каждый tool (имя, description, schema)
2. **Корректировка** — если что-то не так, знать как попросить изменить
3. **Коммуникация** — говорить с Claude на языке "добавь pattern для даты" вместо "tool работает неправильно"
4. **Контроль качества** — проверить, что описания tools не приведут к галлюцинациям и неправильным вызовам

**Правильный workflow:**
```
Вы → описываете что агент должен уметь делать (действия + источники данных)
Claude → генерирует системный промпт + определения tools (через Agent Architect Prompt)
Вы → используете этот справочник чтобы валидировать результат
Claude → вносит правки по вашим замечаниям
```

---

## Что такое Tool Use в Anthropic API

Tool Use — это механизм, позволяющий Claude вызывать внешние функции (API, базу данных, сервисы) во время диалога. Claude решает КОГДА вызвать tool и С КАКИМИ параметрами, но сам вызов выполняет ваш код.

**Терминология Anthropic (НЕ "function calling"):**
- **Tool** — определение инструмента (name, description, input_schema)
- **Tool Use** — решение Claude вызвать инструмент (tool_use content block)
- **Tool Result** — ответ вашего кода на вызов инструмента (tool_result)

**Поток данных:**
```
1. Вы отправляете запрос + список tools → Claude API
2. Claude решает, какой tool вызвать → возвращает tool_use block
3. Ваш код выполняет вызов → отправляет tool_result обратно
4. Claude формирует финальный ответ на основе tool_result
```

---

## Структура определения Tool

**Что Claude генерирует:** объект с тремя полями (name, description, input_schema) для каждого инструмента.

**Как проверить:** сравните с этим шаблоном. Каждый tool должен иметь все три поля, правильное именование и полную JSON Schema. Если чего-то не хватает — попросите дополнить.

```json
{
  "name": "snake_case_имя",
  "description": "Детальное описание ЧТО делает и КОГДА использовать",
  "input_schema": {
    "type": "object",
    "properties": {
      // JSON Schema для входных параметров
    },
    "required": ["обязательные_поля"]
  }
}
```

### Правила именования (проверьте в сгенерированных tools)

| Правило | Пример | Антипример |
|---------|--------|------------|
| snake_case | `get_tasks` | `getTasks`, `Get-Tasks` |
| Глагол + существительное | `create_task` | `task_creator` |
| Конкретность | `search_projects_by_status` | `search` |
| Максимум 3 слова | `get_project_stats` | `get_detailed_project_statistics_report` |

**Промпт для исправления:**
```
Переименуй инструмент [X] по правилам: snake_case, глагол + существительное, максимум 3 слова.
```

### Правила описания (проверьте description каждого tool)

Description — это ГЛАВНОЕ, что влияет на решение Claude использовать tool. Плохое описание = неправильные вызовы.

**Формат описания:**
```
[Что делает — 1 предложение]
[Когда использовать — 1-2 предложения]
[Что возвращает — 1 предложение]
[Ограничения / предупреждения]
```

---

## Эталонная структура, которую должен сгенерировать Claude

```json
{
  "name": "[verb]_[resource]",
  "description": "[Что делает]. Используй когда [условие]. Возвращает [формат]. Не используй для [антипаттерн].",
  "input_schema": {
    "type": "object",
    "properties": {
      "required_param": {
        "type": "string",
        "description": "Описание параметра. Формат: [формат]. Пример: [пример]"
      },
      "optional_param": {
        "type": "string",
        "description": "Описание. По умолчанию: [значение]",
        "enum": ["value1", "value2", "value3"]
      },
      "numeric_param": {
        "type": "integer",
        "description": "Описание. Диапазон: [min]-[max]",
        "minimum": 1,
        "maximum": 100
      },
      "date_param": {
        "type": "string",
        "description": "Дата в формате YYYY-MM-DD. Пример: 2026-04-10",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      }
    },
    "required": ["required_param"]
  }
}
```

---

## Что Claude вернёт для TaskFlow — пример 1: get_tasks

Ниже — пример определения, которое Claude сгенерирует, если вы опишете агента управления задачами в TaskFlow. Используйте как образец для сравнения с тем, что получите для своего проекта.

Получение списка задач пользователя с фильтрацией.

### Определение

```json
{
  "name": "get_tasks",
  "description": "Получает список задач пользователя из базы данных TaskFlow. Используй когда пользователь спрашивает о своих задачах, запрашивает список дел или хочет узнать статус задач. Возвращает массив задач с полями: id, title, status, priority, due_date, project_name, assignee. Не используй для получения статистики по проекту — для этого есть get_project_stats.",
  "input_schema": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "string",
        "description": "UUID пользователя. Берётся из контекста сессии. Пример: 550e8400-e29b-41d4-a716-446655440000"
      },
      "status": {
        "type": "string",
        "description": "Фильтр по статусу задачи. По умолчанию: all (все статусы)",
        "enum": ["all", "open", "in_progress", "review", "completed", "overdue"]
      },
      "priority": {
        "type": "string",
        "description": "Фильтр по приоритету. По умолчанию: all",
        "enum": ["all", "critical", "high", "medium", "low"]
      },
      "project_id": {
        "type": "string",
        "description": "UUID проекта для фильтрации. Если не указан — задачи из всех проектов"
      },
      "due_date_from": {
        "type": "string",
        "description": "Начало периода (включительно). Формат: YYYY-MM-DD",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "due_date_to": {
        "type": "string",
        "description": "Конец периода (включительно). Формат: YYYY-MM-DD",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "limit": {
        "type": "integer",
        "description": "Максимальное количество задач в ответе. По умолчанию: 20. Максимум: 100",
        "minimum": 1,
        "maximum": 100
      },
      "sort_by": {
        "type": "string",
        "description": "Поле для сортировки. По умолчанию: due_date",
        "enum": ["due_date", "priority", "created_at", "updated_at", "title"]
      }
    },
    "required": ["user_id"]
  }
}
```

### Пример вызова Claude

```json
// Пользователь: "Покажи мои срочные задачи на эту неделю"

// Claude возвращает tool_use:
{
  "type": "tool_use",
  "id": "toolu_01A09q90qw90lq917835lq",
  "name": "get_tasks",
  "input": {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "priority": "critical",
    "due_date_from": "2026-04-06",
    "due_date_to": "2026-04-12",
    "sort_by": "due_date"
  }
}
```

### Пример tool_result

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01A09q90qw90lq917835lq",
  "content": [
    {
      "type": "text",
      "text": "{\"tasks\": [{\"id\": \"task_001\", \"title\": \"Подготовить презентацию для клиента\", \"status\": \"in_progress\", \"priority\": \"critical\", \"due_date\": \"2026-04-10\", \"project_name\": \"Редизайн сайта\", \"assignee\": \"Иван Петров\"}, {\"id\": \"task_002\", \"title\": \"Ревью кода модуля оплаты\", \"status\": \"open\", \"priority\": \"critical\", \"due_date\": \"2026-04-11\", \"project_name\": \"Интернет-магазин\", \"assignee\": \"Иван Петров\"}], \"total\": 2}"
    }
  ]
}
```

### Реализация на TypeScript (серверная сторона)

```typescript
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY!
);

interface GetTasksInput {
  user_id: string;
  status?: 'all' | 'open' | 'in_progress' | 'review' | 'completed' | 'overdue';
  priority?: 'all' | 'critical' | 'high' | 'medium' | 'low';
  project_id?: string;
  due_date_from?: string;
  due_date_to?: string;
  limit?: number;
  sort_by?: 'due_date' | 'priority' | 'created_at' | 'updated_at' | 'title';
}

async function handleGetTasks(input: GetTasksInput) {
  let query = supabase
    .from('tasks')
    .select('id, title, status, priority, due_date, project:projects(name), assignee:profiles(full_name)')
    .eq('assignee_id', input.user_id);

  if (input.status && input.status !== 'all') {
    if (input.status === 'overdue') {
      query = query.lt('due_date', new Date().toISOString()).neq('status', 'completed');
    } else {
      query = query.eq('status', input.status);
    }
  }

  if (input.priority && input.priority !== 'all') {
    query = query.eq('priority', input.priority);
  }

  if (input.project_id) {
    query = query.eq('project_id', input.project_id);
  }

  if (input.due_date_from) {
    query = query.gte('due_date', input.due_date_from);
  }

  if (input.due_date_to) {
    query = query.lte('due_date', input.due_date_to);
  }

  const sortField = input.sort_by || 'due_date';
  query = query.order(sortField, { ascending: true });

  const limit = Math.min(input.limit || 20, 100);
  query = query.limit(limit);

  const { data, error, count } = await query;

  if (error) {
    return { error: error.message };
  }

  return { tasks: data, total: count };
}
```

---

## Что Claude вернёт для TaskFlow — пример 2: create_task

Создание новой задачи. Обратите внимание на подтверждение перед созданием — Claude должен это зашить и в description tool, и в системный промпт.

### Определение

```json
{
  "name": "create_task",
  "description": "Создаёт новую задачу в проекте TaskFlow. Используй ТОЛЬКО когда пользователь явно просит создать задачу. ОБЯЗАТЕЛЬНО подтверди название и параметры задачи перед вызовом этого инструмента. Возвращает созданную задачу с id. Не используй для обновления существующих задач — для этого есть update_task.",
  "input_schema": {
    "type": "object",
    "properties": {
      "project_id": {
        "type": "string",
        "description": "UUID проекта, в который добавляется задача. Пример: proj_550e8400-e29b-41d4"
      },
      "title": {
        "type": "string",
        "description": "Название задачи. Максимум 200 символов. Должно быть конкретным и начинаться с глагола. Пример: 'Подготовить макет главной страницы'",
        "maxLength": 200
      },
      "description": {
        "type": "string",
        "description": "Подробное описание задачи. Что нужно сделать, критерии приёмки. Максимум 2000 символов",
        "maxLength": 2000
      },
      "assignee_id": {
        "type": "string",
        "description": "UUID исполнителя. Если не указан — задача без исполнителя"
      },
      "priority": {
        "type": "string",
        "description": "Приоритет задачи. По умолчанию: medium",
        "enum": ["critical", "high", "medium", "low"],
        "default": "medium"
      },
      "due_date": {
        "type": "string",
        "description": "Дедлайн в формате YYYY-MM-DD. Должен быть в будущем",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "tags": {
        "type": "array",
        "description": "Массив тегов для категоризации. Пример: ['frontend', 'дизайн']",
        "items": {
          "type": "string"
        },
        "maxItems": 10
      }
    },
    "required": ["project_id", "title"]
  }
}
```

### Паттерн подтверждения

Claude должен сначала показать параметры пользователю и попросить подтверждение:

```
Пользователь: "Создай задачу — сделать лендинг для промо-акции, дедлайн через неделю, высокий приоритет"

Claude (перед вызовом tool):
"Создаю задачу с параметрами:
- Название: Сделать лендинг для промо-акции
- Приоритет: Высокий
- Дедлайн: 2026-04-17
- Проект: [текущий проект]

Всё верно? Подтвердите, и я создам задачу."

Пользователь: "Да"

Claude (вызывает tool): create_task({ ... })
```

### Реализация на TypeScript

```typescript
interface CreateTaskInput {
  project_id: string;
  title: string;
  description?: string;
  assignee_id?: string;
  priority?: 'critical' | 'high' | 'medium' | 'low';
  due_date?: string;
  tags?: string[];
}

async function handleCreateTask(input: CreateTaskInput) {
  // Валидация дедлайна
  if (input.due_date) {
    const dueDate = new Date(input.due_date);
    if (dueDate <= new Date()) {
      return { error: 'Дедлайн должен быть в будущем' };
    }
  }

  // Проверка существования проекта
  const { data: project } = await supabase
    .from('projects')
    .select('id, name')
    .eq('id', input.project_id)
    .single();

  if (!project) {
    return { error: 'Проект не найден' };
  }

  // Создание задачи
  const { data, error } = await supabase
    .from('tasks')
    .insert({
      project_id: input.project_id,
      title: input.title,
      description: input.description || '',
      assignee_id: input.assignee_id || null,
      priority: input.priority || 'medium',
      due_date: input.due_date || null,
      tags: input.tags || [],
      status: 'open',
      created_at: new Date().toISOString(),
    })
    .select()
    .single();

  if (error) {
    return { error: error.message };
  }

  return {
    task: data,
    message: `Задача "${data.title}" создана в проекте "${project.name}"`,
  };
}
```

---

## Что Claude вернёт для TaskFlow — пример 3: get_project_stats

Получение агрегированной статистики по проекту.

### Определение

```json
{
  "name": "get_project_stats",
  "description": "Получает агрегированную статистику по проекту TaskFlow: количество задач по статусам, прогресс в процентах, загруженность участников, просроченные задачи. Используй когда пользователь спрашивает о состоянии проекта, прогрессе или проблемах. Возвращает объект со всеми метриками. Не используй для получения списка конкретных задач — для этого есть get_tasks.",
  "input_schema": {
    "type": "object",
    "properties": {
      "project_id": {
        "type": "string",
        "description": "UUID проекта. Пример: proj_550e8400-e29b-41d4"
      },
      "period": {
        "type": "string",
        "description": "Период анализа. По умолчанию: all_time",
        "enum": ["this_week", "this_month", "last_30_days", "last_90_days", "all_time"]
      },
      "include_team_breakdown": {
        "type": "boolean",
        "description": "Включить разбивку по участникам команды. По умолчанию: false",
        "default": false
      },
      "compare_with_previous": {
        "type": "boolean",
        "description": "Сравнить с предыдущим аналогичным периодом. По умолчанию: false",
        "default": false
      }
    },
    "required": ["project_id"]
  }
}
```

### Пример вызова

```json
// Пользователь: "Как дела с проектом Редизайн? Покажи статистику за месяц и сравни с прошлым"

{
  "type": "tool_use",
  "id": "toolu_02B19r91rw91mr928846mr",
  "name": "get_project_stats",
  "input": {
    "project_id": "proj_abc123",
    "period": "this_month",
    "include_team_breakdown": true,
    "compare_with_previous": true
  }
}
```

### Пример tool_result

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_02B19r91rw91mr928846mr",
  "content": [
    {
      "type": "text",
      "text": "{\"project\": {\"name\": \"Редизайн сайта\", \"progress\": 68, \"deadline\": \"2026-05-15\"}, \"tasks\": {\"total\": 45, \"completed\": 31, \"in_progress\": 8, \"open\": 4, \"overdue\": 2}, \"team\": [{\"name\": \"Иван Петров\", \"tasks_assigned\": 12, \"tasks_completed\": 9, \"avg_completion_hours\": 16}, {\"name\": \"Мария Сидорова\", \"tasks_assigned\": 15, \"tasks_completed\": 11, \"avg_completion_hours\": 22}], \"comparison\": {\"tasks_completed_change\": 15, \"avg_speed_change\": -8}, \"health\": \"on_track\"}"
    }
  ]
}
```

### Реализация на TypeScript

```typescript
interface GetProjectStatsInput {
  project_id: string;
  period?: 'this_week' | 'this_month' | 'last_30_days' | 'last_90_days' | 'all_time';
  include_team_breakdown?: boolean;
  compare_with_previous?: boolean;
}

async function handleGetProjectStats(input: GetProjectStatsInput) {
  const periodFilter = getPeriodDateRange(input.period || 'all_time');

  // Основная статистика
  const { data: tasks } = await supabase
    .from('tasks')
    .select('id, status, priority, due_date, assignee_id, created_at, completed_at')
    .eq('project_id', input.project_id)
    .gte('created_at', periodFilter.from)
    .lte('created_at', periodFilter.to);

  if (!tasks || tasks.length === 0) {
    return { error: 'Нет данных за указанный период' };
  }

  const stats = {
    total: tasks.length,
    completed: tasks.filter(t => t.status === 'completed').length,
    in_progress: tasks.filter(t => t.status === 'in_progress').length,
    open: tasks.filter(t => t.status === 'open').length,
    overdue: tasks.filter(t =>
      t.due_date &&
      new Date(t.due_date) < new Date() &&
      t.status !== 'completed'
    ).length,
  };

  const progress = Math.round((stats.completed / stats.total) * 100);

  const result: Record<string, unknown> = {
    project: { progress },
    tasks: stats,
    health: stats.overdue > stats.total * 0.2 ? 'at_risk' : 'on_track',
  };

  // Разбивка по команде
  if (input.include_team_breakdown) {
    const { data: teamStats } = await supabase
      .rpc('get_team_task_stats', {
        p_project_id: input.project_id,
        p_from: periodFilter.from,
        p_to: periodFilter.to,
      });
    result.team = teamStats;
  }

  // Сравнение с предыдущим периодом
  if (input.compare_with_previous) {
    const prevPeriod = getPreviousPeriodRange(input.period || 'all_time');
    const { data: prevTasks } = await supabase
      .from('tasks')
      .select('id, status')
      .eq('project_id', input.project_id)
      .gte('created_at', prevPeriod.from)
      .lte('created_at', prevPeriod.to);

    const prevCompleted = prevTasks?.filter(t => t.status === 'completed').length || 0;
    result.comparison = {
      tasks_completed_change: stats.completed - prevCompleted,
      trend: stats.completed > prevCompleted ? 'improving' : 'declining',
    };
  }

  return result;
}

function getPeriodDateRange(period: string) {
  const now = new Date();
  const to = now.toISOString();
  let from: string;

  switch (period) {
    case 'this_week':
      from = new Date(now.setDate(now.getDate() - now.getDay())).toISOString();
      break;
    case 'this_month':
      from = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
      break;
    case 'last_30_days':
      from = new Date(now.setDate(now.getDate() - 30)).toISOString();
      break;
    case 'last_90_days':
      from = new Date(now.setDate(now.getDate() - 90)).toISOString();
      break;
    default:
      from = '2020-01-01T00:00:00.000Z';
  }

  return { from, to };
}

function getPreviousPeriodRange(period: string) {
  // Вычисляет предыдущий аналогичный период для сравнения
  const range = getPeriodDateRange(period);
  const duration = new Date(range.to).getTime() - new Date(range.from).getTime();
  return {
    from: new Date(new Date(range.from).getTime() - duration).toISOString(),
    to: range.from,
  };
}
```

---

## Интеграция с Claude API: полный пример

```typescript
import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic();

// Определение всех tools
const tools: Anthropic.Tool[] = [
  {
    name: 'get_tasks',
    description: 'Получает список задач пользователя из TaskFlow...',
    input_schema: {
      type: 'object' as const,
      properties: {
        user_id: { type: 'string', description: 'UUID пользователя' },
        status: { type: 'string', enum: ['all', 'open', 'in_progress', 'completed', 'overdue'] },
        // ... остальные параметры
      },
      required: ['user_id'],
    },
  },
  {
    name: 'create_task',
    description: 'Создаёт новую задачу в проекте TaskFlow...',
    input_schema: {
      type: 'object' as const,
      properties: {
        project_id: { type: 'string', description: 'UUID проекта' },
        title: { type: 'string', description: 'Название задачи' },
        // ... остальные параметры
      },
      required: ['project_id', 'title'],
    },
  },
  {
    name: 'get_project_stats',
    description: 'Получает агрегированную статистику по проекту...',
    input_schema: {
      type: 'object' as const,
      properties: {
        project_id: { type: 'string', description: 'UUID проекта' },
        period: { type: 'string', enum: ['this_week', 'this_month', 'last_30_days', 'all_time'] },
        // ... остальные параметры
      },
      required: ['project_id'],
    },
  },
];

// Маппинг tool name → handler
const toolHandlers: Record<string, (input: unknown) => Promise<unknown>> = {
  get_tasks: handleGetTasks,
  create_task: handleCreateTask,
  get_project_stats: handleGetProjectStats,
};

// Основной цикл обработки
async function processUserMessage(userMessage: string, userId: string) {
  const messages: Anthropic.MessageParam[] = [
    { role: 'user', content: userMessage },
  ];

  let response = await anthropic.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 4096,
    system: SYSTEM_PROMPT, // Из шаблона 5-28
    tools,
    messages,
  });

  // Цикл обработки tool calls
  while (response.stop_reason === 'tool_use') {
    const toolUseBlocks = response.content.filter(
      (block): block is Anthropic.ToolUseBlock => block.type === 'tool_use'
    );

    const toolResults: Anthropic.ToolResultBlockParam[] = [];

    for (const toolUse of toolUseBlocks) {
      const handler = toolHandlers[toolUse.name];

      if (!handler) {
        toolResults.push({
          type: 'tool_result',
          tool_use_id: toolUse.id,
          content: JSON.stringify({ error: `Unknown tool: ${toolUse.name}` }),
          is_error: true,
        });
        continue;
      }

      try {
        const result = await handler(toolUse.input);
        toolResults.push({
          type: 'tool_result',
          tool_use_id: toolUse.id,
          content: JSON.stringify(result),
        });
      } catch (err) {
        toolResults.push({
          type: 'tool_result',
          tool_use_id: toolUse.id,
          content: JSON.stringify({ error: (err as Error).message }),
          is_error: true,
        });
      }
    }

    // Добавляем ответ Claude и результаты tools в историю
    messages.push({ role: 'assistant', content: response.content });
    messages.push({ role: 'user', content: toolResults });

    // Следующий запрос к Claude
    response = await anthropic.messages.create({
      model: 'claude-sonnet-4-6',
      max_tokens: 4096,
      system: SYSTEM_PROMPT,
      tools,
      messages,
    });
  }

  // Извлекаем текстовый ответ
  const textBlock = response.content.find(
    (block): block is Anthropic.TextBlock => block.type === 'text'
  );

  return textBlock?.text || 'Нет ответа';
}
```

---

## Чек-лист валидации (после генерации)

Когда Claude сгенерировал определения tools — пройдитесь по этому чек-листу для КАЖДОГО tool. Если что-то не так, попросите Claude исправить.

| # | Проверка | Пройдено? |
|---|----------|-----------|
| 1 | Имя в snake_case, глагол + существительное | ☐ |
| 2 | Description содержит "когда" и "когда НЕ" | ☐ |
| 3 | Все обязательные поля в required | ☐ |
| 4 | Каждое property имеет description с примером | ☐ |
| 5 | Строки с форматом имеют pattern (даты, UUID) | ☐ |
| 6 | Числа имеют minimum/maximum | ☐ |
| 7 | Enum для полей с фиксированным набором значений | ☐ |
| 8 | Destructive tools помечены в description | ☐ |
| 9 | Handler обрабатывает ошибки и возвращает { error } | ☐ |
| 10 | Tool протестирован с реальными запросами | ☐ |

**Если найдена проблема — промпт для исправления:**
```
В определении tool [X] проблема: [что не так].
Исправь и верни полное определение с name, description, input_schema.
```

---

## Типичные ошибки

### 1. Слишком короткое description
**Плохо:** `"description": "Gets tasks"`
**Хорошо:** `"description": "Получает список задач пользователя. Используй когда пользователь спрашивает о задачах. Не используй для статистики проекта."`

### 2. Нет required
**Проблема:** Claude может вызвать tool без критических параметров.
**Решение:** Всегда указывайте минимально необходимые параметры в required.

### 3. Нет обработки ошибок в handler
**Проблема:** При ошибке БД Claude получает необработанное исключение.
**Решение:** Всегда try/catch и возврат `{ error: "human-readable message" }`.

### 4. Слишком много tools (> 15)
**Проблема:** Claude начинает путаться, вызывает не те tools.
**Решение:** Группируйте логику. Вместо 5 отдельных `get_*` — один `search` с параметром `resource`.

---

## Workflow: как создать определения tools за 15 минут

```
ШАГ 1: Составьте список действий агента
  ↓ Что агент должен уметь делать? (get, create, update, search...)
    Из каких источников данных?
  
ШАГ 2: Откройте Claude AI (web)
  ↓ Загрузите 2 файла:
  • Ваше описание агента и действий
  • 5-30-AGENT_ARCHITECT_PROMPT.md (из toolkit)
  
ШАГ 3: Промпт:
  "Сгенерируй полные определения tools для этого агента:
   name + description + input_schema с pattern, enum, minimum/maximum.
   Добавь TypeScript handlers для каждого tool."
  
ШАГ 4: Получите результат
  ↓ Claude вернёт JSON-определения + TypeScript код обработчиков
  
ШАГ 5: Валидация (этот документ)
  ↓ Пройдитесь по чек-листу выше для КАЖДОГО tool
  
ШАГ 6: Если нужны правки — используйте "Промпт для исправления"
  
ШАГ 7: Подключите к Claude API через Anthropic SDK
  ↓ Протестируйте на 3-5 реальных запросах, проверьте что Claude
    выбирает правильный tool в каждой ситуации
```

**Итог:** вы не написали ни одного JSON Schema руками. Вы описали действия, валидировали результат, дали правки. Это роль архитектора AI-агентов.

---

## Связанные материалы

- **5-28** — Шаблон системного промпта (куда включаются описания tools)
- **5-30** — Промпт для проектирования полного AI-агента (генератор)
- **5-31** — Тестирование tool use: правильно ли агент выбирает инструменты

---

*AI-Архитектор | Модуль 5: AI-агенты | Все примеры — вымышленный продукт TaskFlow (ООО "Продуктив")*
