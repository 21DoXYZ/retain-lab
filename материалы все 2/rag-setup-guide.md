# 5-32 | Руководство: Настройка RAG с Supabase pgvector

> Полное руководство по настройке Retrieval-Augmented Generation: векторные эмбеддинги, хранение в pgvector, семантический поиск, инжекция контекста в промпт AI-агента.

---

## Философия этого документа

Этот файл — **загружаемый reference + пошаговая инструкция при ручной работе**. Вы не собираете RAG-пайплайн руками с нуля — вы используете его как:

1. **Reference для Claude** — загрузить в проект, чтобы Claude сам развернул RAG по правильной архитектуре (pgvector, правильные размерности, корректные индексы)
2. **Пошаговая инструкция** — когда вы хотите сделать вручную или проверить результат Claude
3. **Чек-лист архитектурных решений** — какие размерности эмбеддингов, какой размер чанков, какой top_k при retrieval

**Принцип работы:**
- Вы — архитектор: решаете, нужен ли RAG, какие документы в базе знаний, какого качества
- Claude Code — исполнитель: создаёт таблицы, пишет функции matching, настраивает инжекцию
- Этот документ — общий язык между вами

**Как применять:**
```
Сценарий 1: Claude разворачивает RAG
  Вы → "настрой RAG по гайду 5-32 для базы знаний X" → Claude следует инструкции

Сценарий 2: Вы разворачиваете сами
  Вы → открываете файл → идёте по шагам → копируете SQL и код

Сценарий 3: Отладка
  Claude/Вы → видите что retrieval возвращает нерелевантные документы → сверяете с разделом про chunking и top_k
```

---

## Что такое RAG и зачем это нужно

RAG (Retrieval-Augmented Generation) решает главную проблему AI-агентов: **ограниченные знания**.

**Без RAG:**
- Агент знает только то, что есть в системном промпте
- Системный промпт ограничен (~10,000 токенов без потери качества)
- Нельзя обновлять знания без изменения промпта
- Агент выдумывает ответы на вопросы, которых не знает

**С RAG:**
- Агент ищет релевантную информацию в базе знаний перед ответом
- База знаний может быть любого размера (тысячи документов)
- Обновление знаний = добавление документов, не изменение промпта
- Агент отвечает на основе реальных данных, не фантазий

**Как работает:**
```
Запрос пользователя
        │
        ▼
  Генерация эмбеддинга запроса (текст → вектор [1536 чисел])
        │
        ▼
  Поиск похожих документов в pgvector (cosine similarity)
        │
        ▼
  Топ-3 релевантных фрагмента
        │
        ▼
  Инжекция в системный промпт как контекст
        │
        ▼
  Claude генерирует ответ НА ОСНОВЕ найденных документов
```

---

## Архитектура

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│ Документация │     │ Пользователь  │     │ Claude API       │
│ (источник)   │     │ (запрос)      │     │ (генерация)      │
└──────┬───────┘     └──────┬────────┘     └────────▲─────────┘
       │                    │                       │
       ▼                    ▼                       │
┌──────────────┐     ┌───────────────┐     ┌───────┴──────────┐
│ Chunking     │     │ Embedding     │     │ Промпт +         │
│ (разбивка    │     │ (запрос →     │     │ контекст из      │
│  на куски)   │     │  вектор)      │     │ найденных        │
└──────┬───────┘     └──────┬────────┘     │ документов       │
       │                    │              └────────▲─────────┘
       ▼                    ▼                       │
┌──────────────┐     ┌───────────────┐              │
│ Embedding    │     │ Similarity    │──────────────┘
│ (куски →     │     │ Search        │  Топ-3 результата
│  векторы)    │     │ (pgvector)    │
└──────┬───────┘     └───────────────┘
       │                    ▲
       ▼                    │
