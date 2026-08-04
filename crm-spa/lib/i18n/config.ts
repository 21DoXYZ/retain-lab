/**
 * i18n configuration — the single source of truth for the supported locales,
 * the default, and the persistence cookie. Client-safe (no next/headers here),
 * so it can be imported from both Server Components and "use client" code.
 *
 * SaaS preset (REBUILD-TASK.md §0.1): en is the default and the ONLY shipped
 * locale. The ru dictionary stays in the repo as the key inventory / fallback
 * for keys not yet covered by en; ru/tr are not selectable and the
 * LocaleSwitcher is not rendered.
 */

export const LOCALES = ["en"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

/** Cookie the switcher writes and the server reads (resolveLocale). */
export const LOCALE_COOKIE = "crm_locale";

/** Short label shown in the language switcher. */
export const LOCALE_LABELS: Record<Locale, string> = {
  en: "EN",
};

/** Full name (for tooltips / aria). */
export const LOCALE_NAMES: Record<Locale, string> = {
  en: "English",
};

export function isLocale(value: string | undefined | null): value is Locale {
  return !!value && (LOCALES as readonly string[]).includes(value);
}
