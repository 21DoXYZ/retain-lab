"use client";

import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";

/**
 * Collapsible — board `<details class="sec coll">` 1:1. Grey summary bar (700 ·
 * 20px · ink) with a rotating blue ▸ marker on the left, «<эмодзи> <Название>
 * (N) — <caption>» text, and a right-aligned hint «нажми, чтобы развернуть ▾» /
 * «свернуть ▴». Default CLOSED for Депозиты / Лог сессий / Бонусы / Траектория.
 *
 * Children stay mounted (only visibility toggles) so the section's own fetch
 * runs eagerly and the header count is known before first open.
 */
export function Collapsible({
  title,
  count,
  caption,
  defaultOpen = false,
  open: openProp,
  onToggle,
  children,
}: {
  title: ReactNode;
  count?: number | null;
  caption?: ReactNode;
  defaultOpen?: boolean;
  /** Управляемый режим (напр., внешнее событие должно раскрыть секцию). */
  open?: boolean;
  onToggle?: (open: boolean) => void;
  children: ReactNode;
}) {
  const t = useT();
  const [internal, setInternal] = useState(defaultOpen);
  const open = openProp ?? internal;
  const toggle = () => (onToggle ? onToggle(!open) : setInternal((o) => !o));

  return (
    <section className="mt-6">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="w-full flex items-center gap-2.5 text-left rounded-[10px] border border-hair3/70 bg-surface hover:bg-hair px-3.5 py-[9px] transition-colors"
      >
        <span
          className={cn(
            "flex-none text-primary text-[18px] leading-none transition-transform",
            open && "rotate-90",
          )}
          aria-hidden
        >
          ▸
        </span>
        <span className="font-bold text-[20px] leading-tight text-ink">
          {title}
          {count != null ? ` (${count})` : ""}
          {caption ? <span className="ml-2 text-[13px] font-normal text-steel">— {caption}</span> : null}
        </span>
        <span className="ml-auto flex-none text-[11px] font-normal text-stone">
          {open ? t("analytics.collapsible.collapse") : t("analytics.collapsible.expand")}
        </span>
      </button>
      <div className={cn("mt-3", !open && "hidden")}>{children}</div>
    </section>
  );
}
