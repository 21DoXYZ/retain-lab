# 3-58 | Telegram MiniApp — гид по разработке

> **Тип:** Универсальный гид (вставь в Claude как контекст)
> **Модуль:** 3 — Разработка и сборка
> **Время применения:** На старте любого MiniApp-проекта
> **Результат:** Claude собирает Telegram MiniApp без типичных ошибок, с учётом всех технических нюансов и production-граблей

---

## Как пользоваться этим документом

1. Создаёшь свой проект (Next.js + Supabase + Vercel).
2. **Копируешь содержимое этого файла целиком в Claude Code как контекст** — например, через `claude /add` или приложить к первому сообщению.
3. Пишешь Claude свою спецификацию: «собери MiniApp с такими-то фичами».
4. Claude использует этот гид как референс — ставит SDK правильно, верифицирует initData, не ломает CSP, обходит грабли Vercel и iOS WebView.

Внутри — реальный код, который мы сами написали и проверили на 100+ студентах в продакшне. Все «❗ Гочи» — это вещи, на которых мы споткнулись лично; сюда они попали именно для того, чтобы вы НЕ повторили.

---

## 1. Что такое Telegram MiniApp

**Telegram MiniApp** = веб-приложение (HTML + JS), которое открывается **внутри клиента Telegram** в специальном WebView. Пользователь не выходит из мессенджера — приложение ложится оверлеем поверх чата.

### Где работает

- iOS Telegram (WKWebView)
- Android Telegram (WebView)
- macOS Telegram Desktop
- Windows Telegram Desktop
- Telegram Web (web.telegram.org / a.web.telegram.org)

### Что Telegram даёт бесплатно

- Авторизация через подписанный `initData` (без своих регистраций / OAuth)
- Тема пользователя (`themeParams`) — приложение автоматически в светлой/тёмной теме
- Нативные UI-элементы: `MainButton` (большая кнопка снизу), `BackButton` (стрелка назад в шапке)
- Тактильная обратная связь (`HapticFeedback`)
- API для добавления на главный экран телефона (Bot API 8.0+)

### Чем отличается от PWA

- PWA = добавляется на главный экран, открывается в браузере, работает офлайн
- MiniApp = открывается ИЗ Telegram, наследует его UI-парадигму, авторизация бесплатная и встроенная

### Главные ограничения

- **WebView ≠ Safari/Chrome.** Некоторые API работают иначе, особенно на iOS WKWebView (см. раздел «Гочи»).
- **Auth только через бота.** Чтобы открыть MiniApp, у пользователя должен быть аккаунт Telegram + он должен запустить вашего бота.
- **Платежи внутри MiniApp** — только через Telegram Stars или внешние ссылки (нельзя интегрировать ЮKassa/Stripe прямо внутрь).

---

## 2. Стек, который доказал себя

Эти версии и комбинации проверены на проде 100+ пользователей. Не меняй без серьёзного повода:

```
Frontend (apps/miniapp):
  Next.js          16 (App Router, Turbopack)
  TypeScript       5.7+ (strict mode)
  Tailwind CSS     4.x (новый синтаксис @import + @theme)
  shadcn/ui        совместимая с Tailwind v4

Backend (apps/bot — если нужен):
  Node.js          22+
  Fastify          5.x
  PM2 + Nginx      на VPS

Data:
  Supabase         PostgreSQL 17 + Storage + pgvector
  pgvector         vector(1024) для RAG (match с Voyage AI voyage-3)

AI:
  Anthropic SDK    последний (claude-sonnet-4-6 по умолчанию)
  Voyage AI        voyage-3 для embeddings

Видео (если нужно защитить):
  Kinescope Pro    signed URL + watermark

Деплой:
  Vercel           для Next.js MiniApp
  Beget / DO       для Fastify бота (если нужен)
```

### Почему не альтернативы

- **Не Pages Router** — App Router в Next.js 16 уже стабилен, Server Components сильно экономят bundle size клиента, что критично для мобильного WebView.
- **Не Tailwind v3** — проект пишется сегодня, v4 быстрее и проще конфигурируется (CSS-only через `@theme`).
- **Не Supabase Auth** — у нас нет своих юзеров, личность приходит из Telegram. Auth лишний слой.
- **Не Express** — Fastify в 2-3 раза быстрее, имеет встроенный schema validation.

---

## 3. Структура монорепо (рекомендуется)

```
my-miniapp/
├── apps/
│   ├── miniapp/              # Next.js 16 — UI
│   │   ├── src/app/          # App Router
│   │   ├── src/components/   # ui/ | features/ | telegram/
│   │   ├── src/lib/          # supabase, theme, helpers
│   │   ├── src/hooks/
│   │   └── next.config.ts
│   └── bot/                  # Fastify Telegram Bot (если есть)
│       ├── src/handlers/
│       ├── src/services/
│       └── src/server.ts
├── packages/
│   └── shared/               # @yourapp/shared
│       ├── src/types/
│       ├── src/supabase/
│       └── src/utils/
├── supabase/migrations/      # SQL миграции
└── package.json              # workspaces: ["apps/*", "packages/*"]
```

В корневом `package.json`:

```json
{
  "workspaces": ["apps/*", "packages/*"],
  "scripts": {
    "dev": "npm run dev --workspaces --if-present",
    "build": "npm run build --workspaces --if-present",
    "type-check": "npm run type-check --workspaces --if-present"
  }
}
```

В `apps/miniapp/next.config.ts` **обязательно** прописать:

```typescript
const config: NextConfig = {
  transpilePackages: ['@yourapp/shared'],  // ← без этого Turbopack не скомпилирует TS из workspace
  // ...
};
```

---

## 4. Подключение Telegram SDK

В `<head>` должен быть подгружен скрипт `https://telegram.org/js/telegram-web-app.js`. В Next.js — через компонент `next/script` со стратегией `beforeInteractive`:

