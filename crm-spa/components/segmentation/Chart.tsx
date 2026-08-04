"use client";

import dynamic from "next/dynamic";
import type { CSSProperties } from "react";
import { Skeleton } from "@/components/ui";

/**
 * ECharts wrapper for the segmentation screens.
 *
 * echarts-for-react (v3) is loaded via next/dynamic with `ssr: false` — ECharts
 * touches `window` at import time, so it must stay client-only (Next 16 would
 * otherwise evaluate it during SSR of this client component).
 *
 * Rendering matches the live board (player_board.py layout): SVG renderer
 * (`opts.renderer = 'svg'`) so charts look identical to the dashboard.
 */
const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full" />,
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type EChartsOption = Record<string, any>;

interface ChartProps {
  option: EChartsOption;
  /** CSS height (board cohort charts are 180px). */
  height?: number | string;
  className?: string;
  style?: CSSProperties;
}

export function Chart({ option, height = 180, className, style }: ChartProps) {
  return (
    <ReactECharts
      option={option}
      notMerge
      lazyUpdate
      style={{ height, width: "100%", ...style }}
      className={className}
      opts={{ renderer: "svg" }}
    />
  );
}