┌──────────────────────────────────────┐
│          Supabase pgvector           │
│    (таблица documents + embeddings)  │
└──────────────────────────────────────┘
```

---

## Шаг 1: Настройка pgvector в Supabase

### SQL: Включение расширения и создание таблиц

```sql
-- 1. Включаем расширение pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Таблица для документов базы знаний
CREATE TABLE documents (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  
  -- Метаданные документа
  title TEXT NOT NULL,
  source TEXT NOT NULL,               -- Откуда: 'help_center', 'faq', 'tutorial', 'changelog'
  source_url TEXT,                     -- Ссылка на оригинал
  category TEXT,                       -- Категория: 'projects', 'tasks', 'billing', etc.
  
  -- Контент
  content TEXT NOT NULL,               -- Полный текст фрагмента
  content_tokens INTEGER,              -- Количество токенов (для контроля лимитов)
  
  -- Вектор эмбеддинга (1536 размерность для text-embedding-3-small)
  embedding VECTOR(1536),
  
  -- Версионирование
  version INTEGER DEFAULT 1,
  is_active BOOLEAN DEFAULT true,      -- Можно "выключить" документ без удаления
  
  -- Временные метки
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Индекс для быстрого поиска по вектору
-- ivfflat — хороший баланс скорости и точности для < 100K документов
CREATE INDEX idx_documents_embedding ON documents 
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Для > 100K документов используйте HNSW:
-- CREATE INDEX idx_documents_embedding ON documents 
--   USING hnsw (embedding vector_cosine_ops)
--   WITH (m = 16, ef_construction = 64);

-- 4. Индексы для фильтрации
CREATE INDEX idx_documents_source ON documents(source);
CREATE INDEX idx_documents_category ON documents(category);
CREATE INDEX idx_documents_active ON documents(is_active);

-- 5. RLS-политики
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

-- Чтение — для всех аутентифицированных
CREATE POLICY "Authenticated users can read active documents"
  ON documents FOR SELECT
  USING (is_active = true AND auth.role() = 'authenticated');

-- Запись — только service role (бэкенд)
CREATE POLICY "Service role can manage documents"
  ON documents FOR ALL
  USING (auth.role() = 'service_role');

-- 6. Функция семантического поиска
CREATE OR REPLACE FUNCTION match_documents(
  query_embedding VECTOR(1536),
  match_threshold FLOAT DEFAULT 0.7,
  match_count INT DEFAULT 5,
  filter_source TEXT DEFAULT NULL,
  filter_category TEXT DEFAULT NULL
)
RETURNS TABLE (
  id UUID,
  title TEXT,
  content TEXT,
  source TEXT,
  source_url TEXT,
  category TEXT,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    d.id,
    d.title,
    d.content,
    d.source,
    d.source_url,
    d.category,
    1 - (d.embedding <=> query_embedding) AS similarity
  FROM documents d
  WHERE
    d.is_active = true
    AND 1 - (d.embedding <=> query_embedding) > match_threshold
    AND (filter_source IS NULL OR d.source = filter_source)
    AND (filter_category IS NULL OR d.category = filter_category)
  ORDER BY d.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
```

---

## Шаг 2: Генерация эмбеддингов

### TypeScript: Утилита для создания эмбеддингов

```typescript
import Anthropic from '@anthropic-ai/sdk';

// Для эмбеддингов используем Voyage AI (рекомендовано Anthropic)
// или OpenAI text-embedding-3-small (широко используется)

// Вариант: использование Voyage AI (рекомендован Anthropic)
async function generateEmbedding(text: string): Promise<number[]> {
  const response = await fetch('https://api.voyageai.com/v1/embeddings', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${process.env.VOYAGE_API_KEY}`,
    },
    body: JSON.stringify({
      model: 'voyage-3',
      input: text,
      input_type: 'document', // 'document' для индексации, 'query' для поиска
    }),
  });

  const data = await response.json();
  return data.data[0].embedding; // вектор [1536 чисел]
}

// Для поисковых запросов — другой input_type
async function generateQueryEmbedding(query: string): Promise<number[]> {
  const response = await fetch('https://api.voyageai.com/v1/embeddings', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${process.env.VOYAGE_API_KEY}`,
    },
    body: JSON.stringify({
      model: 'voyage-3',
      input: query,
      input_type: 'query', // Оптимизирован для поисковых запросов
    }),
  });

  const data = await response.json();
  return data.data[0].embedding;
}
```

### Chunking: Разбивка документов на фрагменты

```typescript
interface DocumentChunk {
  title: string;
  content: string;
  source: string;
  sourceUrl?: string;
  category?: string;
}

