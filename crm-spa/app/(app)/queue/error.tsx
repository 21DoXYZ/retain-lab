"use client";

import { PageHeader, ErrorState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";

/** Route-level error state for /queue (one of the four required states). */
export default function QueueError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t("players.queue.title")} />
      <div className="mt-6">
        <ErrorState
          title={t("players.queue.error.title")}
          description={flaskErrorText(error, t, "players.queue.error.desc")}
          onRetry={reset}
        />
      </div>
    </>
  );
}
