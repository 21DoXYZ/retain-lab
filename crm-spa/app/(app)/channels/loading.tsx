import { PageHeader, Card, Skeleton } from "@/components/ui";
import { getMessages } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/** Route-level loading state for /channels (one of the four required states). */
export default async function ChannelsLoading() {
  const m = getMessages(await resolveLocale());
  return (
    <>
      <PageHeader title={m["segmentation.channels.title"]} lead={m["segmentation.channels.lead"]} />
      <div className="mt-6 grid gap-3.5 [grid-template-columns:repeat(auto-fill,minmax(320px,1fr))]">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <Skeleton className="h-2.5 w-8" />
            <Skeleton className="mt-1.5 h-4 w-40" />
            <Skeleton className="mt-3 h-[180px] w-full" />
          </Card>
        ))}
      </div>
    </>
  );
}
