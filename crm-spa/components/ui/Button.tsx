"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Spinner } from "./Spinner";

/**
 * Button — matches the dashboard.
 *  - primary : dark ink fill (board .btn — the on-screen action button)
 *  - brand   : blue fill (SELLRISE "primary CTA" / nav-active blue)
 *  - ghost   : bordered, blue on hover (board .pager a)
 * All share 8px radius, 42px height (board controls).
 */
export type ButtonVariant = "primary" | "brand" | "ghost";
export type ButtonSize = "md" | "sm";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children: ReactNode;
}

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-ink text-white hover:bg-slate",
  brand: "bg-primary text-white hover:bg-primary-d",
  ghost: "bg-canvas text-slate border border-hair2 hover:border-primary hover:text-primary",
};

const SIZE: Record<ButtonSize, string> = {
  md: "h-[42px] px-[18px] text-sm",
  sm: "h-[34px] px-3.5 text-[13px]",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  children,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-ctl font-medium transition-colors",
        "disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner size={16} /> : null}
      {children}
    </button>
  );
}
