"use client";

import { PageHeader, ErrorState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";

/** Route-level error state for /flags (one of the four required states). */
export default function FlagsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t("risk.flags.title")} />
      <div className="mt-6">
        <ErrorState
          title={t("risk.flags.error.title")}
          description={flaskErrorText(error, t, "risk.flags.error.desc")}
          onRetry={reset}
        />
      </div>
    </>
  );
}