```typescript
// apps/miniapp/src/app/layout.tsx
import Script from 'next/script';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <head>
        <Script
          src="https://telegram.org/js/telegram-web-app.js"
          strategy="beforeInteractive"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
```

**Почему `beforeInteractive`:** SDK должен быть доступен ДО гидрации React-компонентов. Иначе первый рендер `useEffect` увидит `window.Telegram` как `undefined`, и хук попадёт в фолбэк (например, редирект на бота).

После загрузки скрипта появляется глобальный объект:

```typescript
const tg = window.Telegram.WebApp;

tg.ready();              // сообщает Telegram'у, что приложение готово
tg.expand();             // раскрывает MiniApp на полную высоту экрана
tg.initData;             // подписанная HMAC-SHA256 строка для серверной верификации
tg.initDataUnsafe.user;  // распарсенный объект user — НЕ доверять без серверной проверки
tg.themeParams;          // цвета темы пользователя
tg.colorScheme;          // 'light' | 'dark'
tg.platform;             // 'ios' | 'android' | 'tdesktop' | 'macos' | 'weba' | 'webk' | 'unknown'
tg.version;              // версия Bot API клиента ('7.10', '8.0', ...)
tg.MainButton;           // нативная кнопка снизу
tg.BackButton;           // нативная стрелка назад
tg.HapticFeedback;       // тактильная обратная связь
```

---

## 5. Авторизация через initData (HMAC-SHA256)

**Главный security-принцип:** ВСЕ запросы к серверу должны нести подписанный `initData`. Сервер проверяет подпись и только после этого верит, что пользователь действительно тот, за кого себя выдаёт.

### Серверная проверка (готовый сниппет — вставь как есть)

```typescript
// packages/shared/src/utils/verify-init-data.ts
import { createHmac, timingSafeEqual } from 'node:crypto';

export interface TelegramUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
  photo_url?: string;
}

/**
 * Верифицирует подпись Telegram WebApp initData по спеке:
 * https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
 *
 * Возвращает TelegramUser при успехе, null при невалидной подписи или
 * протухшем auth_date. maxAgeSeconds защищает от replay-атак.
 */
export function verifyInitData(
  initData: string,
  botToken: string,
  maxAgeSeconds = 28800,  // 8 часов
): TelegramUser | null {
  if (!initData || !botToken) return null;

  const params = new URLSearchParams(initData);
  const hash = params.get('hash');
  if (!hash) return null;
  params.delete('hash');

  const dataCheckString = [...params.entries()]
    .map(([k, v]) => `${k}=${v}`)
    .sort()
    .join('\n');

  const secretKey = createHmac('sha256', 'WebAppData').update(botToken).digest();
  const computedHash = createHmac('sha256', secretKey).update(dataCheckString).digest('hex');

  // ВАЖНО: timingSafeEqual защищает от timing-attacks. Не использовать ===.
  const expected = Buffer.from(computedHash, 'hex');
  const received = Buffer.from(hash, 'hex');
  if (expected.length !== received.length) return null;
  if (!timingSafeEqual(expected, received)) return null;

  const authDate = Number(params.get('auth_date'));
  if (!Number.isFinite(authDate)) return null;
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (nowSeconds - authDate > maxAgeSeconds) return null;

  const userRaw = params.get('user');
  if (!userRaw) return null;

  try {
    const user = JSON.parse(userRaw) as TelegramUser;
    if (typeof user.id !== 'number' || typeof user.first_name !== 'string') return null;
    return user;
  } catch {
    return null;
  }
}
```

### Использование в API route

```typescript
// apps/miniapp/src/app/api/some-endpoint/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { verifyInitData } from '@yourapp/shared/utils/verify-init-data';

export async function POST(req: NextRequest) {
  const { initData } = await req.json();

  const tgUser = verifyInitData(initData, process.env.TELEGRAM_BOT_TOKEN!);
  if (!tgUser) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  // tgUser.id — это надёжный, проверенный Telegram-ID. Дальше любая бизнес-логика.
}
```

### Правила безопасности

- 🔴 **НИКОГДА** не доверяй `window.Telegram.WebApp.initDataUnsafe` на сервере. Только клиенту-самому-себе.
- 🔴 **НИКОГДА** не используй `===` или `==` для сравнения хэшей — только `timingSafeEqual`.
- 🔴 **НИКОГДА** не клади `TELEGRAM_BOT_TOKEN` в клиентский код или префикс `NEXT_PUBLIC_*`.
- 🔴 **maxAgeSeconds**: подбирай по UX. Слишком мало (1 час) — студенты «вылетают» при долгом просмотре урока. 8 часов = одна учебная сессия. Дольше = больше окна для replay.

---

## 6. TelegramProvider — централизованный auth

Один React Context, который при монтировании MiniApp:
1. Дёргает `WebApp.ready()` + `expand()`
2. Применяет тему
3. Шлёт `initData` на `/api/auth` и держит профиль в state
4. Провайдит `{ profile, loading, error }` всем странам

```typescript
// apps/miniapp/src/components/telegram/TelegramProvider.tsx
'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { applyTelegramTheme, listenThemeChanges } from '@/lib/theme';

interface Profile {
  id: string;
  full_name: string;
  // ... твои поля
}

interface TelegramContextValue {
  profile: Profile | null;
  loading: boolean;
  error: string | null;
}

const Ctx = createContext<TelegramContextValue>({ profile: null, loading: true, error: null });
export const useTelegram = () => useContext(Ctx);

export function TelegramProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const tg = (window as unknown as { Telegram?: { WebApp: any } }).Telegram?.WebApp;

    if (!tg || !tg.initData) {
      setError('Откройте приложение через Telegram');
      setLoading(false);
      return;
    }

    tg.ready();
    tg.expand();
    applyTelegramTheme();
    listenThemeChanges();

    fetch('/api/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData: tg.initData }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) { setError(data.error); return; }
        setProfile(data.profile);
      })
      .catch(() => setError('Ошибка соединения'))
      .finally(() => setLoading(false));
  }, []);

  return <Ctx.Provider value={{ profile, loading, error }}>{children}</Ctx.Provider>;
}
```

