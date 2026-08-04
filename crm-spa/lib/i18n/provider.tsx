"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { DEFAULT_LOCALE, LOCALE_COOKIE, type Locale } from "./config";
import { getMessages } from "./messages";
import type { MessageKey } from "./dictionaries/ru";

/**
 * Client i18n runtime. Wrap a screen subtree in <I18nProvider initialLocale=...>
 * (the server resolves initialLocale from the cookie via resolveLocale()), then
 * read strings with useT():
 *
 *   const t = useT();
 *   <h1>{t("calendar.title")}</h1>
 *   <span>{t("affiliate.lead", { code: "AF104" })}</span>   // {var} interpolation
 *
 * setLocale() (used by <LocaleSwitcher/>) updates the subtree instantly AND
 * persists the choice in a cookie + router.refresh(), so other screens and the
 * next server render pick it up too.
 */

type Vars = Record<string, string | number>;

interface I18nContextValue {
  locale: Locale;
  t: (key: MessageKey, vars?: Vars) => string;
  setLocale: (locale: Locale) => void;
}

const I18nContext = createContext<I18nContextValue | null>(null);

/** Replace {name} placeholders; unknown placeholders are left intact. */
function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  );
}

export function I18nProvider({
  initialLocale = DEFAULT_LOCALE,
  children,
}: {
  initialLocale?: Locale;
  children: ReactNode;
}) {
  const router = useRouter();
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const messages = useMemo(() => getMessages(locale), [locale]);

  const t = useCallback(
    (key: MessageKey, vars?: Vars) => interpolate(messages[key] ?? key, vars),
    [messages],
  );

  const setLocale = useCallback(
    (next: Locale) => {
      setLocaleState(next);
      document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
      // Re-render server components so their initialLocale matches on next nav.
      router.refresh();
    },
    [router],
  );

  const value = useMemo<I18nContextValue>(
    () => ({ locale, t, setLocale }),
    [locale, t, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n/useT/useLocale must be used inside <I18nProvider>.");
  }
  return ctx;
}

/** Just the translate function — the common case. */
export function useT(): I18nContextValue["t"] {
  return useI18n().t;
}

/** Current locale + setter (for a switcher or locale-aware formatting). */
export function useLocale(): { locale: Locale; setLocale: (l: Locale) => void } {
  const { locale, setLocale } = useI18n();
  return { locale, setLocale };
}
