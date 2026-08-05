"use client";

import { useEffect } from "react";
import { PageHeader, Eyebrow, ChartBox, Pill, PillRow, ErrorState } from "@/components/ui";
import { Chart } from "@/components/money/Chart";
import { RetentionTriangle } from "@/components/money/RetentionTriangle";
import { useResource } from "@/components/money/kit";
import type { CashData } from "@/components/money/types";
import { useT } from "@/lib/i18n";

/**
 * /analytics — «Аналитика · графики» (paritet с analytics() борда). Секции:
 * удержание/активность, сегменты (жизненный цикл + RFM), денежный поток (#cash).
 * Данные из /api/v1/money/cash. Библиотека графиков — echarts-for-react (Chart).
 */

// board palette (ANALYTICS_JS)
const OR = "#465fff";
const YE = "#a6b8ff";
const SU = "#7592ff";
const INK = "#101828";
const ST = "#667085";
const HA = "#e5e7eb";
const tip = { backgroundColor: "#fff", borderColor: HA, textStyle: { color: INK } };
const ax = (e: Record<string, unknown> = {}) => ({
  axisLine: { lineStyle: { color: HA } },
  axisTick: { show: false },
  axisLabel: { color: ST },
  splitLine: { lineStyle: { color: HA } },
  ...e,
});

function ChartSkeleton({ height = 300 }: { height?: number }) {
  return <div className="animate-pulse rounded-md bg-hair2/60" style={{ height }} />;
}

export function AnalyticsScreen() {
  const t = useT();
  const { state, data, error, reload } = useResource<CashData>("/api/v1/money/cash");

  // keep the #cash hash target scrollable once data lands
  useEffect(() => {
    if (state === "data" && typeof window !== "undefined" && window.location.hash === "#cash") {
      document.getElementById("cash")?.scrollIntoView();
    }
  }, [state]);

  const loading = state !== "data";
  const d = data;

  const retOption = {
    grid: { left: 8, right: 14, top: 18, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", ...tip },
    xAxis: ax({ type: "category", data: (d?.ret ?? []).map((x) => x.w), boundaryGap: false }),
    yAxis: ax({ type: "value", axisLabel: { formatter: "{value}%", color: ST } }),
    series: [
      {
        type: "line",
        data: (d?.ret ?? []).map((x) => x.v),
        smooth: true,
        symbol: "circle",
        symbolSize: 8,
        lineStyle: { color: OR, width: 3 },
        itemStyle: { color: OR },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(70,95,255,.22)" },
              { offset: 1, color: "rgba(70,95,255,0)" },
            ],
          },
        },
        label: { show: true, color: OR, formatter: "{c}%" },
      },
    ],
  } as const;

  const hbar = (rows: { label: string; value: number }[], color: string) =>
    ({
      grid: { left: 8, right: 30, top: 10, bottom: 8, containLabel: true },
      tooltip: { trigger: "item", ...tip },
      xAxis: ax({ type: "value", axisLabel: { show: false }, splitLine: { show: false } }),
      yAxis: ax({
        type: "category",
        data: rows.map((x) => x.label).reverse(),
        axisLine: { show: false },
      }),
      series: [
        {
          type: "bar",
          data: rows.map((x) => x.value).reverse(),
          barWidth: "62%",
          itemStyle: { color, borderRadius: [0, 5, 5, 0] },
          label: { show: true, position: "right", color: ST },
        },
      ],
    }) as const;

  const daysOption = hbar(d?.days ?? [], OR);
  const lifeOption = hbar(d?.life ?? [], SU);
  const rfmOption = hbar((d?.rfm ?? []).map((x) => ({ label: x.seg, value: x.players })), INK);

  const depositsLabel = t("money.charts.legendDeposits");
  const withdrawalsLabel = t("money.charts.legendWithdrawals");
  const cfOption = {
    grid: { left: 8, right: 14, top: 30, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", ...tip },
    legend: { data: [depositsLabel, withdrawalsLabel], textStyle: { color: ST }, top: 0 },
    xAxis: ax({ type: "category", data: (d?.cf ?? []).map((x) => x.m) }),
    yAxis: ax({
      type: "value",
      axisLabel: { color: ST, formatter: (v: number) => `${v / 1e6}M` },
    }),
    series: [
      {
        name: depositsLabel,
        type: "bar",
        data: (d?.cf ?? []).map((x) => x.dep),
        itemStyle: { color: YE, borderRadius: [4, 4, 0, 0] },
      },
      {
        name: withdrawalsLabel,
        type: "bar",
        data: (d?.cf ?? []).map((x) => x.wd),
        itemStyle: { color: OR, borderRadius: [4, 4, 0, 0] },
      },
    ],
  } as const;

  return (
    <>
      <PageHeader
        title={t("money.charts.title")}
        accent={t("money.charts.accent")}
        lead={t("money.charts.lead")}
        right={
          <PillRow>
            <Pill live>{t("money.charts.pillLive")}</Pill>
          </PillRow>
        }
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <Eyebrow>{t("money.charts.sectionRetention")}</Eyebrow>
          <div className="grid gap-4 lg:grid-cols-2">
            <ChartBox title={t("money.charts.retentionTitle")} caption={t("money.charts.retentionCaption")}>
              {loading ? <ChartSkeleton /> : <Chart option={retOption} height={300} />}
            </ChartBox>
            <ChartBox title={t("money.charts.daysTitle")} caption={t("money.charts.daysCaption")}>
              {loading ? <ChartSkeleton /> : <Chart option={daysOption} height={300} />}
            </ChartBox>
          </div>

          {/* Retention-треугольник (Д2): когортная матрица вместо усреднённой линии */}
          <ChartBox title={t("money.triangle.title")} caption={t("money.triangle.caption")}>
            <RetentionTriangle />
          </ChartBox>

          <Eyebrow>{t("money.charts.sectionSegments")}</Eyebrow>
          <div className="grid gap-4 lg:grid-cols-2">
            <ChartBox title={t("money.charts.lifeTitle")} caption={t("money.charts.lifeCaption")}>
              {loading ? <ChartSkeleton /> : <Chart option={lifeOption} height={300} />}
            </ChartBox>
            <ChartBox title={t("money.charts.rfmTitle")} caption={t("money.charts.rfmCaption")}>
              {loading ? <ChartSkeleton /> : <Chart option={rfmOption} height={300} />}
            </ChartBox>
          </div>

          <div id="cash">
            <Eyebrow>{t("money.charts.sectionCashflow")}</Eyebrow>
          </div>
          <ChartBox title={t("money.charts.cashflowTitle")} caption={t("money.charts.cashflowCaption")}>
            {loading ? <ChartSkeleton height={320} /> : <Chart option={cfOption} height={320} />}
          </ChartBox>
        </>
      )}
    </>
  );
}