В `app/layout.tsx`:

```tsx
<body>
  <TelegramProvider>{children}</TelegramProvider>
</body>
```

---

## 7. Theme adaptation

Telegram передаёт цвета своей темы через `WebApp.themeParams`. Идея — конвертировать их в CSS-переменные и подставлять через Tailwind v4 `@theme`.

```typescript
// apps/miniapp/src/lib/theme.ts
export function applyTelegramTheme() {
  const tg = (window as any).Telegram?.WebApp;
  if (!tg) return;

  const t = tg.themeParams ?? {};
  const root = document.documentElement;

  const cssVars: Record<string, string> = {
    '--tg-bg':            t.bg_color           ?? '#0F1114',
    '--tg-text':          t.text_color         ?? '#E5E7EB',
    '--tg-hint':          t.hint_color         ?? '#9CA3AF',
    '--tg-link':          t.link_color         ?? '#0F8AD2',
    '--tg-button':        t.button_color       ?? '#0F8AD2',
    '--tg-button-text':   t.button_text_color  ?? '#FFFFFF',
    '--tg-secondary-bg':  t.secondary_bg_color ?? '#1A1C1F',
    '--tg-section-bg':    t.section_bg_color   ?? '#1A1C1F',
    '--tg-destructive':   t.destructive_text_color ?? '#EF4444',
  };

  Object.entries(cssVars).forEach(([k, v]) => root.style.setProperty(k, v));
  document.documentElement.classList.toggle('dark', tg.colorScheme === 'dark');
}

export function listenThemeChanges() {
  const tg = (window as any).Telegram?.WebApp;
  tg?.onEvent('themeChanged', applyTelegramTheme);
}
```

```css
/* apps/miniapp/src/app/globals.css */
@import "tailwindcss";

@theme {
  --color-background:        var(--tg-bg);
  --color-foreground:        var(--tg-text);
  --color-muted:             var(--tg-hint);
  --color-primary:           var(--tg-button);
  --color-primary-foreground: var(--tg-button-text);
  --color-secondary:         var(--tg-secondary-bg);
  --color-card:              var(--tg-section-bg);
  --color-destructive:       var(--tg-destructive);
}

body {
  background-color: var(--color-background);
  color: var(--color-foreground);
}
```

🔴 **НЕ хардкодить цвета** в компонентах (`bg-white`, `text-gray-900`). Только `bg-background`, `text-foreground`, `bg-card`, `text-primary`. Иначе тема пользователя не применится.

---

## 8. Mobile-first UI правила

MiniApp по умолчанию открывается во весь экран телефона. Никакого desktop-layout.

### Обязательный контейнер

```tsx
<div className="max-w-md mx-auto px-4 py-6">
  {/* твой контент */}
</div>
```

### Запрещено

- 🔴 `md:`, `lg:`, `xl:`, `2xl:` breakpoints
- 🔴 Sidebar / навигация по бокам
- 🔴 Многоколоночный layout
- 🔴 Header-навигация (есть нативный `BackButton`)

### Safe area для iOS notch + home indicator

```css
/* globals.css */
body {
  padding-top:    env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
  padding-left:   env(safe-area-inset-left);
  padding-right:  env(safe-area-inset-right);
}

/* На страницах, где виден MainButton — добавить отступ снизу под него: */
.with-main-button {
  padding-bottom: calc(env(safe-area-inset-bottom) + 80px);
}
```

---

## 9. MainButton wrapper

Нативная большая кнопка снизу экрана. Используй для главного действия страницы (Сохранить, Опубликовать, Купить).

```tsx
// apps/miniapp/src/components/telegram/MainButton.tsx
'use client';

import { useEffect } from 'react';

interface MainButtonProps {
  text: string;
  onClick: () => void;
  visible?: boolean;
  disabled?: boolean;
  loading?: boolean;
}

export function MainButton({
  text,
  onClick,
  visible = true,
  disabled = false,
  loading = false,
}: MainButtonProps) {
  useEffect(() => {
    const tg = (window as any).Telegram?.WebApp;
    if (!tg?.MainButton) return;

    const button = tg.MainButton;
    button.setText(text);

    if (visible)  button.show();   else button.hide();
    if (disabled) button.disable(); else button.enable();
    if (loading)  button.showProgress(); else button.hideProgress();

    button.onClick(onClick);

    // 🔴 КРИТИЧНО: cleanup. Иначе кнопка зависнет на следующей странице
    // со старым обработчиком и обманёт пользователя.
    return () => {
      button.offClick(onClick);
      button.hide();
    };
  }, [text, onClick, visible, disabled, loading]);

  return null;  // ничего не рендерим — это нативный UI
}
```

---

## 10. BackButton wrapper

Нативная стрелка «назад» в шапке Telegram'а. Показывается на всех внутренних страницах, скрывается на главной.

```tsx
// apps/miniapp/src/components/telegram/BackButton.tsx
'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

interface BackButtonProps {
  onClick?: () => void;  // если не указан — router.back()
}

export function BackButton({ onClick }: BackButtonProps) {
  const router = useRouter();

  useEffect(() => {
    const tg = (window as any).Telegram?.WebApp;
    if (!tg?.BackButton) return;

    const handler = onClick ?? (() => router.back());
    tg.BackButton.show();
    tg.BackButton.onClick(handler);

    return () => {
      tg.BackButton.offClick(handler);
      tg.BackButton.hide();
    };
  }, [router, onClick]);

  return null;
}
```

🔴 **На главной (dashboard) кнопку НЕ монтировать** — пользователь закрывает MiniApp свайпом или крестиком.

---

## 11. HapticFeedback — тактильная обратная связь

