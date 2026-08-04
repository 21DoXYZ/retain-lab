import { PageHeader, Skeleton } from "@/components/ui";
import { getMessages } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/** Route-level loading для /reports (одно из четырёх обязательных состояний). */
export default async function ReportsLoading() {
  const m = getMessages(await resolveLocale());
  return (
    <>
      <PageHeader title={m["reports.title"]} lead={m["reports.lead"]} />
      <div className="mt-6 space-y-3">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    </>
  );
}
