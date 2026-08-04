"use client";

import { useEffect, useState } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { Skeleton } from "@/components/ui";

/**
 * CallChart — SSR-safe echarts wrapper for the operator score-by-week chart
 * (§10.5), self-contained to the call-board module (same pattern as
 * components/money/Chart.tsx). SVG renderer, mount guard keeps echarts.init off
 * the server. The chart only ever decorates numeric data that is also shown in
 * tables — parity never depends on it rendering.
 */
interface CallChartProps {
  option: EChartsOption | Record<string, unknown>;
  height?: number | string;
  className?: string;
}

export function CallChart({ option, height = 260, className }: CallChartProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const style = { height, width: "100%" };
  if (!mounted) return <Skeleton className={className} />;

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option as EChartsOption}
      style={style}
      className={className}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}

/** Board chart palette — do not introduce new colours (see money/segmentation). */
export const CHART = {
  primary: "#2563eb",
  steel: "#64748b",
  hair: "#e5e7eb",
  ink: "#1e293b",
  amber: "#d97706",
} as const;