```typescript
// apps/miniapp/src/hooks/useHaptic.ts
'use client';

export function useHaptic() {
  const tg = typeof window !== 'undefined'
    ? (window as any).Telegram?.WebApp
    : null;

  return {
    impact: (style: 'light' | 'medium' | 'heavy' = 'medium') => {
      tg?.HapticFeedback?.impactOccurred(style);
    },
    notification: (type: 'error' | 'success' | 'warning') => {
      tg?.HapticFeedback?.notificationOccurred(type);
    },
    selection: () => {
      tg?.HapticFeedback?.selectionChanged();
    },
  };
}
```

### Когда какую вибрацию использовать

| Действие | Метод |
|---|---|
| Тап по карточке / переход на страницу | `impact('light')` |
| Подтверждение важного действия (Сохранить, Удалить) | `impact('medium')` |
| Удаление, рестарт, сброс | `impact('heavy')` |
| Успех (профиль сохранён, оплата прошла) | `notification('success')` |
| Ошибка (валидация, сеть упала) | `notification('error')` |
| Внимание (rate-limit, лимит достигнут) | `notification('warning')` |
| Переключение таба, сегмента, чекбокса | `selection()` |

---

## 12. Server Actions vs API Routes

В Next.js 16 — две формы серверного кода:

### Server Actions

**Файл с `'use server'` в начале.** Вызывается из клиентского кода как обычная функция, Next.js под капотом превращает её в POST.

Идеально для:
- Мутаций данных в твоём бекенде (UPDATE profile, INSERT post)
- Лёгких операций в формах

### API Routes (`app/api/.../route.ts`)

Полноценный HTTP-эндпоинт с заголовками, поддержкой методов, файлами.

Идеально для:
- Webhooks (Telegram bot, оплаты, внешние сервисы)
- Загрузки файлов > 4.5 MB (см. раздел Гочи)
- Стороннего вызова из других систем
- Стриминга больших ответов

---

## 13. ❗ Гоча: Vercel режет body Server Actions ≈ 4.5 MB

**Симптом:** студент пытается загрузить картинку или видео, получает `Body exceeded 4.5 MB`. Указание `experimental.serverActions.bodySizeLimit: '100mb'` в `next.config.ts` НЕ помогает — Vercel держит свой infra-уровневый лимит.

### Решение — direct-to-Storage upload через signed URL

1. Server Action возвращает **подписанный одноразовый upload URL** Supabase Storage.
2. Клиент кидает файл напрямую в Storage через `PUT signedUrl`, минуя Vercel.

#### Server Action (issue signed URL)

```typescript
// apps/miniapp/src/app/actions/upload.ts
'use server';

import { createAdminClient } from '@yourapp/shared/supabase/admin';
import { resolveTgId } from '@/lib/auth';

export async function createUploadUrl(
  initData: string,
  fileType: string,
  fileSize: number,
): Promise<{ ok: boolean; uploadUrl?: string; publicUrl?: string; message?: string }> {
  const tgId = resolveTgId(initData);
  if (!tgId) return { ok: false, message: 'unauthorized' };

  const ALLOWED: Record<string, string> = {
    'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp',
    'video/mp4': 'mp4',  'video/webm': 'webm', 'video/quicktime': 'mov',
  };
  if (!ALLOWED[fileType]) return { ok: false, message: 'unsupported file type' };

  const MAX = fileType.startsWith('video/') ? 100 * 1024 * 1024 : 10 * 1024 * 1024;
  if (fileSize > MAX) return { ok: false, message: `файл слишком большой` };

  const ext = ALLOWED[fileType];
  const path = `${tgId}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.${ext}`;

  const supabase = createAdminClient();
  const { data: signed, error } = await supabase.storage
    .from('user_uploads')
    .createSignedUploadUrl(path);
  if (error || !signed) return { ok: false, message: 'internal error' };

  const { data: pub } = supabase.storage.from('user_uploads').getPublicUrl(path);
  return { ok: true, uploadUrl: signed.signedUrl, publicUrl: pub.publicUrl };
}
```

#### Клиент (PUT через XHR с прогрессом)

```typescript
// в твоём компоненте
const signed = await createUploadUrl(initData, file.type, file.size);
if (!signed.ok || !signed.uploadUrl) throw new Error(signed.message);

await new Promise<void>((resolve, reject) => {
  const xhr = new XMLHttpRequest();
  xhr.open('PUT', signed.uploadUrl!, true);
  xhr.setRequestHeader('Content-Type', file.type);
  xhr.setRequestHeader('x-upsert', 'false');

  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    setUploadProgress(pct);
  };
  xhr.onload  = () => xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error('upload failed'));
  xhr.onerror = () => reject(new Error('network error'));
  xhr.send(file);
});

// signed.publicUrl теперь хранится в БД (или передаётся дальше)
```

#### Bucket настройка

```sql
-- В миграции
update storage.buckets
set
  file_size_limit    = 104857600,  -- 100 MB
  allowed_mime_types = array['image/jpeg','image/png','image/webp','video/mp4','video/webm','video/quicktime']
where id = 'user_uploads';
```

---

## 14. ❗ Гоча: Server Actions сериализуют массив как объект

**Симптом:** клиент шлёт `input.tags = ['ai', 'product']`, на сервере получает `{0: 'ai', 1: 'product'}`. `Array.isArray(input.tags) === false` → пишем в jsonb-колонку как объект, читаем обратно — пустой массив.

### Решение — coerce на сервере

```typescript
function toArray<T>(input: unknown): T[] {
  if (Array.isArray(input)) return input as T[];
  if (input && typeof input === 'object') return Object.values(input) as T[];
  return [];
}

// Применяем для каждого массива в Server Action input:
if (input.tags !== undefined) patch.tags = toArray<string>(input.tags);
```

И симметрично — на чтении при парсинге jsonb (вдруг старая запись в БД сохранилась как объект):

```typescript
function parseTags(raw: unknown): string[] {
  return Array.isArray(raw)
    ? raw.filter((t): t is string => typeof t === 'string')
    : raw && typeof raw === 'object'
      ? Object.values(raw as Record<string, unknown>).filter((t): t is string => typeof t === 'string')
      : [];
}
```

