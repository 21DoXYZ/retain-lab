import { PageHeader, Panel, SCardGrid, SCard, Skeleton } from "@/components/ui";
import { getMessages } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/** Route-level loading state for /queue (one of the four required states). */
export default async function QueueLoading() {
  const m = getMessages(await resolveLocale());
  return (
    <>
      <PageHeader
        title={m["players.queue.title"]}
        lead={m["players.queue.loading.lead"]}
      />
      <SCardGrid className="mt-5 lg:grid-cols-3">
        <SCard label={m["players.queue.card.inQueue"]} value="" loading />
        <SCard label={m["players.queue.card.planToday"]} value="" loading />
        <SCard label={m["players.queue.card.overdue"]} value="" loading />
      </SCardGrid>
      <div className="mt-5">
        <Panel>
          <div className="p-4 space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
