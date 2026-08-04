import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Card — white surface, hairline border, 12px radius (board .panel/.chartbox).
 * Use for generic content blocks and chart boxes.
 */
interface CardProps {
  children: ReactNode;
  className?: string;
  /** Adds the standard 18px/20px inner padding (board chartbox). */
  padded?: boolean;
}

export function Card({ children, className, padded = true }: CardProps) {
  return (
    <div
      className={cn(
        "bg-canvas border border-hair rounded-card",
        padded && "px-5 py-[18px]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** ChartBox — Card with a title + caption header (board .chartbox). */
interface ChartBoxProps {
  title: ReactNode;
  caption?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function ChartBox({ title, caption, children, className }: ChartBoxProps) {
  return (
    <Card className={className}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {caption ? <div className="text-xs text-steel mb-2.5">{caption}</div> : null}
      {children}
    </Card>
  );
}

/**
 * Panel — same surface as Card but clips content (board .panel). Meant to wrap
 * tables so the sticky header / rounded corners render cleanly.
 */
interface PanelProps {
  children: ReactNode;
  className?: string;
}

export function Panel({ children, className }: PanelProps) {
  return (
    <div className={cn("bg-canvas border border-hair rounded-card overflow-hidden", className)}>
      {children}
    </div>
  );
}

/** Banner — cream callout with blue left rule (board .banner). */
export function Banner({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "bg-cream border border-beige border-l-[3px] border-l-primary rounded-card px-[18px] py-[15px] mt-6 text-[13.5px] leading-relaxed",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Field — key/value row (board .fld); value is monospaced. */
interface FieldProps {
  label: ReactNode;
  value: ReactNode;
  title?: string;
  className?: string;
}

export function Field({ label, value, title, className }: FieldProps) {
  return (
    <div
      title={title}
      className={cn(
        "flex justify-between items-center gap-2.5 bg-canvas border border-hair rounded-ctl px-[13px] py-[9px] text-[13px]",
        className,
      )}
    >
      <span className="text-steel flex-none whitespace-nowrap">{label}</span>
      <span className="font-mono text-right min-w-0 truncate">{value}</span>
    </div>
  );
}