---

## 15. ❗ Гоча: `instanceof Blob` не работает в Server Actions

**Симптом:** в Server Action получаешь `FormData`, делаешь `if (!(file instanceof Blob))` — всегда false, хотя файл реально есть.

**Причина:** Server Action работает в другом JS realm; глобальный `Blob` в нём — другой класс, чем у `file`.

### Решение — duck-typing

```typescript
function isBlobLike(x: unknown): x is { type: string; size: number; arrayBuffer(): Promise<ArrayBuffer> } {
  return !!x
    && typeof x === 'object'
    && typeof (x as any).type === 'string'
    && typeof (x as any).size === 'number'
    && typeof (x as any).arrayBuffer === 'function';
}

// В Server Action:
const file = formData.get('file');
if (!isBlobLike(file)) return { ok: false, message: 'file required' };
```

(Лучше использовать direct-upload из раздела #13 — там вообще нет `Blob` на сервере.)

---

## 16. ❗ Гоча: iOS WebView блокирует `<a download>` с `blob:` URL

**Симптом:** на iOS Telegram при клике на «Скачать» с `<a href={blob:...} download>` появляется системный диалог «Перейти по ссылке» с непонятным `blob:https://...` адресом, файл не сохраняется.

### Решение — `Telegram.WebApp.downloadFile` + signed URL endpoint

#### Подписанный токен

```typescript
// packages/shared/src/utils/download-token.ts
import { createHmac, timingSafeEqual } from 'node:crypto';

const TTL_MS = 10 * 60 * 1000;
const SECRET = () => process.env.TELEGRAM_BOT_TOKEN ?? '';

const b64url = (buf: Buffer | string) =>
  Buffer.from(typeof buf === 'string' ? Buffer.from(buf, 'utf8') : buf)
    .toString('base64')
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

const sign = (payload: string) =>
  b64url(createHmac('sha256', SECRET()).update(payload).digest());

export function signDownloadToken(tgId: number, slug: string): string {
  const exp = Date.now() + TTL_MS;
  const slugB64 = b64url(slug);
  const payload = `${tgId}.${slugB64}.${exp}`;
  return `${payload}.${sign(payload)}`;
}

export function verifyDownloadToken(token: string): { tgId: number; slug: string } | null {
  const parts = token.split('.');
  if (parts.length !== 4) return null;
  const [tgIdStr, slugB64, expStr, sig] = parts;
  const expected = sign(`${tgIdStr}.${slugB64}.${expStr}`);
  if (sig.length !== expected.length) return null;
  if (!timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return null;
  if (Number(expStr) < Date.now()) return null;
  const tgId = Number(tgIdStr);
  if (!Number.isFinite(tgId) || tgId <= 0) return null;
  const b64 = slugB64.replace(/-/g, '+').replace(/_/g, '/');
  const pad = b64.length % 4 === 0 ? '' : '='.repeat(4 - (b64.length % 4));
  const slug = Buffer.from(b64 + pad, 'base64').toString('utf8');
  return { tgId, slug };
}
```

#### Endpoint (см. также гочу про обрезку — раздел #17)

```typescript
// apps/miniapp/src/app/api/download/[slug]/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { verifyDownloadToken } from '@yourapp/shared/utils/download-token';

export const runtime = 'nodejs';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  const token = new URL(req.url).searchParams.get('t');
  const payload = token ? verifyDownloadToken(token) : null;
  if (!payload || payload.slug !== slug) {
    return new NextResponse('# Сессия устарела\n\nЗакрой и открой MiniApp заново.', {
      status: 401,
      headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
    });
  }
  // ... fetch your content from DB by slug, check tariff/access
  // const content = ...

  // См. раздел #17 — обязательно Buffer + Content-Length + ReadableStream:
  return serveAsDownload(content, `${slug}.md`);
}
```

#### Клиент

```typescript
// При первичном fetch'е страницы — сервер сразу возвращает download_url с токеном:
// const { content, download_url } = await getMaterialBySlug(slug, initData)

const handleDownload = () => {
  const tg = (window as any).Telegram?.WebApp;
  if (tg?.downloadFile && download_url) {
    tg.downloadFile({
      url: `${window.location.origin}${download_url}`,
      file_name: `${slug}.md`,
    });
    return;
  }
  // Fallback на десктопе/в браузере: blob anchor
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${slug}.md`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};
```

---

## 17. ❗ Гоча: chunked encoding обрезает большие ответы на ~10–12 КБ

**Симптом:** клиент скачивает `.md` файл — содержимое **обрезано посередине** на 10–12 КБ. Reader (Telegram client / curl) видит первый сетевой chunk и закрывает соединение.

**Причина:** Vercel'овский serverless wrapper иногда отдаёт ответ через `Transfer-Encoding: chunked` без `Content-Length`. Telegram'овский downloadFile + некоторые WebView'ы недокачивают chunked ответы.

### Решение — Buffer + Content-Length + одночанковый ReadableStream

```typescript
function serveAsDownload(content: string, filename: string) {
  const bytes = Buffer.from(content, 'utf8');

  // ReadableStream одним enqueue + close — runtime не сможет случайно
  // разрезать на два сетевых frame'а. Content-Length даёт клиенту
  // явный сигнал о длине, не полагаясь на chunked-end.
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });

  return new NextResponse(body, {
    status: 200,
    headers: {
      'Content-Type':        'text/markdown; charset=utf-8',
      'Content-Disposition': `attachment; filename="${filename}"`,
      'Content-Length':      String(bytes.length),
      'Cache-Control':       'no-store, no-cache, must-revalidate',
    },
  });
}
```

🔴 **Применяй ко ВСЕМ download-эндпоинтам.** В нашей продукции этим лечилось 100% случаев обрезки.

---

## 18. ❗ Гоча: HLS-плеер чернеет в WKWebView при resize

**Симптом:** клиент в Telegram Desktop на macOS открывает видео, жмёт «Развернуть». Видео становится чёрным, звук идёт. После 5–10 секунд (на следующем keyframe) восстанавливается.

**Причина:** WKWebView + HLS-декодер плохо переживает резкое изменение размеров `<video>` (или iframe плеера) в одном React-рендере (`fixed inset-0` поверх `aspect-video`).

### Решение — HTML5 fullscreen API на iframe (не CSS-flip)

```typescript
async function toggleFullscreen() {
  const iframe = iframeRef.current;
  if (!iframe) return;

  if (document.fullscreenElement) {
    await document.exitFullscreen();
    return;
  }

  // На desktop: HTML5 fullscreen работает чисто, плеер сам подстраивается
  if (document.fullscreenEnabled) {
    try {
      await iframe.requestFullscreen();
      return;
    } catch {
      /* fallthrough к Telegram API */
    }
  }

  // Mobile fallback: Telegram-native fullscreen панели + CSS overlay
  const tg = (window as any).Telegram?.WebApp;
  tg?.requestFullscreen?.();  // expand панель MiniApp
  setCssFullscreen(true);     // CSS `fixed inset-0` на контейнере iframe
}
```

Iframe должен иметь:

```tsx
<iframe
  allow="autoplay; fullscreen; picture-in-picture; encrypted-media"
  allowFullScreen
  // ...
