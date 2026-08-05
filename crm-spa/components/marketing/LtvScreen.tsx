"use client";

import {
  PageHeader,
  ModuleHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Card,
  Panel,
  DataTable,
  TierBadge,
  type Column,
} from "@/components/ui";
import { formatInt, formatMoney, formatMoneyMn } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { EChart, CHART_COLORS } from "./EChart";
import { useFlaskData } from "./useFlaskData";
import type { LtvResponse, LtvCurvePoint, LtvTier, YoungWhale } from "./types";

/** Inline sparkline (board `spark`) — cumulative LTV curve pinned to the KPI card. */
function Sparkline({ values }: { values: (number | null)[] }) {
  const nums = values.map((v) => v ?? 0);
  if (nums.length < 2) return null;
  const max = Math.max(...nums);
  const min = Math.min(...nums);
  const span = max - min || 1;
  const pts = nums
    .map((v, i) => {
      const x = (i / (nums.length - 1)) * 100;
      const y = 28 - ((v - min) / span) * 26;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="w-full h-full">
      <polyline points={pts} fill="none" stroke={CHART_COLORS.primary} strokeWidth={1.5} opacity={0.5} />
    </svg>
  );
}

function CurveChart({ curve }: { curve: LtvCurvePoint[] }) {
  const t = useT();
  const avgName = t("marketing.ltv.series.avg");
  const medianName = t("marketing.ltv.series.median");
  const option = {
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis" as const },
    legend: { data: [avgName, medianName], top: 0, textStyle: { color: CHART_COLORS.steel } },
    color: [CHART_COLORS.primary, CHART_COLORS.pos],
    xAxis: {
      type: "category" as const,
      boundaryGap: false,
      data: curve.map((c) => `D${c.day}`),
      axisLine: { lineStyle: { color: CHART_COLORS.hair } },
      axisLabel: { color: CHART_COLORS.steel },
    },
    yAxis: {
      type: "value" as const,
      axisLabel: { color: CHART_COLORS.steel },
      splitLine: { lineStyle: { color: CHART_COLORS.hair } },
    },
    series: [
      {
        name: avgName,
        type: "line" as const,
        smooth: true,
        showSymbol: false,
        areaStyle: { color: "rgba(70,95,255,0.08)" },
        data: curve.map((c) => c.avg),
      },
      {
        name: medianName,
        type: "line" as const,
        smooth: true,
        showSymbol: false,
        data: curve.map((c) => c.median),
      },
    ],
  };
  return <EChart option={option} height={300} />;
}

export function LtvScreen() {
  const t = useT();
  const { state, data, error, reload } = useFlaskData<LtvResponse>("/api/v1/ltv");
  const loading = state === "loading";
  const k = data?.kpi;
  const daySuffix = t("marketing.ltv.daySuffix");

  const curveCols: Column<LtvCurvePoint>[] = [
    { key: "day", header: t("marketing.ltv.col.day"), id: true, render: (r) => `D${r.day}` },
    { key: "cohort", header: t("marketing.ltv.col.cohort"), mono: true, render: (r) => formatInt(r.cohort_n) },
    { key: "avg", header: t("marketing.ltv.col.avgLtv"), mono: true, render: (r) => `${formatInt(r.avg)} ₺` },
    { key: "median", header: t("marketing.ltv.col.median"), mono: true, render: (r) => `${formatInt(r.median)} ₺` },
    { key: "x", header: t("marketing.ltv.col.xD1"), mono: true, render: (r) => `×${r.x_d1}` },
  ];

  const tierCols: Column<LtvTier>[] = [
    { key: "tier", header: t("marketing.ltv.col.tier"), align: "left", render: (r) => <TierBadge tier={r.tier} /> },
    { key: "cohort", header: t("marketing.ltv.col.cohortTraining"), mono: true, render: (r) => formatInt(r.cohort_n) },
    { key: "d30", header: t("marketing.ltv.col.expD30"), mono: true, render: (r) => `${formatInt(r.exp_d30)} ₺` },
    { key: "d90", header: t("marketing.ltv.col.expD90"), mono: true, render: (r) => `${formatInt(r.exp_d90)} ₺` },
    { key: "d120", header: t("marketing.ltv.col.expD120"), mono: true, render: (r) => `${formatInt(r.exp_d120)} ₺` },
  ];

  const whaleCols: Column<YoungWhale>[] = [
    {
      key: "id",
      header: t("marketing.ltv.col.id"),
      id: true,
      render: (r) => (
        <span>
          {r.player_id}
          {r.tier_provisional ? (
            <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-[#fef9c3] text-[#854d0e] align-middle">
              {t("marketing.ltv.provisionalBadge")}
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "age", header: t("marketing.ltv.col.age"), mono: true, render: (r) => `${formatInt(r.days_since_ftd)}${daySuffix}` },
    { key: "tier", header: t("marketing.ltv.col.tier"), align: "right", render: (r) => <TierBadge tier={r.early_tier} /> },
    { key: "d7", header: t("marketing.ltv.col.dep7d"), mono: true, render: (r) => `${formatInt(r.dep_d7)} ₺` },
    { key: "dtot", header: t("marketing.ltv.col.depTotal"), mono: true, render: (r) => `${formatInt(r.dep_to_date)} ₺` },
    {
      key: "p90",
      header: t("marketing.ltv.col.predD90"),
      mono: true,
      render: (r) => <span className="text-pos">{formatInt(r.pred_ltv_d90)} ₺</span>,
    },
    { key: "head", header: t("marketing.ltv.col.headroom"), mono: true, render: (r) => `${formatInt(r.ltv_headroom)} ₺` },
  ];

  return (
    <>
      <PageHeader
        title={
          <>
            {t("marketing.ltv.title")} <em className="not-italic text-steel font-normal text-[15px]">{t("marketing.ltv.titleVersion")}</em>
          </>
        }
        lead={t("marketing.ltv.lead")}
      />

      <ModuleHeader module="vip" />

      {state === "error" ? (
        <Card className="mt-5">
          <div className="text-neg text-[13.5px]">{error}</div>
          <button onClick={reload} className="mt-2 text-primary text-[13px] underline">
            {t("common.retry")}
          </button>
        </Card>
      ) : (
        <>
          <div className="mt-5">
            <SCardGrid>
              <SCard
                loading={loading}
                variant="orange"
                icon="💎"
                label={t("marketing.ltv.card.headroom.label")}
                value={formatMoneyMn(k?.tot_head)}
                sub={t("marketing.ltv.card.headroom.sub")}
                spark={data ? <Sparkline values={data.curve.map((c) => c.avg)} /> : undefined}
              />
              <SCard
                loading={loading}
                variant="cream"
                icon="🐋"
                label={t("marketing.ltv.card.whales.label")}
                value={formatInt(k?.whales)}
                sub={t("marketing.ltv.card.whales.sub", { value: formatMoneyMn(k?.whales_head) })}
              />
              <SCard
                loading={loading}
                icon="🎯"
                label={t("marketing.ltv.card.young.label")}
                value={formatInt(k?.young)}
                sub={t("marketing.ltv.card.young.sub")}
              />
              <SCard
                loading={loading}
                icon="📈"
                label={t("marketing.ltv.card.growth.label")}
                value={k?.growth_d120_d1 != null ? `×${k.growth_d120_d1}` : "—"}
                sub={t("marketing.ltv.card.growth.sub")}
              />
            </SCardGrid>
          </div>

          <div className="mt-6">
            <Eyebrow>{t("marketing.ltv.curveEyebrow")}</Eyebrow>
            <Card>{loading ? <div className="h-[300px] animate-pulse rounded-md bg-hair2/50" /> : data ? <CurveChart curve={data.curve} /> : null}</Card>
            <Panel className="mt-3">
              <DataTable
                columns={curveCols}
                rows={data?.curve ?? []}
                getRowKey={(r) => r.day}
                state={loading ? "loading" : "data"}
              />
            </Panel>
            <div className="text-[13px] text-steel leading-relaxed mt-1.5">
              📖 <b>{t("marketing.ltv.footnote.bold1")}</b> {t("marketing.ltv.footnote.body")}
              <b> {t("marketing.ltv.footnote.bold2")}</b> {t("marketing.ltv.footnote.tail")}
            </div>
          </div>

          <div className="mt-6">
            <Eyebrow>{t("marketing.ltv.tierEyebrow")}</Eyebrow>
            <Panel>
              <DataTable
                columns={tierCols}
                rows={data?.tiers ?? []}
                getRowKey={(r) => r.tier}
                state={loading ? "loading" : "data"}
              />
            </Panel>
          </div>

          <div className="mt-6">
            <Eyebrow>{t("marketing.ltv.whalesEyebrow")}</Eyebrow>
            <div className="text-[13px] text-steel mb-2">
              {t("marketing.ltv.whalesDesc")}
            </div>
            <Panel>
              <DataTable
                columns={whaleCols}
                rows={data?.young_whales ?? []}
                getRowKey={(r) => r.player_id}
                getRowHref={(r) => `/players/${r.player_id}`}
                state={loading ? "loading" : data && data.young_whales.length === 0 ? "empty" : "data"}
                emptyTitle={t("marketing.ltv.empty.title")}
                emptyDescription={t("marketing.ltv.empty.desc")}
              />
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
