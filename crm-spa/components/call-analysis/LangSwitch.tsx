"use client";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import type { ViewLang } from "./TranscriptView";

/**
 * Переключатель языка транскрипта (§10.3): [Русский][English][Оригинал TR].
 * Перевод грузится по требованию (в TranscriptView), здесь только выбор.
 */
const OPTIONS: { lang: ViewLang; labelKey: MessageKey }[] = [
  { lang: "ru", labelKey: "calls.transcript.langRu" },
  { lang: "en", labelKey: "calls.transcript.langEn" },
  { lang: "tr", labelKey: "calls.transcript.original" },
];

export function LangSwitch({
  value,
  onChange,
}: {
  value: ViewLang;
  onChange: (lang: ViewLang) => void;
}) {
  const t = useT();
  return (
    <div className="inline-flex rounded-ctl border border-hair2 overflow-hidden text-[12.5px]">
      {OPTIONS.map((o) => (
        <button
          key={o.lang}
          type="button"
          onClick={() => onChange(o.lang)}
          className={cn(
            "px-2.5 py-1.5 cursor-pointer transition-colors border-l border-hair2 first:border-l-0",
            value === o.lang ? "bg-ink text-white" : "bg-canvas text-steel hover:text-primary",
          )}
        >
          {t(o.labelKey)}
        </button>
      ))}
    </div>
  );
}