/>
```

---

## 19. CSP (Content Security Policy) headers

В `next.config.ts`:

```typescript
const config: NextConfig = {
  async headers() {
    return [{
      source: '/(.*)',
      headers: [
        { key: 'X-Frame-Options', value: 'ALLOWALL' },
        { key: 'Permissions-Policy', value: 'fullscreen=*' },
        {
          key: 'Content-Security-Policy',
          value: [
            "default-src 'self'",
            // Telegram + ваш видео-провайдер. ВАЖНО: wildcard *.example.com
            // НЕ покрывает apex example.com — указывайте оба.
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://telegram.org https://kinescope.io https://*.kinescope.io",
            "style-src 'self' 'unsafe-inline' https://kinescope.io https://*.kinescope.io",
            "img-src 'self' data: https: blob:",
            "font-src 'self' data: https://kinescope.io https://*.kinescope.io",
            "connect-src 'self' https://api.anthropic.com https://*.supabase.co https://kinescope.io https://*.kinescope.io",
            "frame-src https://kinescope.io https://*.kinescope.io https://telegram.org",
            // ВАЖНО: media-src обязан включать Storage (видео из бакета).
            // img-src `https:` wildcard покрывает Supabase картинки, но
            // media-src такого wildcard не имеет — нужно прописать явно.
            "media-src 'self' blob: https://*.supabase.co https://kinescope.io https://*.kinescope.io",
            "worker-src 'self' blob:",
            // Только Telegram может встраивать наш MiniApp:
            "frame-ancestors https://web.telegram.org https://telegram.org",
          ].join('; '),
        },
      ],
    }];
  },
};
```

🔴 **Wildcard `*.example.com` НЕ покрывает apex `example.com`.** Если работает только iframe и не работают скрипты — ищи apex в CSP.

---

## 20. Webhook handlers (платежи, бот)

Любой webhook от внешнего сервиса:

1. Читай **raw body** (`await req.text()`), а не JSON.
2. Верифицируй HMAC по сырым байтам ДО `JSON.parse`.
3. Используй `timingSafeEqual` для сравнения подписей.
4. Логируй в `webhook_logs` для идемпотентности (дубликаты → 200 OK без обработки).

```typescript
// apps/miniapp/src/app/api/webhooks/payment/route.ts
import { createHmac, timingSafeEqual } from 'node:crypto';

export async function POST(req: NextRequest) {
  const raw = await req.text();
  const sig = req.headers.get('x-signature') ?? '';
  const expected = createHmac('sha256', process.env.PAYMENT_WEBHOOK_SECRET!).update(raw).digest('hex');

  const sigBuf = Buffer.from(sig, 'hex');
  const expBuf = Buffer.from(expected, 'hex');
  if (sigBuf.length !== expBuf.length) return new NextResponse(null, { status: 401 });
  if (!timingSafeEqual(sigBuf, expBuf)) return new NextResponse(null, { status: 401 });

  const event = JSON.parse(raw);
  // ... логика, idempotency-проверка через webhook_logs

  return NextResponse.json({ ok: true });
}
```

---

## 21. RLS на каждой таблице Supabase

Включай RLS даже если приложение ходит в БД через service_role. Это **защита глубиной** на случай, если кто-то случайно создаст публичный endpoint с anon-key'ем.

Минимальный шаблон политики (если нет Supabase Auth, как у нас):

```sql
-- Каждая таблица:
alter table public.<name> enable row level security;

create policy "service_role_all"
  on public.<name>
  for all
  to service_role
  using (true);

create policy "deny_anon"
  on public.<name>
  for all
  to anon
  using (false);

create policy "deny_authenticated"
  on public.<name>
  for all
  to authenticated
  using (false);
```

Все клиенты приложения (MiniApp, бот) ходят через `createClient(URL, SERVICE_ROLE_KEY)`. Бизнес-проверки доступа делаются в коде API routes / Server Actions.

---

## 22. «Добавить на главный экран» (Bot API 8.0+)

С Bot API 8.0 (декабрь 2024) Telegram даёт нативный API для PWA-style инсталла:

```typescript
const tg = (window as any).Telegram?.WebApp;

// 1. Проверка статуса
tg?.checkHomeScreenStatus?.((status: 'unsupported' | 'unknown' | 'added' | 'missed') => {
  if (status === 'missed' || status === 'unknown') {
    showAddBanner();  // показать кнопку «Добавить»
  }
});

// 2. По клику пользователя
function handleAdd() {
  tg?.addToHomeScreen?.();
  // открывается Telegram'овский confirmation sheet
}

