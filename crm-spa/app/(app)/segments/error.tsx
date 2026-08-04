"use client";

import { PageHeader, ErrorState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";

/** Route-level error state for /segments (one of the four required states). */
export default function SegmentsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t("automation.title")} />
      <div className="mt-6">
        <ErrorState
          title={t("automation.error.title")}
          description={flaskErrorText(error, t, "automation.error.desc")}
          onRetry={reset}
        />
      </div>
    </>
  );
}
