"use client";

import { PageHeader, ErrorState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";

/** Route-level error state for /pool (one of the four required states). */
export default function PoolError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t("players.pool.title")} />
      <div className="mt-6">
        <ErrorState
          title={t("players.pool.error.title")}
          description={flaskErrorText(error, t, "players.pool.error.desc")}
          onRetry={reset}
        />
      </div>
    </>
  );
}
