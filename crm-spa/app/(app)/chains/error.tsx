"use client";

import { PageHeader, ErrorState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";

/** Route-level error state for /chains (one of the four required states). */
export default function ChainsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t("automation.chains.title")} />
      <div className="mt-6">
        <ErrorState
          title={t("automation.chains.error.title")}
          description={flaskErrorText(error, t, "automation.chains.error.desc")}
          onRetry={reset}
        />
      </div>
    </>
  );
}