/**
 * Разбивает длинный текст на фрагменты с перекрытием.
 * 
 * Почему перекрытие: если важное предложение попадает на границу
 * двух чанков, перекрытие гарантирует, что оно будет найдено.
 */
function chunkText(
  text: string,
  maxChunkSize: number = 500, // ~500 слов = ~700 токенов
  overlap: number = 50        // 50 слов перекрытия
): string[] {
  const words = text.split(/\s+/);
  const chunks: string[] = [];

  let start = 0;
  while (start < words.length) {
    const end = Math.min(start + maxChunkSize, words.length);
    const chunk = words.slice(start, end).join(' ');
    chunks.push(chunk);
    start = end - overlap;

    // Избегаем бесконечного цикла
    if (end === words.length) break;
  }

  return chunks;
}

/**
 * Умный chunking: разбивает по заголовкам Markdown
 * Сохраняет контекст заголовка в каждом чанке
 */
function chunkMarkdown(markdown: string): string[] {
  const sections = markdown.split(/^##\s+/m);
  const chunks: string[] = [];

  for (const section of sections) {
    if (!section.trim()) continue;

    const lines = section.split('\n');
    const heading = lines[0].trim();
    const body = lines.slice(1).join('\n').trim();

    if (!body) continue;

    // Если секция маленькая — один чанк
    if (body.split(/\s+/).length <= 500) {
      chunks.push(`## ${heading}\n\n${body}`);
    } else {
      // Если большая — разбиваем, сохраняя заголовок
      const subChunks = chunkText(body, 450, 50);
      for (const sub of subChunks) {
        chunks.push(`## ${heading}\n\n${sub}`);
      }
    }
  }

  return chunks;
}
```

---

## Шаг 3: Индексация документов

### TypeScript: Загрузка базы знаний

```typescript
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY! // service role для записи
);

interface DocumentInput {
  title: string;
  content: string; // Markdown или обычный текст
  source: string;  // 'help_center' | 'faq' | 'tutorial'
  sourceUrl?: string;
  category?: string;
}

/**
 * Индексирует один документ: разбивает на чанки, генерирует эмбеддинги,
 * сохраняет в Supabase.
 */
async function indexDocument(doc: DocumentInput): Promise<number> {
  // 1. Разбиваем на чанки
  const chunks = chunkMarkdown(doc.content);
  console.log(`Document "${doc.title}": ${chunks.length} chunks`);

  let indexed = 0;

  for (const chunk of chunks) {
    // 2. Генерируем эмбеддинг
    const embedding = await generateEmbedding(chunk);

    // 3. Считаем токены (приблизительно: 1 токен ≈ 4 символа для русского)
    const contentTokens = Math.ceil(chunk.length / 3);

    // 4. Сохраняем в БД
    const { error } = await supabase.from('documents').insert({
      title: doc.title,
      content: chunk,
      source: doc.source,
      source_url: doc.sourceUrl,
      category: doc.category,
      embedding,
      content_tokens: contentTokens,
    });

    if (error) {
      console.error(`Error indexing chunk: ${error.message}`);
      continue;
    }

    indexed++;

    // Пауза для rate limiting API эмбеддингов
    await new Promise(resolve => setTimeout(resolve, 100));
  }

  return indexed;
}

/**
 * Массовая индексация базы знаний TaskFlow
 */
