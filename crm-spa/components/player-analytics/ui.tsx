"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Field, EmptyState, Card } from "@/components/ui";
import { useT } from "@/lib/i18n";

/**
 * Shared presentational bits for the analytics card sections — 1:1 with the
 * player_board.py card CSS (tokens only, no new colours/fonts):
 *   SectionH2   → board `.sec h2` (700, 20px, ink) + optional muted caption
 *   FieldsGrid  → board `.fields`  (auto-fill minmax(220px,1fr), gap 9)
 *   Metric      → board `.fld`     (label: mono value)  [wraps ui Field]
 *   KGrid       → board `.kgrid`   (auto-fit minmax(150px,1fr), gap 14)
 *   StatTile    → board compact `.scard{min-height:auto}` KPI tile (rhythm)
 */

export type Tone = "default" | "pos" | "neg";
type Variant = "default" | "cream" | "orange" | "alert";

const TONE: Record<Tone, string> = {
  default: "text-ink",
  pos: "text-pos",
  neg: "text-neg",
};

const VARIANT: Record<Variant, string> = {
  default: "bg-canvas border-hair",
  cream: "bg-cream border-beige",
  orange: "bg-canvas border-hair",
  alert: "bg-cream border-primary border-[1.5px]",
};

/** Board `.sec h2` — section heading (700 · 20px · ink) with a muted caption. */
export function SectionH2({ children, caption }: { children: ReactNode; caption?: ReactNode }) {
  return (
    <h2 className="flex flex-wrap items-baseline gap-2 font-bold text-[20px] leading-tight text-ink mb-3">
      <span>{children}</span>
      {caption ? <span className="text-[13px] font-normal text-steel">{caption}</span> : null}
    </h2>
  );
}

/** Board `.fields` — responsive grid of key/value `.fld` rows. */
export function FieldsGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid gap-[9px] grid-cols-[repeat(auto-fill,minmax(220px,1fr))]", className)}>
      {children}
    </div>
  );
}

/** One board `.fld` row. `value` already formatted; `title` = full hover text. */
export function Metric({ label, value, title }: { label: ReactNode; value: ReactNode; title?: string }) {
  return <Field label={label} value={value} title={title} />;
}

/** Board `.kgrid` — auto-fit KPI-tile grid (LTV / ladder / rhythm stats). */
export function KGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid gap-[14px] grid-cols-[repeat(auto-fit,minmax(150px,1fr))]", className)}>
      {children}
    </div>
  );
}

/** Board compact `.scard{min-height:auto}` — label + big value (rhythm stats). */
export function StatTile({
  label,
  value,
  sub,
  tone = "default",
  variant = "default",
  title,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  variant?: Variant;
  title?: string;
}) {
  const valueColor = variant === "orange" && tone === "default" ? "text-primary" : TONE[tone];
  // Board `.scard`: tall (min-height 128px), 18px/20px padding, 26px value.
  return (
    <div title={title} className={cn("rounded-card border px-5 py-[18px] min-h-[128px] min-w-0", VARIANT[variant])}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel leading-tight">{label}</div>
      <div className={cn("font-extrabold text-[26px] leading-[1.05] mt-[9px] tracking-[-1px]", valueColor)}>
        {value}
      </div>
      {sub ? <div className="text-[12px] text-steel mt-2 leading-snug">{sub}</div> : null}
    </div>
  );
}

/** Soft "нет доступа" block — 403 from a role-restricted endpoint (not an error). */
export function NoAccess({ note }: { note?: ReactNode }) {
  const t = useT();
  return (
    <Card>
      <EmptyState
        icon="🔒"
        title={t("analytics.common.noAccessTitle")}
        description={note ?? t("analytics.common.noAccessDesc")}
      />
    </Card>
  );
}
