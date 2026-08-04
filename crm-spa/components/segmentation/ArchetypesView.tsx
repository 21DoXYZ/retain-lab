"use client";

import { PageHeader, Card, ErrorState, Skeleton } from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSegmentationData } from "./useSegmentationData";
import type { ArchetypesResponse, Archetype } from "./types";

/**
 * /archetypes — behavioural player archetypes, 1:1 with the board's
 * archetypes() page. Classification (PERSONA_SQL) and numbers come from
 * /api/v1/archetypes. Layout mirrors the board `.arcard`: emoji + name + desc,
 * count/pct, a proportional gradient bar, and a 5-metric stat row.
 */

const ARCHETYPE_GRID = "grid gap-3.5 [grid-template-columns:repeat(auto-fill,minmax(380px,1fr))]";
const BAR_GRADIENT = "linear-gradient(90deg,#2563eb,#60a5fa)";

interface StatProps {
  label: string;
  value: string;
}

function Stat({ label, value }: StatProps) {
  return (
    <div className="text-center">
      <span className="block text-[10px] uppercase tracking-[0.3px] text-steel">{label}</span>
      <b className="font-mono text-[13px] font-semibold">{value}</b>
    </div>
  );
}

function ArchetypeCard({ a, maxCount }: { a: Archetype; maxCount: number }) {
  const t = useT();
  return (
    <Card className="px-[18px] py-4">
      <div className="flex items-center gap-3">
        <span className="text-[30px] leading-none">{a.emoji}</span>
        <div className="min-w-0 flex-1">
          <div className="text-base font-bold">{a.name}</div>
          <div className="mt-0.5 text-[12.5px] text-steel">{a.desc}</div>
        </div>
        <div className="text-right">
          <b className="font-mono text-xl font-extrabold">{formatInt(a.count)}</b>
          <span className="block text-[11px] text-steel">{a.pct}%</span>
        </div>
      </div>

      <div className="my-3 h-1.5 overflow-hidden rounded-full bg-hair2">
        <i
          className="block h-full"
          style={{ width: `${Math.round((a.count / maxCount) * 100)}%`, background: BAR_GRADIENT }}
        />
      </div>

      <div className="grid grid-cols-5 gap-2">
        <Stat label={t("segmentation.archetypes.stat.avgBet")} value={`${formatInt(a.avg_bet)} ₺`} />
        <Stat label={t("segmentation.archetypes.stat.activeDays")} value={String(a.active_days)} />
        <Stat label={t("segmentation.archetypes.stat.games")} value={String(a.distinct_games)} />
        <Stat label={t("segmentation.archetypes.stat.depositors")} value={`${formatInt(a.depositor_pct)}%`} />
        <Stat label={t("segmentation.archetypes.stat.turnover")} value={`${a.turnover_mn} Mn`} />
      </div>
    </Card>
  );
}

function ArchetypeGridSkeleton() {
  return (
    <div className={ARCHETYPE_GRID}>
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i} className="px-[18px] py-4">
          <div className="flex items-center gap-3">
            <Skeleton className="h-8 w-8 rounded-full" />
            <div className="flex-1">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="mt-1.5 h-3 w-40" />
            </div>
            <Skeleton className="h-6 w-12" />
          </div>
          <Skeleton className="my-3 h-1.5 w-full" />
          <Skeleton className="h-6 w-full" />
        </Card>
      ))}
    </div>
  );
}

export function ArchetypesView() {
  const t = useT();
  const { state, data, error, reload } = useSegmentationData<ArchetypesResponse>(
    "/api/v1/archetypes",
    (d) => d.archetypes.length === 0,
  );

  const maxCount = data ? Math.max(...data.archetypes.map((a) => a.count), 1) : 1;

  return (
    <>
      <PageHeader
        title={t("segmentation.archetypes.title")}
        accent={t("segmentation.archetypes.accent")}
        lead={
          data
            ? t("segmentation.archetypes.lead.withCount", { n: formatInt(data.total) })
            : t("segmentation.archetypes.lead.fallback")
        }
      />

      {state === "error" ? (
        <Card className="mt-6">
          <ErrorState description={error ?? undefined} onRetry={reload} />
        </Card>
      ) : state === "loading" || !data ? (
        <div className="mt-6">
          <ArchetypeGridSkeleton />
        </div>
      ) : (
        <div className={`mt-6 ${ARCHETYPE_GRID}`}>
          {data.archetypes.map((a) => (
            <ArchetypeCard key={a.persona} a={a} maxCount={maxCount} />
          ))}
        </div>
      )}
    </>
  );
}
