"use client";

import { PageHeader, ErrorState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";

/** Route-level error state for /verdicts (one of the four required states). */
export default function VerdictsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t("traffic.verdicts.title")} />
      <div className="mt-6">
        <ErrorState
          title={t("traffic.verdicts.error.title")}
          description={flaskErrorText(error, t, "traffic.verdicts.error.desc")}
          onRetry={reset}
        />
      </div>
    </>
  );
}
