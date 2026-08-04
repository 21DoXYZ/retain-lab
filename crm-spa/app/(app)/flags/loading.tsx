import { PageHeader, Panel, SCardGrid, SCard, Skeleton } from "@/components/ui";
import { getMessages } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/** Route-level loading state for /flags (one of the four required states). */
export default async function FlagsLoading() {
  const m = getMessages(await resolveLocale());
  return (
    <>
      <PageHeader title={m["risk.flags.title"]} lead={m["risk.flags.loading.lead"]} />
      <SCardGrid className="mt-[18px] lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <SCard key={i} label="" value="" loading />
        ))}
      </SCardGrid>
      <div className="mt-4">
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
