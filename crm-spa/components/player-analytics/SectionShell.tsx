"use client";

"use client";

import type { ReactNode } from "react";
import { Card, SkeletonText, ErrorState, EmptyState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { NoAccess, SectionH2 } from "./ui";
import type { Section } from "./hooks";

/**
 * SectionBody — the four required screen states for one fetched analytics
 * section, without a heading. Reused by SectionShell (adds an Eyebrow) and by
 * the collapsible sections (add a <Collapsible> header instead). State mapping:
 *   loading  → skeleton
 *   403      → soft «нет доступа» (role-restricted endpoint, not a failure)
 *   404      → empty-state
 *   error    → ErrorState + retry
 *   isEmpty()→ empty-state
 *   data     → children(data)
 */
export function SectionBody<T>({
  section,
  isEmpty,
  emptyTitle,
  emptyDescription,
  children,
}: {
  section: Section<T>;
  isEmpty?: (data: T) => boolean;
  emptyTitle?: ReactNode;
  emptyDescription?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  const t = useT();
  const { state, data, error, status, reload } = section;

  if (state === "loading") {
    return (
      <Card>
        <SkeletonText lines={4} />
      </Card>
    );
  }
  if (state === "error" && status === 403) {
    return <NoAccess />;
  }
  if (state === "error" && status === 404) {
    return (
      <Card>
        <EmptyState title={emptyTitle ?? t("analytics.common.noData")} description={emptyDescription} />
      </Card>
    );
  }
  if (state === "error") {
    return (
      <Card>
        <ErrorState description={error ?? undefined} onRetry={reload} />
      </Card>
    );
  }
  if (data && isEmpty?.(data)) {
    return (
      <Card>
        <EmptyState title={emptyTitle ?? t("analytics.common.noData")} description={emptyDescription} />
      </Card>
    );
  }
  return data ? <>{children(data)}</> : null;
}

/** SectionShell — board `.sec h2` heading + SectionBody. For always-open sections. */
export function SectionShell<T>({
  title,
  caption,
  section,
  isEmpty,
  emptyTitle,
  emptyDescription,
  children,
}: {
  title: ReactNode;
  caption?: ReactNode;
  section: Section<T>;
  isEmpty?: (data: T) => boolean;
  emptyTitle?: ReactNode;
  emptyDescription?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  return (
    <section className="mt-6">
      <SectionH2 caption={caption}>{title}</SectionH2>
      <SectionBody
        section={section}
        isEmpty={isEmpty}
        emptyTitle={emptyTitle}
        emptyDescription={emptyDescription}
      >
        {children}
      </SectionBody>
    </section>
  );
}