async function indexKnowledgeBase() {
  const documents: DocumentInput[] = [
    {
      title: 'Как создать проект',
      content: `## Создание проекта в TaskFlow

Проект — это контейнер для задач, объединённых общей целью.

### Шаги:
1. Нажмите кнопку "Новый проект" на главной странице
2. Введите название проекта (до 100 символов)
3. Выберите шаблон или создайте пустой проект
4. Добавьте участников по email
5. Нажмите "Создать"

### Ограничения по тарифам:
- Free: до 3 проектов
- Pro: до 20 проектов
- Business: безлимитно

### Часто задаваемые вопросы:
- Можно ли удалить проект? Да, через Настройки проекта > Удалить
- Можно ли архивировать? Да, проект скрывается но данные сохраняются
- Кто может создавать проекты? Любой пользователь с ролью Admin или Manager`,
      source: 'help_center',
      sourceUrl: 'https://taskflow.ru/help/create-project',
      category: 'projects',
    },
    {
      title: 'Управление задачами',
      content: `## Создание и управление задачами

Задача — основная единица работы в TaskFlow.

### Создание задачи:
1. Откройте проект
2. Нажмите "+" или "Новая задача"
3. Заполните: название, описание, приоритет, дедлайн, исполнитель
4. Добавьте теги для группировки

### Статусы задач:
- Открыта — ещё не начата
- В работе — активная работа
- На ревью — ждёт проверки
- Выполнена — завершена

### Приоритеты:
- Критический — блокирует других, дедлайн < 24 часов
- Высокий — важно, но не блокирует
- Средний — стандартная задача
- Низкий — можно отложить

### Быстрые действия:
- Перетаскивание для смены статуса (Kanban-вид)
- Ctrl+Enter — создать задачу из любого экрана
- @упоминание — назначить исполнителя в комментариях`,
      source: 'help_center',
      sourceUrl: 'https://taskflow.ru/help/tasks',
      category: 'tasks',
    },
    // ... ещё документы
  ];

  let totalIndexed = 0;
  for (const doc of documents) {
    const count = await indexDocument(doc);
    totalIndexed += count;
  }

  console.log(`Total indexed: ${totalIndexed} chunks`);
}
```

---

## Шаг 4: Семантический поиск

### TypeScript: Поиск по базе знаний

```typescript
interface SearchResult {
  id: string;
  title: string;
  content: string;
  source: string;
  sourceUrl: string | null;
  category: string | null;
  similarity: number;
}

/**
 * Семантический поиск по базе знаний.
 * Используется как handler для tool "search_knowledge_base"
 */
async function searchKnowledgeBase(
  query: string,
  options: {
    category?: string;
    source?: string;
    limit?: number;
    threshold?: number;
  } = {}
): Promise<SearchResult[]> {
  const {
    category = null,
    source = null,
    limit = 3,
    threshold = 0.7,
  } = options;

  // 1. Генерируем эмбеддинг запроса
  const queryEmbedding = await generateQueryEmbedding(query);

  // 2. Вызываем функцию поиска в Supabase
  const { data, error } = await supabase.rpc('match_documents', {
    query_embedding: queryEmbedding,
    match_threshold: threshold,
    match_count: limit,
    filter_source: source,
    filter_category: category,
  });

  if (error) {
    console.error('Search error:', error.message);
    return [];
  }

  return data as SearchResult[];
}

// Пример использования:
// const results = await searchKnowledgeBase('как создать проект');
// → [{title: 'Как создать проект', content: '...', similarity: 0.92}]
```

---

## Шаг 5: Инжекция контекста в промпт

### TypeScript: Полный поток RAG + Claude

```typescript
import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic();

/**
 * Полный RAG-pipeline: поиск → инжекция → генерация ответа
 */
