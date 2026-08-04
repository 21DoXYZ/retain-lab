/**
 * Client-safe i18n barrel. Import everything for screens from here:
 *   import { I18nProvider, useT, LocaleSwitcher } from "@/lib/i18n";
 *
 * NOTE: resolveLocale() is intentionally NOT re-exported — it imports
 * next/headers and is server-only. Import it directly in Server Components:
 *   import { resolveLocale } from "@/lib/i18n/server";
 */

export {
  LOCALES,
  DEFAULT_LOCALE,
  LOCALE_COOKIE,
  LOCALE_LABELS,
  LOCALE_NAMES,
  isLocale,
  type Locale,
} from "./config";
export { getMessages } from "./messages";
export type { MessageKey, Messages } from "./dictionaries/ru";
export { I18nProvider, useI18n, useT, useLocale } from "./provider";
export { LocaleSwitcher } from "./LocaleSwitcher";
