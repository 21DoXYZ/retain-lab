"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { Button } from "./Button";

export { Spinner } from "./Spinner";

/**
 * Loading / empty / error primitives — one of the four required screen states
 * (plan §0.6). Available standalone and embedded in DataTable / SCard.
 */

/** Shimmer block for loading skeletons (Tailwind animate-pulse on a hairline). */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-hair2/70", className)} />;
}

/** A few stacked skeleton lines. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={cn("h-3.5", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

interface StateBlockProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

function StateBlock({ icon, title, description, action, className }: StateBlockProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center gap-2 px-6 py-12",
        className,
      )}
    >
      {icon ? <div className="text-[34px] leading-none opacity-80">{icon}</div> : null}
      <div className="text-slate font-semibold text-[15px]">{title}</div>
      {description ? (
        <div className="text-steel text-[13px] max-w-md leading-relaxed">{description}</div>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/**
 * EmptyState — explains why there is nothing and what to do next
 * (plan: "пояснение + что сделать").
 */
interface EmptyStateProps {
  title?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  icon = "🗂",
  action,
  className,
}: EmptyStateProps) {
  const t = useT();
  return (
    <StateBlock
      icon={icon}
      title={title ?? t("ui.empty.title")}
      description={description}
      action={action}
      className={className}
    />
  );
}

/**
 * ErrorState — message + retry (plan: "сообщение + повтор"). `onRetry` makes
 * the consumer a Client Component (standard Next pattern).
 */
interface ErrorStateProps {
  title?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

export function ErrorState({
  title,
  description,
  icon = "⚠️",
  onRetry,
  retryLabel,
  className,
}: ErrorStateProps) {
  const t = useT();
  return (
    <StateBlock
      icon={icon}
      title={title ?? t("ui.error.title")}
      description={description ?? t("ui.error.description")}
      action={
        onRetry ? (
          <Button variant="ghost" onClick={onRetry}>
            {retryLabel ?? t("ui.error.retry")}
          </Button>
        ) : null
      }
      className={className}
    />
  );
}
