import type { EChartsOption } from "./Chart";
import type { CohortItem, FunnelStage, RfmSegment, LtvDecile } from "./types";

/**
 * ECharts option builders — colours and geometry copied 1:1 from the live board
 * (player_board.py COHORTS_JS `copt()`), so the SPA charts read identically to
 * the dashboard. Palette below is the board's exact set.
 */
const OR = "#465fff";
const SU = "#7592ff";
const INK = "#101828";
const ST = "#667085";
const HA = "#e5e7eb";
const PAL = [OR, SU, "#a6b8ff", "#3641f5", "#c9d4ff", INK, "#d0d5dd"];

const TIP = {
  backgroundColor: "#fff",
  borderColor: HA,
  textStyle: { color: INK },
  confine: true,
};

/** Cohort mini-chart — dispatches by item.type exactly like the board copt(). */
export function cohortOption(item: CohortItem): EChartsOption | null {
  const d = item.data ?? [];
  const labels = d.map((x) => x.label);
  const values = d.map((x) => x.value);

  if (item.type === "bar") {
    return {
      grid: { left: 6, right: 40, top: 8, bottom: 6, containLabel: true },
      tooltip: { trigger: "item", ...TIP },
      xAxis: {
        type: "value",
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
      },
      yAxis: {
        type: "category",
        data: [...labels].reverse(),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: ST, fontSize: 11 },
      },
      series: [
        {
          type: "bar",
          data: [...values].reverse(),
          barWidth: "62%",
          itemStyle: { color: OR, borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: "right", color: ST, fontSize: 10 },
        },
      ],
    };
  }

  if (item.type === "time") {
    return {
      grid: { left: 6, right: 8, top: 10, bottom: 6, containLabel: true },
      tooltip: { trigger: "axis", ...TIP },
      xAxis: {
        type: "category",
        data: labels,
        axisLine: { lineStyle: { color: HA } },
        axisTick: { show: false },
        axisLabel: { color: ST, fontSize: 9, interval: Math.ceil(d.length / 8) },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: HA } },
        axisLabel: { color: ST, fontSize: 10 },
      },
      series: [
        {
          type: "bar",
          data: values,
          barWidth: "58%",
          itemStyle: { color: OR, borderRadius: [3, 3, 0, 0] },
        },
      ],
    };
  }

  if (item.type === "area") {
    return {
      grid: { left: 6, right: 8, top: 10, bottom: 6, containLabel: true },
      tooltip: { trigger: "axis", ...TIP },
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: HA } },
        axisTick: { show: false },
        axisLabel: { color: ST, fontSize: 9, interval: 3 },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
      },
      series: [
        {
          type: "line",
          data: values,
          smooth: true,
          symbol: "none",
          lineStyle: { color: OR, width: 2 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(70,95,255,.3)" },
                { offset: 1, color: "rgba(70,95,255,0)" },
              ],
            },
          },
        },
      ],
    };
  }

  if (item.type === "donut") {
    return {
      tooltip: { trigger: "item", ...TIP },
      series: [
        {
          type: "pie",
          radius: ["48%", "75%"],
          center: ["50%", "52%"],
          padAngle: 2,
          itemStyle: { borderColor: "#fff", borderWidth: 2, borderRadius: 4 },
          label: { color: ST, fontSize: 11, formatter: (p: { name: string }) => p.name },
          data: d.map((x, i) => ({
            name: x.label,
            value: x.value,
            itemStyle: { color: PAL[i % PAL.length] },
          })),
        },
      ],
    };
  }

  return null;
}

/** Deposit funnel — vertical echarts funnel series (same numbers as the table). */
export function funnelOption(stages: FunnelStage[]): EChartsOption {
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: { name: string; value: number }) =>
        `${p.name}: ${p.value.toLocaleString("en-US").replace(/,/g, " ")}`,
      ...TIP,
    },
    series: [
      {
        type: "funnel",
        left: "4%",
        right: "4%",
        top: 8,
        bottom: 8,
        minSize: "8%",
        sort: "descending",
        gap: 2,
        label: {
          show: true,
          position: "inside",
          color: "#fff",
          fontSize: 11,
          formatter: (p: { name: string }) => p.name,
        },
        itemStyle: { borderColor: "#fff", borderWidth: 1 },
        data: stages.map((s, i) => ({
          name: s.name,
          value: s.n,
          itemStyle: { color: PAL[i % PAL.length] },
        })),
      },
    ],
  };
}

/** RFM segment sizes — horizontal bar, board bar geometry. */
export function rfmBarOption(segments: RfmSegment[]): EChartsOption {
  const rows = [...segments].reverse();
  return {
    grid: { left: 6, right: 48, top: 8, bottom: 6, containLabel: true },
    tooltip: { trigger: "item", ...TIP },
    xAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
    },
    yAxis: {
      type: "category",
      data: rows.map((s) => s.seg),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: ST, fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        data: rows.map((s) => ({ value: s.n, itemStyle: { color: s.fg } })),
        barWidth: "62%",
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        label: {
          show: true,
          position: "right",
          color: ST,
          fontSize: 10,
          formatter: (p: { value: number }) =>
            p.value.toLocaleString("en-US").replace(/,/g, " "),
        },
      },
    ],
  };
}

/** LTV decile concentration — "% всей ценности" per decile (same numbers as table). */
export function ltvConcentrationOption(deciles: LtvDecile[]): EChartsOption {
  return {
    grid: { left: 6, right: 12, top: 12, bottom: 6, containLabel: true },
    tooltip: {
      trigger: "axis",
      formatter: (arr: { name: string; value: number }[]) =>
        `${arr[0].name}: ${arr[0].value}%`,
      ...TIP,
    },
    xAxis: {
      type: "category",
      data: deciles.map((r) => `D${r.decile}`),
      axisLine: { lineStyle: { color: HA } },
      axisTick: { show: false },
      axisLabel: { color: ST, fontSize: 10 },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: HA } },
      axisLabel: { color: ST, fontSize: 10, formatter: "{value}%" },
    },
    series: [
      {
        type: "bar",
        data: deciles.map((r) => ({
          value: r.pct_of_value,
          itemStyle: { color: r.is_whale ? OR : SU, borderRadius: [3, 3, 0, 0] },
        })),
        barWidth: "58%",
      },
    ],
  };
}