// 3. Слушаем результат
tg?.onEvent?.('homeScreenAdded', () => hideAddBanner());
```

Старые клиенты (Bot API < 8.0) — методов просто нет, optional chaining гасит. Никаких ошибок. На таких клиентах показываем текст: «откройте `⋮` → "Добавить на экран Домой"».

---

## 23. Деплой на Vercel

### Env-переменные (не коммитить!)

```
TELEGRAM_BOT_TOKEN=123:ABC...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
ANTHROPIC_API_KEY=sk-ant-...
# ... остальные секреты
```

🔴 **`NEXT_PUBLIC_*` префикс** = переменная попадает в клиентский бандл и видна в DevTools. **Никогда** не используй для секретных ключей.

### `next.config.ts` чек-лист

```typescript
const config: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@yourapp/shared'],   // если монорепо
  experimental: {
    serverActions: { bodySizeLimit: '5mb' }, // выше 4.5 MB не работает на Vercel
  },
  async headers() { /* CSP — см. раздел #19 */ },
  // Включить нужные файлы в output:
  // outputFileTracingIncludes: { '/api/admin/...': ['../../seed-data/**'] },
};
```

### Smoke-тесты после деплоя

- [ ] Открыть `https://app.example.com` в обычном браузере → редирект на бота / экран «Откройте через Telegram»
- [ ] Открыть бота, нажать MainButton → MiniApp открывается
- [ ] Выйти из MiniApp, зайти снова → состояние сохраняется
- [ ] DevTools на Telegram Desktop / удалённый отладчик на Android → нет ошибок CSP / 404 / 500

---

## 24. Готовый шаблон CLAUDE.md для твоего проекта

Положи рядом с `package.json`. Claude Code читает его как контекст в каждой сессии.

