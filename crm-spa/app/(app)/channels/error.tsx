"use client";

import { PageHeader, ErrorState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";

/** Route-level error state for /channels (one of the four required states). */
export default function ChannelsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t("segmentation.channels.title")} />
      <div className="mt-6">
        <ErrorState
          description={flaskErrorText(error, t, "segmentation.channels.error.desc")}
          onRetry={reset}
        />
      </div>
    </>
  );
}