async function ragAnswer(
  userQuery: string,
  systemPromptBase: string
): Promise<string> {
  // 1. Поиск релевантных документов
  const documents = await searchKnowledgeBase(userQuery, {
    limit: 3,
    threshold: 0.7,
  });

  // 2. Формируем контекст из найденных документов
  let context = '';
  if (documents.length > 0) {
    context = `\n\n## Релевантные документы из базы знаний\n\n`;
    context += `Используй ТОЛЬКО информацию из этих документов для ответа. `;
    context += `Если ответа нет в документах — скажи, что не нашёл информацию.\n\n`;

    for (let i = 0; i < documents.length; i++) {
      const doc = documents[i];
      context += `### Документ ${i + 1}: ${doc.title}`;
      context += ` (релевантность: ${Math.round(doc.similarity * 100)}%)\n`;
      if (doc.sourceUrl) {
        context += `Источник: ${doc.sourceUrl}\n`;
      }
      context += `\n${doc.content}\n\n---\n\n`;
    }
  } else {
    context = `\n\n## База знаний\n\n`;
    context += `По запросу "${userQuery}" релевантных документов не найдено. `;
    context += `Сообщи пользователю, что не нашёл информацию по этому вопросу, `;
    context += `и предложи обратиться в поддержку.\n`;
  }

  // 3. Собираем полный системный промпт
  const fullSystemPrompt = systemPromptBase + context;

  // 4. Отправляем в Claude
  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 2048,
    system: fullSystemPrompt,
    messages: [{ role: 'user', content: userQuery }],
  });

  const textBlock = response.content.find(
    (b): b is Anthropic.TextBlock => b.type === 'text'
  );

  return textBlock?.text || 'Не удалось сгенерировать ответ';
}
```

### Альтернатива: RAG как Tool Use

Вместо инжекции в промпт, RAG можно реализовать как инструмент:

```typescript
const tools: Anthropic.Tool[] = [
  {
    name: 'search_knowledge_base',
    description: 'Ищет релевантные статьи в базе знаний TaskFlow по семантическому запросу. Используй ПЕРЕД ответом на любой вопрос о функциональности TaskFlow. Возвращает топ-3 релевантных фрагмента с текстом и ссылками.',
    input_schema: {
      type: 'object' as const,
      properties: {
        query: {
          type: 'string',
          description: 'Поисковый запрос — переформулируй вопрос пользователя в ключевые слова',
        },
        category: {
          type: 'string',
          description: 'Категория для фильтрации',
          enum: ['projects', 'tasks', 'team', 'billing', 'integrations', 'troubleshooting'],
        },
      },
      required: ['query'],
    },
  },
];

// Handler для tool
async function handleSearchKnowledgeBase(input: { query: string; category?: string }) {
  const results = await searchKnowledgeBase(input.query, {
    category: input.category,
    limit: 3,
  });

  if (results.length === 0) {
    return { found: false, message: 'Релевантных документов не найдено' };
  }

  return {
    found: true,
    documents: results.map(r => ({
      title: r.title,
      content: r.content,
      url: r.sourceUrl,
      relevance: Math.round(r.similarity * 100) + '%',
    })),
  };
}
```

**Когда что использовать:**

| Подход | Плюсы | Минусы | Когда |
|--------|-------|--------|-------|
| RAG в промпте | Контекст всегда доступен, один запрос к Claude | Тратит токены даже когда не нужен | Агент ВСЕГДА отвечает из KB |
| RAG как Tool | Claude сам решает когда искать, экономия токенов | 2 запроса к Claude вместо 1 | Агент иногда отвечает без KB |

---

## Шаг 6: Обновление базы знаний

### TypeScript: API для управления документами

```typescript
import { Router } from 'express';

const router = Router();

