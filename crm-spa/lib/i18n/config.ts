/**
 * i18n configuration — the single source of truth for the supported locales,
 * the default, and the persistence cookie. Client-safe (no next/headers here),
 * so it can be imported from both Server Components and "use client" code.
 *
 * Locales (SPA_BUILD_PLAN.md §6 / ТЗ п.7):
 *   ru — base language (source of truth for every key),
 *   en — first additional language (key translations wired in),
 *   tr — reserved stub (empty values fall back to ru until translated).
 */

export const LOCALES = ["ru", "en", "tr"] as const;
export type Locale = (typeof LOCALES)[number];

/** Base language — every key is defined here; other locales fall back to it. */
export const DEFAULT_LOCALE: Locale = "ru";

/** Cookie the switcher writes and the server reads (resolveLocale). */
export const LOCALE_COOKIE = "crm_locale";

/** Short label shown in the language switcher. */
export const LOCALE_LABELS: Record<Locale, string> = {
  ru: "RU",
  en: "EN",
  tr: "TR",
};

/** Full name (for tooltips / aria). */
export const LOCALE_NAMES: Record<Locale, string> = {
  ru: "Русский",
  en: "English",
  tr: "Türkçe",
};

export function isLocale(value: string | undefined | null): value is Locale {
  return !!value && (LOCALES as readonly string[]).includes(value);
}
