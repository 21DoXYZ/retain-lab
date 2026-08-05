"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { DataTable, PageHeader, type Column, type TableState } from "@/components/ui";

/**
 * /offers — каталог офферов тенанта (offers_catalog.json) + статистика выдач
 * из offers_issued. GET /api/v1/saas/offers.
 */

interface OfferRow {
  offer_id: string;
  title: string;
  executor: string;
  monetary: boolean;
  cost_estimate: number;
  max_per_user_30d: number;
  stats: { issued: number; dry_run: number; holdout: number; rejected: number };
}

interface OffersData {
  control_pct: number;
  offers: OfferRow[];
}

export function OffersView() {
  const t = useT();
  const [data, setData] = useState<OffersData | null>(null);
  const [state, setState] = useState<TableState>("loading");

  const load = useCallback(() => {
    setState("loading");
    flaskFetch<OffersData>("/api/v1/saas/offers")
      .then((d) => {
        setData(d);
        setState(d.offers.length ? "data" : "empty");
      })
      .catch(() => setState("error"));
  }, []);

  useEffect(load, [load]);

  const columns: Column<OfferRow>[] = [
    {
      key: "offer_id", header: t("saas.offers.col.offer"),
      render: (r) => (
        <div className="min-w-0">
          <div className="font-medium text-ink">{r.title}</div>
          <div className="text-[11px] text-steel font-mono">{r.offer_id}</div>
        </div>
      ),
    },
    { key: "executor", header: t("saas.offers.col.executor"), mono: true, render: (r) => r.executor },
    {
      key: "monetary", header: t("saas.offers.col.monetary"),
      render: (r) => (r.monetary ? t("saas.offers.yes") : t("saas.offers.no")),
      sortValue: (r) => (r.monetary ? 1 : 0),
    },
    {
      key: "cost_estimate", header: t("saas.offers.col.cost"), align: "right", mono: true,
      render: (r) => "$" + r.cost_estimate.toFixed(2),
    },
    { key: "max_per_user_30d", header: t("saas.offers.col.limit"), align: "right", mono: true,
      render: (r) => String(r.max_per_user_30d || "-") },
    {
      key: "issued", header: t("saas.offers.col.issued"), align: "right", mono: true,
      render: (r) => String(r.stats.issued + r.stats.dry_run),
      sortValue: (r) => r.stats.issued + r.stats.dry_run,
    },
    { key: "holdout", header: t("saas.offers.col.holdout"), align: "right", mono: true,
      render: (r) => String(r.stats.holdout), sortValue: (r) => r.stats.holdout },
    {
      key: "rejected", header: t("saas.offers.col.rejected"), align: "right", mono: true,
      render: (r) => (r.stats.rejected ? <span className="text-neg">{r.stats.rejected}</span> : "0"),
      sortValue: (r) => r.stats.rejected,
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("saas.offers.title")}
        lead={t("saas.offers.lead", { pct: data?.control_pct ?? 10 })}
      />
      <DataTable
        columns={columns}
        rows={data?.offers ?? []}
        getRowKey={(r) => r.offer_id}
        state={state}
        onRetry={load}
      />
    </div>
  );
}