// Добавить новый документ
router.post('/api/knowledge-base/documents', async (req, res) => {
  const { title, content, source, sourceUrl, category } = req.body;

  if (!title || !content || !source) {
    return res.status(400).json({ error: 'title, content и source обязательны' });
  }

  try {
    const count = await indexDocument({
      title,
      content,
      source,
      sourceUrl,
      category,
    });

    res.json({ success: true, chunksIndexed: count });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// Деактивировать документ (без удаления)
router.patch('/api/knowledge-base/documents/:id/deactivate', async (req, res) => {
  const { id } = req.params;

  const { error } = await supabase
    .from('documents')
    .update({ is_active: false, updated_at: new Date().toISOString() })
    .eq('id', id);

  if (error) {
    return res.status(500).json({ error: error.message });
  }

  res.json({ success: true });
});

// Обновить документ (деактивировать старый + создать новый)
router.put('/api/knowledge-base/documents/:id', async (req, res) => {
  const { id } = req.params;
  const { title, content, source, sourceUrl, category } = req.body;

  // 1. Деактивируем старую версию
  await supabase
    .from('documents')
    .update({ is_active: false })
    .eq('id', id);

  // 2. Индексируем новую версию
  const count = await indexDocument({
    title,
    content,
    source,
    sourceUrl,
    category,
  });

  res.json({ success: true, chunksIndexed: count });
});

// Статистика базы знаний
router.get('/api/knowledge-base/stats', async (req, res) => {
  const { data } = await supabase
    .from('documents')
    .select('source, category, is_active')
    .eq('is_active', true);

  const stats = {
    totalDocuments: data?.length || 0,
    bySource: {} as Record<string, number>,
    byCategory: {} as Record<string, number>,
  };

  for (const doc of data || []) {
    stats.bySource[doc.source] = (stats.bySource[doc.source] || 0) + 1;
    if (doc.category) {
      stats.byCategory[doc.category] = (stats.byCategory[doc.category] || 0) + 1;
    }
  }

  res.json(stats);
});

export default router;
```

---

## Оптимизация и лучшие практики

### 1. Размер чанков

| Размер | Плюсы | Минусы | Когда |
|--------|-------|--------|-------|
| 200 слов | Точный поиск | Может потерять контекст | FAQ, короткие ответы |
| 500 слов | Баланс | Стандарт | Большинство случаев |
| 1000 слов | Полный контекст | Менее точный поиск, дороже | Длинные инструкции |

**Рекомендация:** Начните с 500 слов с перекрытием 50 слов. Корректируйте по результатам.

### 2. Порог релевантности (threshold)

| Threshold | Поведение |
|-----------|-----------|
| 0.5 | Много результатов, но могут быть нерелевантные |
| 0.7 | Хороший баланс (рекомендуется для старта) |
| 0.85 | Только очень точные совпадения, может ничего не найти |
| 0.9+ | Практически точное совпадение |

### 3. Мониторинг качества RAG

```sql
-- Таблица для отслеживания качества поиска
CREATE TABLE rag_feedback (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  query TEXT NOT NULL,
  document_ids UUID[] NOT NULL,
  similarities FLOAT[] NOT NULL,
  was_helpful BOOLEAN,         -- Пользователь отметил ответ как полезный?
  agent_used_context BOOLEAN,  -- Агент использовал найденные документы?
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Метрика: средняя релевантность за неделю
SELECT
  DATE_TRUNC('week', created_at) AS week,
  AVG(similarities[1]) AS avg_top1_similarity,
  COUNT(*) FILTER (WHERE was_helpful = true)::FLOAT / COUNT(*) AS helpful_rate
FROM rag_feedback
GROUP BY week
ORDER BY week DESC;
```

### 4. Стоимость

| Компонент | Стоимость | На 1000 документов |
|-----------|-----------|-------------------|
| Эмбеддинг (Voyage AI) | ~$0.10 / 1M токенов | ~$0.05 (индексация) |
| Поиск запроса | ~$0.0001 / запрос | $0.0001 |
| Хранение pgvector | Включено в Supabase | $0 (free tier) |
| Claude ответ | ~$3 / 1M входных токенов | ~$0.003 / ответ |

**Итого:** ~$0.003-0.005 за один RAG-ответ. При 1000 запросах/день: ~$3-5/день.

---

## Чек-лист: RAG готов к production

| # | Проверка | Пройдено? |
|---|----------|-----------|
| 1 | pgvector включён, таблица создана | ☐ |
| 2 | Индекс создан (ivfflat или hnsw) | ☐ |
| 3 | RLS настроен (authenticated: read, service: write) | ☐ |
| 4 | Функция match_documents работает | ☐ |
| 5 | Документы разбиты на чанки (< 500 слов) | ☐ |
| 6 | Эмбеддинги сгенерированы и сохранены | ☐ |
| 7 | Поиск тестирован на 10+ реальных запросах | ☐ |
| 8 | Threshold настроен (начать с 0.7) | ☐ |
| 9 | Инжекция контекста в промпт работает | ☐ |
| 10 | Обработка пустого результата поиска | ☐ |
| 11 | API для обновления документов | ☐ |
| 12 | Мониторинг качества (rag_feedback) | ☐ |

---

## Связанные материалы

- **5-28** — Шаблон системного промпта (куда инжектируется контекст RAG)
- **5-29** — Определение tool search_knowledge_base
- **5-30** — Проектирование агента с RAG-компонентом
- **5-31** — Тестирование RAG: точность поиска, галлюцинации
- **3-18** — MCP Setup Reference (подключение Supabase)

---

*AI-Архитектор | Модуль 5: AI-агенты | Все примеры — вымышленный продукт TaskFlow (ООО "Продуктив")*
