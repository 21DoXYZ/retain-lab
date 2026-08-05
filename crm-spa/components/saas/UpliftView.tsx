"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Banner, DataTable, PageHeader, type Column, type TableState } from "@/components/ui";

/**
 * /uplift — недельный замер кампаний: target vs holdout → инкремент $
 * (GET /api/v1/saas/uplift; строки пишет stripe_sync/uplift_report.py по
 * расписанию saas-ops). n_control=0 → инкремент честно n/a.
 */

interface UpliftRow {
  campaign_id: string;
  period_start: string;
  period_end: string;
  n_target: number;
  n_control: number;
  conv_target: number;
  conv_control: number;
  avg_check: number;
  incremental_usd: number | null;
  goal_event: string;
}

interface UpliftData {
  tenant: string;
  total_incremental: number;
  campaigns: UpliftRow[];
}

function pct(x: number): string {
  return (x * 100).toFixed(1) + "%";
}

function usd(n: number): string {
  return "$" + n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function UpliftView() {
  const t = useT();
  const [data, setData] = useState<UpliftData | null>(null);
  const [state, setState] = useState<TableState>("loading");

  const load = useCallback(() => {
    setState("loading");
    flaskFetch<UpliftData>("/api/v1/saas/uplift")
      .then((d) => {
        setData(d);
        setState(d.campaigns.length ? "data" : "empty");
      })
      .catch(() => setState("error"));
  }, []);

  useEffect(load, [load]);

  const columns: Column<UpliftRow>[] = [
    { key: "campaign_id", header: t("saas.uplift.col.campaign"), render: (r) => r.campaign_id, id: true },
    {
      key: "conv_target", header: t("saas.uplift.col.target"), align: "right", mono: true,
      render: (r) => `${pct(r.conv_target)} · ${t("saas.uplift.groupN", { n: r.n_target })}`,
    },
    {
      key: "conv_control", header: t("saas.uplift.col.holdout"), align: "right", mono: true,
      render: (r) => `${pct(r.conv_control)} · ${t("saas.uplift.groupN", { n: r.n_control })}`,
    },
    {
      key: "avg_check", header: t("saas.uplift.col.check"), align: "right", mono: true,
      render: (r) => usd(r.avg_check),
    },
    {
      key: "incremental_usd", header: t("saas.uplift.col.incremental"), align: "right", mono: true,
      render: (r) =>
        r.incremental_usd === null ? (
          <span className="text-steel">{t("saas.uplift.na")}</span>
        ) : (
          <span className={r.incremental_usd >= 0 ? "text-pos" : "text-neg"}>
            {(r.incremental_usd >= 0 ? "+" : "") + usd(r.incremental_usd)}
          </span>
        ),
      sortValue: (r) => r.incremental_usd ?? -Infinity,
    },
    { key: "goal_event", header: t("saas.uplift.col.goal"), render: (r) => r.goal_event, mono: true },
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.uplift.title")} lead={t("saas.uplift.lead")} />

      {data && data.campaigns.length > 0 ? (
        <Banner>
          <span className="text-[15px] font-semibold">
            {t("saas.uplift.total", { amount: usd(data.total_incremental) })}
          </span>
        </Banner>
      ) : null}

      <DataTable
        columns={columns}
        rows={data?.campaigns ?? []}
        getRowKey={(r) => r.campaign_id}
        state={state}
        onRetry={load}
        emptyTitle={t("saas.uplift.empty.title")}
        emptyDescription={t("saas.uplift.empty.desc")}
      />
    </div>
  );
}