```markdown
# <Project> — Telegram MiniApp

## Стек
- Next.js 16 (App Router, Turbopack)
- TypeScript strict (no `any`)
- Tailwind CSS v4 (`@import "tailwindcss"` + `@theme`)
- Supabase (Postgres + Storage + pgvector)
- Vercel (frontend)

## Правила кодирования
- TypeScript strict, никакого `any` — `unknown` + narrowing
- camelCase для переменных, PascalCase для компонентов, snake_case для таблиц БД
- Один компонент = один файл, до 200 строк
- Импорты: `@/` для своего кода, `@yourapp/shared/*` для shared
- try/catch для async, Error Boundaries для React
- Никаких TODO в коммитах — доводи фичу до конца

## Telegram MiniApp требования
- Mobile-first: `max-w-md mx-auto px-4`, никаких `md:`/`lg:`
- Native UI: `MainButton`, `BackButton`, `HapticFeedback` через обёртки в `components/telegram/`
- Theme: `themeParams` → CSS variables через `@theme`. Не хардкодить цвета.
- Auth: `verifyInitData` HMAC-SHA256 на сервере. **НИКОГДА** не доверять `initDataUnsafe`.

## Tailwind v4 (важно!)
- `globals.css` начинается с `@import "tailwindcss"` (НЕ `@tailwind base/components/utilities`)
- `@theme { --color-*: ... }` блок ВМЕСТО `tailwind.config.ts`
- `shadow-xs` вместо `shadow-sm`, `outline-hidden` вместо `outline-none`

## Anthropic Tool Use
- Это `Tool Use`, НЕ `function calling` (то OpenAI)
- SDK: `@anthropic-ai/sdk`, метод `messages.create({ tools: [...] })`
- Модель по умолчанию: `claude-sonnet-4-6`

## Готчи (не повторять)
- Server Actions может прислать массив как `{0: ..., 1: ...}` — coerce через `Object.values()`
- Vercel режет body Server Actions ≈ 4.5 MB — большие файлы через signed Storage URL
- iOS WebView блокирует `<a download>` с `blob:` — использовать `tg.downloadFile`
- HLS в WKWebView чернеет при CSS-flip — fullscreen через HTML5 `iframe.requestFullscreen`
- Chunked encoding режет большие ответы — `Buffer + Content-Length + ReadableStream`
- CSP wildcard `*.example.com` НЕ покрывает apex — указывать оба

## Безопасность
- Никаких `NEXT_PUBLIC_*` для секретных ключей
- Service Role Key только в env API routes / бота
- HMAC сравнение только через `timingSafeEqual`
- RLS на каждой таблице (даже под service_role)

## Команды
- `npm run dev` — оба workspace параллельно
- `npm run type-check` — `tsc --noEmit` во всех пакетах
- `npx supabase db push` — применить миграции

## Субагенты (рекомендую)
- `database-architect` — Supabase схема, RLS, миграции
- `frontend-developer` — React, Tailwind, Telegram-обёртки
- `qa-reviewer` — type check, security, smoke-tests
- `bot-developer` (если есть бот) — Fastify, webhook'и, Telegram API
```

---

## 25. Production checklist (50 пунктов)

### Архитектура

- [ ] `transpilePackages` прописан в `next.config.ts` (если монорепо)
- [ ] `tsconfig.json` с `strict: true` во всех пакетах
- [ ] `npm run type-check` проходит во всех workspace без ошибок
- [ ] Нет `any` в продовом коде (только в `*.test.ts` если нужно)
- [ ] Нет хардкоженных цветов / breakpoints

### Telegram SDK

- [ ] `<Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive">` в `app/layout.tsx`
- [ ] `WebApp.ready()` + `WebApp.expand()` вызваны в `TelegramProvider`
- [ ] Тема применяется + слушается `themeChanged` событие
- [ ] `MainButton` / `BackButton` cleanup в `useEffect` (off + hide)
- [ ] `HapticFeedback` на ключевых action

### Авторизация

- [ ] `verifyInitData` использует `timingSafeEqual` (не `===`)
- [ ] `auth_date` проверяется (не старше 8 часов)
- [ ] **Нет** мест, где сервер доверяет `initDataUnsafe`
- [ ] Каждый защищённый endpoint вызывает `verifyInitData` ДО бизнес-логики

### CSP / headers

- [ ] CSP покрывает Telegram, Supabase, Anthropic, твой видео-провайдер
- [ ] Apex И wildcard для каждого домена в CSP (`example.com` И `*.example.com`)
- [ ] `media-src` явно включает Storage (для видео из бакета)
- [ ] `frame-ancestors` ограничен `telegram.org`/`web.telegram.org`
- [ ] `Permissions-Policy: fullscreen=*` для видео

### Files / uploads

- [ ] Файлы > 4.5 MB идут через direct-to-Storage signed URL
- [ ] Buckets имеют `file_size_limit` и `allowed_mime_types`
- [ ] Download endpoints используют `Buffer + Content-Length + ReadableStream`
- [ ] iOS download через `tg.downloadFile` + signed token, не `blob:` URL
- [ ] Вместо `instanceof Blob` — duck-typing

### Server Actions

- [ ] Все массивы coerce'ятся через `Object.values()` fallback на сервере
- [ ] `bodySizeLimit` стоит на 5mb (или сколько Vercel разрешает)
- [ ] Server Actions не используют files > 4.5MB

### БД

- [ ] RLS включена на каждой таблице
- [ ] Миграции в `supabase/migrations/YYYYMMDDHHMMSS_*.sql`
- [ ] Типы регенерированы после миграций (`supabase gen types typescript`)
- [ ] FK всегда указаны (`on delete cascade/set null/restrict`)
- [ ] Индексы на колонках, используемых в `WHERE` / `ORDER BY`

### Безопасность

- [ ] Нет `NEXT_PUBLIC_*` для секретов
- [ ] Service Role Key только в server-коде
- [ ] Webhook'и читают raw body, верифицируют HMAC до парсинга
- [ ] `webhook_logs` для идемпотентности (event_id уникален)
- [ ] Никакого `eval()` / `new Function()` с user input

### Деплой Vercel

- [ ] Env-переменные настроены в Vercel dashboard
- [ ] Domain настроен в DNS (CNAME → vercel)
- [ ] SSL включён (автоматически)
- [ ] Build проходит без ошибок
- [ ] Smoke test: `curl -I https://app.example.com` → 200

### Telegram bot setup

- [ ] BotFather: бот создан, получен токен
- [ ] BotFather: Menu Button → URL твоего MiniApp
- [ ] BotFather: Domain → твой домен
- [ ] Bot хост (VPS / serverless) запущен и доступен
- [ ] Webhook бота подключён через `setWebhook` с `secret_token`

### Smoke test финальный

- [ ] Открыть бота → `/start` → команда работает
- [ ] Открыть MiniApp через MainButton бота → загружается
- [ ] Виден главный экран, личный профиль
- [ ] Нативные кнопки `MainButton`/`BackButton` работают
- [ ] `HapticFeedback` отзывается на iOS/Android
- [ ] Тёмная и светлая тема выглядят корректно
- [ ] На macOS Telegram Desktop — раскрытие в fullscreen работает (видео не чернеет)
- [ ] Загрузка большого файла (>10 MB) — не падает по `bodySizeLimit`
- [ ] Скачивание файла на iPhone Telegram — файл целый, не обрезан

### Мониторинг

- [ ] Vercel logs читаются (`vercel logs` или dashboard)
- [ ] Critical actions логируются (создание профиля, оплата, ошибки auth)
- [ ] Sentry / другая error-tracker система подключена (опционально)

---

## Частые вопросы

**Q: Можно ли сделать MiniApp без бота?**
A: Технически — нет, MiniApp всегда привязан к боту. Но бот может быть «пустой»: только команда `/start` + кнопка «Открыть приложение». Дальше вся логика в MiniApp.

**Q: Как принимать оплату внутри MiniApp?**
A: Два варианта:
1. **Telegram Stars** — Telegram'овская валюта, оплата через `tg.openInvoice`. Telegram забирает 30 %.
2. **Внешняя оплата** — отправляешь пользователя на свой landing с ЮKassa / Stripe / PayPal через `tg.openLink`. После оплаты — webhook от платёжки → апдейт профиля → бот шлёт сообщение «оплата прошла».

**Q: Может ли MiniApp работать офлайн?**
A: Service Workers внутри Telegram WebView ограничены. Полноценный офлайн — нет. Но Next.js кэширование статики на CDN даёт «псевдо-офлайн» для повторных открытий.

**Q: Как тестировать локально?**
A: 
- Dev Telegram-клиент → `t.me/botfather` → создать тестового бота
- `vercel preview` URL подставить в Menu Button бота
- ИЛИ настроить локальный mock через `DEV_MOCK_TG_ID` (env-переменная), чтобы открывать `localhost:3000` напрямую в браузере с подделанным `tgUser.id`

**Q: Что делать, если студент открыл MiniApp в обычном браузере (не Telegram)?**
A: В `TelegramProvider` проверь `!tg || !tg.initData` → редиректь на бота:
```typescript
window.location.href = 'https://t.me/your_bot';
```

---

## Дальше

После того как бот + MiniApp задеплоены и smoke-test пройден — можно добавлять фичи. Берёшь следующий промпт из `seed-data/toolkit/`:

- `2-13-SPEC_WRITER_PROMPT.md` — спецификация для новых фич
- `3-17-CLAUDE_CODE_SETUP_GENERATOR.md` — пакет субагентов под твою архитектуру
- `4-22-CODE_REVIEW_PROMPT.md` — code review перед merge
- `4-23-SECURITY_REVIEW_PROMPT.md` — security аудит

---

*Гид собран на опыте сборки и эксплуатации MiniApp платформы AI-Архитектор: 100+ студентов, ~50 уроков, защищённое видео, AI-наставник, сообщество с лентой и картой. Все «❗ Гочи» — это вещи, на которых мы лично спотыкались в продакшне.*

*Версия: Апрель 2026*
