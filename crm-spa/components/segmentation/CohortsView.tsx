"use client";

import Link from "next/link";
import { PageHeader, Card, Eyebrow, Banner, ErrorState, EmptyState, Skeleton } from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { useSegmentationData } from "./useSegmentationData";
import { Chart } from "./Chart";
import { cohortOption } from "./chartOptions";
import type { CohortsResponse, CohortItem } from "./types";

/**
 * /cohorts — catalogue of every cohort slice (A1..G29a), 1:1 with the board's
 * cohorts() page. Data + labels come straight from /api/v1/cohorts (shared board
 * cache), so counts match the dashboard exactly. Chart cards use the board's
 * cohortOption() geometry; table cards mirror the board's `.trow` proportional
 * bar list.
 */

/** Board `.trow` list — proportional-bar rows for `table` type cohorts. */
function CohortTable({ rows }: { rows: [string, number][] }) {
  const max = Math.max(...rows.map(([, v]) => v), 1);
  return (
    <div className="flex flex-col gap-[3px]">
      {rows.map(([label, value], i) => (
        <div
          key={`${label}-${i}`}
          className="relative flex justify-between overflow-hidden rounded-md px-[9px] py-[5px] text-xs"
        >
          <span
            className="absolute inset-y-0 left-0 bg-primary/10"
            style={{ width: `${Math.round((value / max) * 100)}%` }}
          />
          <span className="relative z-[1] max-w-[70%] truncate font-mono text-[11px]" title={label}>
            {label}
          </span>
          <span className="relative z-[1] font-mono text-primary">{formatInt(value)}</span>
        </div>
      ))}
    </div>
  );
}

/** One cohort card — id + title, then a chart or the table variant. */
function CohortCard({ item }: { item: CohortItem }) {
  const t = useT();
  const option = item.type === "table" ? null : cohortOption(item);
  return (
    <Card>
      <div className="font-mono text-[10px] text-steel">{item.id}</div>
      <h4 className="mb-2 mt-0.5 text-sm font-semibold">{item.title}</h4>
      {item.type === "table" ? (
        <CohortTable rows={item.rows ?? []} />
      ) : option ? (
        <Chart option={option} height={180} />
      ) : (
        <div className="flex h-[180px] items-center justify-center text-xs text-steel">
          {t("segmentation.cohorts.noData")}
        </div>
      )}
    </Card>
  );
}

const COHORT_GRID = "grid gap-3.5 [grid-template-columns:repeat(auto-fill,minmax(320px,1fr))]";

function CohortGridSkeleton() {
  return (
    <div className={COHORT_GRID}>
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <Skeleton className="h-2.5 w-8" />
          <Skeleton className="mt-1.5 h-4 w-40" />
          <Skeleton className="mt-3 h-[180px] w-full" />
        </Card>
      ))}
    </div>
  );
}

interface CohortsViewProps {
  /** Show ONLY groups whose `name` is in this list (e.g. ["B · Канал"] on /channels). */
  onlyGroups?: string[];
  /** Hide groups whose `name` is in this list (e.g. ["B · Канал"] on /cohorts). */
  excludeGroups?: string[];
  /** Override the PageHeader title (defaults to the cohorts catalogue title). */
  titleKey?: MessageKey;
  /** Override the subtitle/accent (defaults to the server-supplied `meta.subtitle`). */
  subtitleKey?: MessageKey;
  /** Override the lead line under the title. */
  leadKey?: MessageKey;
  /** Small caption-link rendered under the header (e.g. "channel slices moved → Channels"). */
  movedLink?: { href: string; labelKey: MessageKey };
  /** Empty-state copy when the (filtered) group set has nothing to show. */
  emptyKey?: { title: MessageKey; desc: MessageKey };
}

export function CohortsView({
  onlyGroups,
  excludeGroups,
  titleKey,
  subtitleKey,
  leadKey,
  movedLink,
  emptyKey,
}: CohortsViewProps = {}) {
  const t = useT();
  const { state, data, error, reload } = useSegmentationData<CohortsResponse>(
    "/api/v1/cohorts",
    (d) => d.groups.length === 0,
  );

  const title = titleKey ? t(titleKey) : t("segmentation.cohorts.title");
  const subtitle = subtitleKey
    ? t(subtitleKey)
    : (data?.meta.subtitle ?? t("segmentation.cohorts.defaultSubtitle"));
  const lead = leadKey ? t(leadKey) : t("segmentation.cohorts.lead");

  // Клиентская фильтрация групп (данные — тот же /api/v1/cohorts): /channels
  // показывает только «B · Канал», /cohorts эту группу прячет (переехала в Трафик).
  const groups = (data?.groups ?? []).filter((g) => {
    if (onlyGroups && !onlyGroups.includes(g.name)) return false;
    if (excludeGroups && excludeGroups.includes(g.name)) return false;
    return true;
  });

  return (
    <>
      <PageHeader title={title} accent={`· ${subtitle}`} lead={lead} />

      {movedLink ? (
        <p className="mt-2 text-[12.5px] text-steel">
          <Link href={movedLink.href} className="text-primary font-medium hover:underline">
            {t(movedLink.labelKey)}
          </Link>
        </p>
      ) : null}

      {state === "error" ? (
        <Card className="mt-6">
          <ErrorState description={error ?? undefined} onRetry={reload} />
        </Card>
      ) : state === "loading" || !data ? (
        <div className="mt-6 space-y-6">
          <Eyebrow>{t("segmentation.cohorts.loading")}</Eyebrow>
          <CohortGridSkeleton />
        </div>
      ) : groups.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            title={emptyKey ? t(emptyKey.title) : t("segmentation.cohorts.title")}
            description={emptyKey ? t(emptyKey.desc) : t("segmentation.cohorts.noData")}
          />
        </div>
      ) : (
        <div className="mt-6 space-y-6">
          {groups.map((group) => (
            <section key={group.name}>
              <Eyebrow>{group.name}</Eyebrow>
              <div className={COHORT_GRID}>
                {group.items.map((item) => (
                  <CohortCard key={item.id} item={item} />
                ))}
              </div>
            </section>
          ))}

          {data.meta.note ? (
            <Banner>
              ⚠️ {data.meta.note} {t("segmentation.cohorts.banner.asOf", { date: data.meta.as_of })}
            </Banner>
          ) : null}
        </div>
      )}
    </>
  );
}
