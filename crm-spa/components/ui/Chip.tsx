"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";

/**
 * Chip — filter chip (board .chip / .chip.on). Active state fills with ink.
 * Renders as a <button> by default; pass `href` for link-style filters
 * (the board uses <a> query-param filters).
 */
interface ChipBaseProps {
  children: ReactNode;
  active?: boolean;
  className?: string;
  title?: string;
}

interface ChipButtonProps extends ChipBaseProps {
  href?: undefined;
  onClick?: () => void;
}

interface ChipLinkProps extends ChipBaseProps {
  href: string;
  onClick?: () => void;
}

type ChipProps = ChipButtonProps | ChipLinkProps;

function chipClass(active: boolean, className?: string): string {
  return cn(
    "inline-flex items-center text-[12.5px] rounded-full px-[13px] py-[7px] border transition-colors cursor-pointer",
    active
      ? "bg-ink text-white border-ink"
      : "bg-canvas text-steel border-hair2 hover:border-primary hover:text-primary",
    className,
  );
}

export function Chip(props: ChipProps) {
  const { children, active = false, className, title } = props;
  if (props.href) {
    return (
      <Link href={props.href} onClick={props.onClick} title={title} className={chipClass(active, className)}>
        {children}
      </Link>
    );
  }
  return (
    <button type="button" onClick={props.onClick} title={title} className={chipClass(active, className)}>
      {children}
    </button>
  );
}

/** Filter bar wrapper (board .bar). */
export function ChipBar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex gap-2 flex-wrap items-center my-4", className)}>{children}</div>
  );
}
