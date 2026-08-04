import { PageHeader, Panel, SCardGrid, SCard, Skeleton } from "@/components/ui";
import { getMessages } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/** Route-level loading state for /pool (one of the four required states). */
export default async function PoolLoading() {
  const m = getMessages(await resolveLocale());
  return (
    <>
      <PageHeader title={m["players.pool.title"]} lead={m["players.pool.loading.lead"]} />
      <SCardGrid className="mt-5 lg:grid-cols-4">
        <SCard label={m["players.pool.card.inPool"]} value="" loading />
        <SCard label={m["players.pool.card.selected"]} value="" loading />
        <SCard label={m["players.pool.card.operators"]} value="" loading />
        <SCard label={m["players.pool.card.unassigned"]} value="" loading />
      </SCardGrid>
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
