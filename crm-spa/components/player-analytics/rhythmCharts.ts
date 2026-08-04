"use client";

import type { EChartsOption } from "echarts";
import { useT } from "@/lib/i18n";
import { RC } from "./Chart";

/**
 * Построители echarts-опций для ритма ставок — общие для двух экранов:
 *   • RhythmSection      — ритм игрока целиком (GET /players/<id>/rhythm)
 *   • GameDetailModal    — ритм внутри одной игры (GET /players/<id>/game/<gid>)
 *
 * Борд рисует оба одним и тем же RHYTHM_JS (player_board.rhythm_html), поэтому и
 * здесь это ОДИН код: палитра и рендер обязаны совпадать, иначе «когда ставил»
 * в игре выглядит иначе, чем «когда ставил» вообще. Данные — naive
 * Europe/Istanbul (паритет с бордом).
 */

export const H24 = Array.from({ length: 24 }, (_, i) => i);

const axis = {
  axisLine: { lineStyle: { color: RC.hair } },
  axisTick: { show: false },
  axisLabel: { color: RC.steel },
};
const tooltip = {
  backgroundColor: "#fff",
  borderColor: RC.hair,
  textStyle: { color: RC.ink },
  confine: true,
};

/** Подписи дней недели в порядке пн…вс (борд: dow[0] = понедельник). */
export function useDowLabels(): string[] {
  const t = useT();
  return [
    t("analytics.rhythm.dow.mon"),
    t("analytics.rhythm.dow.tue"),
    t("analytics.rhythm.dow.wed"),
    t("analytics.rhythm.dow.thu"),
    t("analytics.rhythm.dow.fri"),
    t("analytics.rhythm.dow.sat"),
    t("analytics.rhythm.dow.sun"),
  ];
}

export function dowOption(dow: number[], dowLabels: string[]): EChartsOption {
  return {
    grid: { left: 6, right: 12, top: 14, bottom: 6, containLabel: true },
    tooltip: { trigger: "axis", ...tooltip },
    xAxis: { type: "category", data: dowLabels, ...axis },
    yAxis: { type: "value", ...axis, splitLine: { lineStyle: { color: RC.hair } } },
    series: [
      { type: "bar", data: dow, barWidth: "56%", itemStyle: { color: RC.primary, borderRadius: [4, 4, 0, 0] } },
    ],
  };
}

export function hourOption(hour: number[]): EChartsOption {
  return {
    grid: { left: 6, right: 12, top: 14, bottom: 6, containLabel: true },
    tooltip: { trigger: "axis", ...tooltip },
    xAxis: {
      type: "category",
      data: H24,
      boundaryGap: false,
      axisLabel: { color: RC.steel, interval: 2, formatter: (v: string) => `${v}h` },
      axisLine: { lineStyle: { color: RC.hair } },
      axisTick: { show: false },
    },
    yAxis: { type: "value", ...axis, splitLine: { lineStyle: { color: RC.hair } } },
    series: [
      {
        type: "line",
        data: hour,
        smooth: true,
        symbol: "none",
        lineStyle: { color: RC.primary, width: 2.5 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(37,99,235,.25)" },
              { offset: 1, color: "rgba(37,99,235,0)" },
            ],
          },
        },
      },
    ],
  };
}

export function heatmapOption(hm: [number, number, number][], dowLabels: string[]): EChartsOption {
  const max = Math.max(1, ...hm.map((x) => x[2]));
  return {
    grid: { left: 6, right: 14, top: 10, bottom: 24, containLabel: true },
    tooltip: { position: "top", ...tooltip },
    xAxis: {
      type: "category",
      data: H24,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: RC.steel, interval: 2, formatter: (v: string) => `${v}h` },
    },
    yAxis: {
      type: "category",
      data: dowLabels,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: RC.steel },
    },
    visualMap: { min: 0, max, show: false, inRange: { color: RC.heat } },
    series: [{ type: "heatmap", data: hm, itemStyle: { borderColor: "#fff", borderWidth: 1.5 } }],
  };
}
