"use client";

import { cn } from "@/lib/cn";
import { LOCALES, LOCALE_LABELS, LOCALE_NAMES } from "./config";
import { useI18n } from "./provider";

/**
 * Segmented RU / EN / TR switcher. Styled with design tokens only (matches the
 * board's control look). Drop it into a PageHeader `right` slot; it must sit
 * inside an <I18nProvider>. Switching is instant (state) and persisted (cookie).
 */
export function LocaleSwitcher({ className }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();

  return (
    <div
      role="group"
      aria-label={t("lang.aria")}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-ctl border border-hair2 bg-canvas p-0.5",
        className,
      )}
    >
      {LOCALES.map((code) => {
        const active = code === locale;
        return (
          <button
            key={code}
            type="button"
            onClick={() => setLocale(code)}
            aria-pressed={active}
            title={LOCALE_NAMES[code]}
            className={cn(
              "px-2.5 py-1 rounded-[6px] text-[12px] font-semibold transition-colors cursor-pointer",
              active
                ? "bg-primary text-white"
                : "text-steel hover:text-primary hover:bg-cream",
            )}
          >
            {LOCALE_LABELS[code]}
          </button>
        );
      })}
    </div>
  );
}
