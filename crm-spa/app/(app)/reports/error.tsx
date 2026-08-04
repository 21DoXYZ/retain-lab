"use client";

import { PageHeader, ErrorState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";

/** Route-level error для /reports (одно из четырёх обязательных состояний). */
export default function ReportsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t("reports.title")} />
      <div className="mt-6">
        <ErrorState
          title={t("reports.error.title")}
          description={flaskErrorText(error, t, "reports.error.desc")}
          onRetry={reset}
        />
      </div>
    </>
  );
}
