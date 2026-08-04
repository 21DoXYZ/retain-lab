import { PageHeader, Panel, Skeleton } from "@/components/ui";
import { getMessages } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/** Route-level loading state for /segments (one of the four required states). */
export default async function SegmentsLoading() {
  const m = getMessages(await resolveLocale());
  return (
    <>
      <PageHeader title={m["automation.title"]} lead={m["automation.lead"]} />
      <div className="mt-5">
        <Panel>
          <div className="p-4 space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
