"use client";

import { useEffect, useState } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";

/**
 * Chart — thin, SSR-safe echarts-for-react wrapper. We pass our own echarts v6
 * instance to ReactEChartsCore (the recommended pattern for controlling the
 * version) and render with the SVG renderer, exactly like the live board
 * (player_board.py forces renderer:'svg'). The mount guard keeps echarts.init
 * off the server, so the container renders empty during SSR and hydrates on the
 * client. autoResize is handled by echarts-for-react.
 */
interface ChartProps {
  // Экраны передают структурно-выведенные литералы опций (echarts узко типизирует
  // 'line'/'bar' и пр.). Принимаем широкий вход и кастуем к EChartsOption на входе
  // в ReactECharts — без any, каст локализован в обёртке.
  option: EChartsOption | Record<string, unknown>;
  height?: number | string;
  className?: string;
}

export function Chart({ option, height = 300, className }: ChartProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const style = { height, width: "100%" };
  if (!mounted) return <div style={style} className={className} />;

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
