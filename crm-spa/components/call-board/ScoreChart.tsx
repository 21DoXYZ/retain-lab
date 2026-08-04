"use client";

import { formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { CallChart, CHART } from "./Chart";
import type { WeeklyPoint, ScriptChange } from "./types";

/**
 * Балл по неделям (§10.5) с ВЕРТИКАЛЬНОЙ отметкой смены версии скрипта (markLine).
 * Отметка обязательна: без неё падение балла читается как «оператор испортился»,
 * хотя изменилась линейка. Только декорация над таблицей критериев — числа те же.
 */
export function ScoreChart({
  weekly,
  scriptChanges,
}: {
  weekly: WeeklyPoint[];
  scriptChanges: ScriptChange[];
}) {
  const t = useT();
  const labels = weekly.map((w) => formatDate(w.week));
  const scores = weekly.map((w) => w.avg_score);

  // Каждую смену версии привязываем к недельной корзине, в которую попадает дата.
  const marks = scriptChanges
    .map((c) => {
      const at = new Date(c.activated_at).getTime();
      let idx = -1;
      for (let i = 0; i < weekly.length; i++) {
        if (new Date(weekly[i].week).getTime() <= at) idx = i;
      }
      return idx >= 0 ? { xAxis: labels[idx], name: t("callsboard.report.scriptChange", { version: c.version }) } : null;
    })
    .filter((m): m is { xAxis: string; name: string } => m !== null);

  const option = {
    grid: { left: 8, right: 16, top: 22, bottom: 6, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#fff",
      borderColor: CHART.hair,
      textStyle: { color: CHART.ink },
    },
    xAxis: {
      type: "category",
      data: labels,
      axisLine: { lineStyle: { color: CHART.hair } },
      axisTick: { show: false },
      axisLabel: { color: CHART.steel },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: CHART.hair } },
      axisLabel: { color: CHART.steel },
    },
    series: [
      {
        type: "line",
        data: scores,
        connectNulls: false,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { color: CHART.primary, width: 2 },
        itemStyle: { color: CHART.primary },
        markLine: {
          symbol: "none",
          silent: true,
          lineStyle: { color: CHART.amber, type: "dashed", width: 1.5 },
          label: { color: CHART.amber, fontSize: 11, formatter: (p: { name: string }) => p.name },
          data: marks,
        },
      },
    ],
  } as const;

  return <CallChart option={option} height={260} />;
}
