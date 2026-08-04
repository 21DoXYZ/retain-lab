/**
 * SERVER-ONLY locale resolution. Imports next/headers, so this must be pulled in
 * from Server Components / Route Handlers only — NOT from the client barrel
 * (lib/i18n/index). Import it directly:  import { resolveLocale } from "@/lib/i18n/server";
 *
 * Reads the `crm_locale` cookie (written by the client LocaleSwitcher) and
 * returns the active locale, defaulting to ru. Pass the result into
 * <I18nProvider initialLocale=...> so the first client render matches the cookie
 * (no hydration flash).
 */
import { cookies } from "next/headers";
import { DEFAULT_LOCALE, LOCALE_COOKIE, isLocale, type Locale } from "./config";

export async function resolveLocale(): Promise<Locale> {
  const store = await cookies();
  const value = store.get(LOCALE_COOKIE)?.value;
  return isLocale(value) ? value : DEFAULT_LOCALE;
}
