/**
 * Message resolution: merge a locale's Partial dictionary over the ru base so
 * every key always resolves. Empty-string overrides are ignored (they fall back
 * to ru) — that is what makes the tr stub safe. Client-safe (no next/headers).
 */
import { ru, type MessageKey, type Messages } from "./dictionaries/ru";
import { en } from "./dictionaries/en";
import { tr } from "./dictionaries/tr";
import type { Locale } from "./config";

const OVERRIDES: Record<Locale, Partial<Messages>> = {
  ru: {},
  en,
  tr,
};

/**
 * Fully-resolved dictionary for `locale`: ru base with the locale's non-empty
 * overrides applied. Cheap; the provider memoises it per locale.
 */
export function getMessages(locale: Locale): Messages {
  const overrides = OVERRIDES[locale] ?? {};
  const resolved: Messages = { ...ru };
  for (const key of Object.keys(overrides) as MessageKey[]) {
    const value = overrides[key];
    if (value != null && value !== "") resolved[key] = value;
  }
  return resolved;
}
