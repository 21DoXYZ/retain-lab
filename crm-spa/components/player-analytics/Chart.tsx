"use client";

import dynamic from "next/dynamic";
import type { ComponentType, CSSProperties } from "react";
import type { EChartsOption } from "echarts";
import { Skeleton } from "@/components/ui";

/**
 * EChart — client-only echarts-for-react wrapper for the rhythm charts/heatmap,
 * self-contained to the player-analytics module (same pattern as the marketing/
 * segmentation wrappers). ECharts touches `window` at import time, so it is
 * loaded with `ssr: false` inside this Client Component (Next 16 lazy-loading).
 *
 * Charts are decoration over the rhythm stats/table — numeric parity never
 * depends on the chart rendering.
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
  loading: () => <Skeleton className="h-full w-full" />,
}) as ComponentType<ReactEChartsProps>;

/** Board rhythm palette (player_board.py RHYTHM_JS) — do not introduce new colours. */
export const RC = {
  primary: "#465fff",
  steel: "#667085",
  hair: "#e5e7eb",
  ink: "#101828",
  heat: ["#ecf3ff", "#c9d4ff", "#7592ff", "#465fff", "#1e3a8a"],
};

export function EChart({
  option,
  height = 210,
  className,
}: {
  option: EChartsOption;
  height?: number | string;
  className?: string;
}) {
  return (
    <ReactECharts
      option={option}
      notMerge
      lazyUpdate
      style={{ height, width: "100%" }}
      className={className}
      opts={{ renderer: "svg" }}
    />
  );
}
