import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Skeleton } from "./States";

/**
 * SCard — KPI stat card, 1:1 with the board .scard: uppercase label, big
 * value, sub-text, corner icon, optional sparkline slot. Variants:
 *  - default : white on hairline border
 *  - cream   : blue-50 fill, blue-100 border (board .scard.cream)
 *  - alert   : blue-50 fill, 1.5px primary border (board .scard.alert)
 *  - orange  : white card, value rendered in primary blue (board .scard.orange)
 * Value tone: pass valueTone 'pos' | 'neg' to colour the number.
 */
export type SCardVariant = "default" | "cream" | "alert" | "orange";
export type ValueTone = "default" | "pos" | "neg";

interface SCardProps {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  /** Дельта к периоду сравнения (0.2): цветной бейдж «▲ 12%» под значением. */
  delta?: ReactNode;
  /** Emoji or node shown top-right at ~45% opacity. */
  icon?: ReactNode;
  variant?: SCardVariant;
  valueTone?: ValueTone;
  /** Sparkline / decoration pinned to the card bottom (e.g. an SVG). */
  spark?: ReactNode;
  /** Renders the loading skeleton state instead of content. */
  loading?: boolean;
  /** Native hover tooltip on the tile (board `.scard` SCARD_TIP, player_board.py:1305). */
  title?: string;
  className?: string;
}

const VARIANT_CLASS: Record<SCardVariant, string> = {
  default: "bg-canvas border-hair",
  cream: "bg-cream border-beige",
  alert: "bg-cream border-primary border-[1.5px]",
  orange: "bg-canvas border-hair",
};

const TONE_CLASS: Record<ValueTone, string> = {
  default: "text-ink",
  pos: "text-pos",
  neg: "text-neg",
};

export function SCard({
  label,
  value,
  sub,
  delta,
  icon,
  variant = "default",
  valueTone = "default",
  spark,
  loading = false,
  title,
  className,
}: SCardProps) {
  const valueColor = variant === "orange" && valueTone === "default" ? "text-primary" : TONE_CLASS[valueTone];

  if (loading) {
    return (
      <div
        className={cn(
          "relative overflow-hidden rounded-card border px-5 py-[18px] min-h-[128px]",
          VARIANT_CLASS.default,
          className,
        )}
      >
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-8 w-32 mt-3" />
        <Skeleton className="h-3 w-40 mt-3" />
      </div>
    );
  }

  return (
    <div
      title={title}
      className={cn(
        "relative overflow-hidden rounded-card border px-5 py-[18px] min-h-[128px]",
        VARIANT_CLASS[variant],
        className,
      )}
    >
      {icon ? (
        <div className="absolute top-[15px] right-[18px] text-base opacity-45 z-[2]">{icon}</div>
      ) : null}
      <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel">{label}</div>
      <div
        className={cn(
          "font-extrabold text-[32px] leading-[1.05] mt-[9px] tracking-[-1px] relative z-[2]",
          valueColor,
        )}
      >
        {value}
      </div>
      {sub || delta ? (
        <div className="text-xs text-steel mt-2 relative z-[2] flex items-center gap-1.5 flex-wrap">
          {sub}{delta}
        </div>
      ) : null}
      {spark ? <div className="absolute left-0 right-0 bottom-0 h-[30px] z-[1]">{spark}</div> : null}
    </div>
  );
}

/** Grid of KPI cards — board .cards (4 columns, responsive). */
export function SCardGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "grid gap-4 grid-cols-2 lg:grid-cols-4",
        className,
      )}
    >
      {children}
    </div>
  );
}
