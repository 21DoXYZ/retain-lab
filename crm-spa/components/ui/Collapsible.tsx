"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";

/**
 * Collapsible section — 1:1 with the board `.sec.coll` (native <details>/<summary>).
 * Header shows «<emoji> <title> (<count>) — <hint>» with a right-aligned toggle
 * cue: «нажми, чтобы развернуть ▾» when closed, «свернуть ▴» when open (CSS
 * ::after, mirrors player_board.py .sec.coll>summary::after). Default closed for
 * the long tables the board also collapses (Депозиты / Лог сессий / Траектория).
 */
interface CollapsibleProps {
  title: ReactNode;
  /** Count shown in parentheses next to the title (e.g. number of rows). */
  count?: number;
  /** Muted description after the title. */
  hint?: ReactNode;
  /** Open on first render (default: closed, like the board). */
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}

export function Collapsible({
  title,
  count,
  hint,
  defaultOpen = false,
  children,
  className,
}: CollapsibleProps) {
  const t = useT();
  return (
    <details
      open={defaultOpen}
      className={cn(
        "group bg-canvas border border-hair2 rounded-card px-5 py-[18px] [&[open]]:pb-5",
        className,
      )}
    >
      <summary className="flex items-center gap-2 cursor-pointer list-none select-none [&::-webkit-details-marker]:hidden">
        <span className="font-extrabold text-[18px] tracking-[-0.4px] text-ink">
          {title}
          {count != null ? <span className="text-steel font-semibold"> ({count})</span> : null}
        </span>
        {hint ? <span className="text-[12.5px] text-steel font-normal">{hint}</span> : null}
        <span className="ml-auto text-[11px] font-normal text-stone whitespace-nowrap">
          <span className="group-open:hidden">{t("ui.collapsible.expand")}</span>
          <span className="hidden group-open:inline">{t("ui.collapsible.collapse")}</span>
        </span>
      </summary>
      <div className="mt-4">{children}</div>
    </details>
  );
}
