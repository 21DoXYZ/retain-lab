"use client";

import {
  PageHeader,
  Card,
  ChartBox,
  Panel,
  DataTable,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSegmentationData } from "./useSegmentationData";
import { Chart } from "./Chart";
import { funnelOption } from "./chartOptions";
import type { FunnelResponse, FunnelStage } from "./types";

/**
 * /funnel — deposit funnel (registration → played → deposit #1 (FTD) → … → #10).
 * Numbers come straight from /api/v1/funnel (deposit_ladder), 1:1 with the board.
 */
export function FunnelView() {
  const t = useT();
  const { state, data, error, reload } = useSegmentationData<FunnelResponse>(
    "/api/v1/funnel",
    (d) => d.stages.length === 0,
  );

  const columns: Column<FunnelStage>[] = [
    { key: "name", header: t("segmentation.funnel.col.stage"), render: (s) => s.name },
    { key: "n", header: t("segmentation.funnel.col.players"), mono: true, render: (s) => formatInt(s.n) },
    {
      key: "pct",
      header: t("segmentation.funnel.col.pctReg"),
      mono: true,
      render: (s) => `${s.pct_of_reg}%`,
    },
    {
      key: "step",
      header: t("segmentation.funnel.col.stepConv"),
      mono: true,
      render: (s) => (s.step_conv == null ? "" : `${s.step_conv}%`),
    },
    {
      key: "bar",
      header: t("segmentation.funnel.col.funnelBar"),
      align: "left",
      render: (s) => (
        <div className="min-w-[160px]">
          <div
            className="h-4 rounded"
            style={{ background: "#fde68a", width: `${s.bar_pct}%` }}
          />
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("segmentation.funnel.title")}
        accent={t("segmentation.funnel.accent")}
        lead={t("segmentation.funnel.lead")}
      />

      {state === "error" ? (
        <Card className="mt-6">
          <ErrorState description={error ?? undefined} onRetry={reload} />
        </Card>
      ) : (
        <div className="mt-6 space-y-4">
          <ChartBox title={t("segmentation.funnel.chart.title")} caption={t("segmentation.funnel.chart.caption")}>
            {state === "data" && data ? (
              <Chart option={funnelOption(data.stages)} height={280} />
            ) : (
              <div className="h-[280px] animate-pulse rounded-md bg-hair2/60" />
            )}
          </ChartBox>

          <Panel>
            <DataTable
              columns={columns}
              rows={data?.stages ?? []}
              getRowKey={(s) => s.name}
              state={state === "data" ? "data" : state === "empty" ? "empty" : "loading"}
              skeletonRows={12}
              emptyTitle={t("segmentation.funnel.emptyTitle")}
            />
          </Panel>
        </div>
      )}
    </>
  );
}
