"use client";

import dynamic from "next/dynamic";
import type { ComponentType, CSSProperties } from "react";
import type { EChartsOption } from "echarts";

/**
 * EChart — thin client-only wrapper around echarts-for-react (same charting
 * library as the live Flask board). ECharts touches `window`, so it is loaded
 * with `ssr: false` inside this Client Component (Next 16 lazy-loading guide).
 *
 * Charts here are decoration over data that is ALSO shown as a table, so the
 * numeric parity (V5) never depends on the chart rendering.
 */
interface ReactEChartsProps {
  option: EChartsOption;
  style?: CSSProperties;
  className?: string;
  opts?: { renderer?: "canvas" | "svg" };
  notMerge?: boolean;
  lazyUpdate?: boolean;
}

const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => <div className="w-full animate-pulse rounded-md bg-hair2/60" style={{ height: 320 }} />,
}) as ComponentType<ReactEChartsProps>;

export interface EChartProps {
  option: EChartsOption;
  height?: number;
  className?: string;
}

/** Brand palette pulled from the design tokens (globals.css). */
export const CHART_COLORS = {
  primary: "#2563eb",
  sun5: "#3b82f6",
  pos: "#1f9d57",
  gold: "#854d0e",
  steel: "#64748b",
  hair: "#e5e7eb",
  ink: "#1e293b",
};

export function EChart({ option, height = 320, className }: EChartProps) {
  return (
    <ReactECharts
      option={option}
      style={{ height, width: "100%" }}
      className={className}
      opts={{ renderer: "svg" }}
      notMerge
      lazyUpdate
    />
  );
}
