import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Pill — small status/label pill (board .pill). `live` renders the solid blue
 * variant (board .pill.live). Non-interactive; for clickable filters use Chip.
 */
interface PillProps {
  children: ReactNode;
  live?: boolean;
  className?: string;
}

export function Pill({ children, live = false, className }: PillProps) {
  return (
    <span
      className={cn(
        "inline-block text-[12.5px] font-medium rounded-full px-3 py-1.5",
        live ? "bg-primary text-white" : "bg-cream text-ink",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Row of pills (board .pills). */
export function PillRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex gap-2 flex-wrap", className)}>{children}</div>;
}
