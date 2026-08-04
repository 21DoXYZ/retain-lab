# i18n — localization scaffold

Lightweight, config-free localization for the CRM-SPA. No routing segments, no
middleware — so it does **not** touch the `(app)` layout or `proxy.ts`. A screen
opts in by wrapping its client subtree in `<I18nProvider>` and reading strings
through `useT()`.

Locales (ТЗ п.7 / plan §6): **ru** base · **en** wired in · **tr** stub (empty
values fall back to ru until translated).

## Files

| File | Role |
|------|------|
| `config.ts` | locales list, default, cookie name, labels. Client-safe. |
| `dictionaries/ru.ts` | **base dictionary — source of truth for the key set.** |
| `dictionaries/en.ts` | English translations (`Partial<Messages>`). |
| `dictionaries/tr.ts` | Turkish stub (`Partial<Messages>`, mostly empty). |
| `messages.ts` | `getMessages(locale)` — merges a locale over ru. |
| `provider.tsx` | `<I18nProvider>`, `useT`, `useLocale`, `useI18n`. Client. |
| `LocaleSwitcher.tsx` | RU/EN/TR segmented control. Client. |
| `server.ts` | `resolveLocale()` — reads the cookie. **Server-only.** |
| `index.ts` | client-safe barrel (does **not** re-export `server.ts`). |

## Using it in a screen

Server Component (page) resolves the cookie and passes it down:

```tsx
import { resolveLocale } from "@/lib/i18n/server";      // server-only import
import { I18nProvider } from "@/lib/i18n";

export default async function Page() {
  const locale = await resolveLocale();
  return (
    <I18nProvider initialLocale={locale}>
      <MyClientScreen />
    </I18nProvider>
  );
}
```

Client Component reads strings:

```tsx
"use client";
import { useT, LocaleSwitcher } from "@/lib/i18n";

export function MyClientScreen() {
  const t = useT();
  return (
    <>
      <PageHeader title={t("calendar.title")} right={<LocaleSwitcher />} />
      <p>{t("affiliate.lead", { code: "AF104" })}</p>   {/* {var} interpolation */}
    </>
  );
}
```

## Adding strings (for every agent)

1. **Add the key to `dictionaries/ru.ts` first**, with a Russian value. ru
   defines the key set — a key missing from ru is not a valid `MessageKey`.
2. Optionally translate it in `dictionaries/en.ts` / `dictionaries/tr.ts`.
   These are `Partial<Messages>`: any key you omit — or leave as `""` — renders
   the ru value at runtime. Nothing breaks if a translation is missing.
3. Use it: `t("your.key")`. TypeScript autocompletes keys and rejects typos.

**Do not** re-key or wrap other agents' screens — they currently render literal
ru strings; wrapping them in `t()` is a later, deliberate pass. This scaffold is
the mechanism, not a mandate to convert every screen now.

## Where it is live

B4's screens (`/calendar`, `/affiliate`) render fully through `useT()` and carry
the `<LocaleSwitcher/>`, so RU↔EN↔TR switching is demonstrable end-to-end today.

## Optional future step (not done here — out of B4's zone)

To make the switcher global (one instance in the top chrome for the whole app),
add `<I18nProvider initialLocale={await resolveLocale()}>` around `AppChrome` in
`app/(app)/layout.tsx` and drop `<LocaleSwitcher/>` into the header. That is a
one-line change owned by B1/the orchestrator; the scaffold already supports it.
