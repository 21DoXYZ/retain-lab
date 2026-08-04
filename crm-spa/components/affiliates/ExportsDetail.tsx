"use client";

import { useMemo } from "react";
import {
  SCard,
  SCardGrid,
  DataTable,
  Button,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt, formatDateShort } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useResource } from "./data";
import type { ExportPlayer, ExportsDetailData, ExportResult } from "./types";

/**
 * /exports (detail) — what happened to the players of ONE list after it was
 * handed to the call-center. 1:1 with the board exports_view() detail branch.
 */

const MONEY_TRY = (v: number) => `${formatInt(v)} ₺`;

export function ExportsDetail({
  exp,
  seg,
  onBack,
}: {
  exp: string;
  seg: string;
  onBack: () => void;
}) {
  const t = useT();

  const RESULT_LABEL: Record<ExportResult, string> = {
    deposit: t("monitor.exportsDetail.result.deposit"),
    returned: t("monitor.exportsDetail.result.returned"),
    bonus: t("monitor.exportsDetail.result.bonus"),
    none: "—",
  };

  const path = useMemo(() => {
    const params = new URLSearchParams({ exp, seg });
    return `/api/v1/exports/detail?${params.toString()}`;
  }, [exp, seg]);

  const { state, data, error, reload } = useResource<ExportsDetailData>(path);
  const s = data?.summary;

  const columns: Column<ExportPlayer>[] = [
    { key: "id", header: t("monitor.exportsDetail.col.player"), align: "left", id: true, render: (p) => p.player_id },
    { key: "dep", header: t("monitor.exportsDetail.col.depAfter"), mono: true, render: (p) => (p.dep_n > 0 ? <span className="text-pos">+{MONEY_TRY(p.dep_sum)}</span> : "—") },
    { key: "wd", header: t("monitor.exportsDetail.col.wdAfter"), mono: true, render: (p) => (p.wd_sum > 0 ? <span className="text-neg">−{MONEY_TRY(p.wd_sum)}</span> : "—") },
    { key: "net", header: t("monitor.exportsDetail.col.net"), mono: true, render: (p) => (p.dep_n > 0 || p.wd_sum > 0 ? <span className={p.net >= 0 ? "text-pos" : "text-neg"}><b>{MONEY_TRY(p.net)}</b></span> : "—") },
    { key: "dep_first", header: t("monitor.exportsDetail.col.depWhen"), align: "left", render: (p) => (p.dep_n > 0 ? formatDateShort(p.dep_first) : "—") },
    { key: "bonus_first", header: t("monitor.exportsDetail.col.bonusAfter"), align: "left", render: (p) => (p.bonus_n > 0 ? `🎁 ${formatDateShort(p.bonus_first)}` : "—") },
    { key: "bets", header: t("monitor.exportsDetail.col.returnedToPlay"), align: "left", render: (p) => (p.bets_after > 0 ? t("monitor.exportsDetail.returnedYes", { n: formatInt(p.bets_after) }) : t("monitor.exportsDetail.returnedNo")) },
    {
      key: "result",
      header: t("monitor.exportsDetail.col.result"),
      align: "left",
      render: (p) => (
        <span>
          {RESULT_LABEL[p.result]}
          {p.not_played ? <span className="text-neg">{t("monitor.exportsDetail.notPlayedSuffix")}</span> : null}
        </span>
      ),
    },
    { key: "rec_bonus", header: t("monitor.exportsDetail.col.recBonus"), align: "left", render: (p) => <span className="text-steel">{p.rec_bonus ?? "—"}</span> },
  ];

  return (
    <>
      <div className="mb-3">
        <button type="button" onClick={onBack} className="text-[13px] text-primary hover:underline">
          {t("monitor.exportsDetail.back")}
        </button>
      </div>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-extrabold text-[30px] tracking-[-0.6px] text-ink">
            {t("monitor.exportsDetail.heading")} <span className="text-primary">{seg}</span>{" "}
            {data ? <span className="text-[15px] font-medium text-steel">{t("monitor.exportsDetail.headingFrom", { date: data.disp })}</span> : null}
          </h1>
          <div className="text-steel text-[14.5px] mt-1.5">
            {t("monitor.exportsDetail.subtitle")}
          </div>
        </div>
      </div>

      {state === "error" ? (
        <div className="mt-6">
          <ErrorState description={error ?? undefined} onRetry={reload} />
        </div>
      ) : (
        <>
          <div className="mt-[18px]">
            <SCardGrid className="lg:grid-cols-3 xl:grid-cols-6">
              <SCard icon="📋" label={t("monitor.exportsDetail.kpi.total.label")} value={s ? formatInt(s.total) : "—"} sub={t("monitor.exportsDetail.kpi.total.sub")} loading={state === "loading"} />
              <SCard variant="cream" icon="💰" label={t("monitor.exportsDetail.kpi.deposited.label")} value={s ? formatInt(s.deposited) : "—"} sub={s ? t("monitor.exportsDetail.kpi.deposited.sub", { n: formatInt(s.dep_try) }) : undefined} loading={state === "loading"} />
              <SCard icon="💸" label={t("monitor.exportsDetail.kpi.withdrawn.label")} value={s ? MONEY_TRY(s.wd_try) : "—"} sub={t("monitor.exportsDetail.kpi.withdrawn.sub")} loading={state === "loading"} />
              <SCard variant={s && s.net < 0 ? "alert" : "orange"} icon="💵" label={t("monitor.exportsDetail.kpi.net.label")} value={s ? MONEY_TRY(s.net) : "—"} sub={t("monitor.exportsDetail.kpi.net.sub")} loading={state === "loading"} />
              <SCard icon="🎮" label={t("monitor.exportsDetail.kpi.returned.label")} value={s ? formatInt(s.returned) : "—"} sub={t("monitor.exportsDetail.kpi.returned.sub")} loading={state === "loading"} />
              <SCard variant="alert" icon="⚠️" label={t("monitor.exportsDetail.kpi.depNoPlay.label")} value={s ? formatInt(s.dep_no_play) : "—"} sub={t("monitor.exportsDetail.kpi.depNoPlay.sub")} loading={state === "loading"} />
            </SCardGrid>
          </div>

          <div className="mt-4 overflow-hidden rounded-card border border-hair bg-canvas">
            <DataTable
              columns={columns}
              rows={data?.rows ?? []}
              state={state === "loading" ? "loading" : (data?.rows.length ?? 0) === 0 ? "empty" : "data"}
              getRowKey={(p) => p.player_id}
              getRowHref={(p) => `/players/${p.player_id}`}
              emptyTitle={t("monitor.exportsDetail.empty.title")}
              emptyDescription={t("monitor.exportsDetail.empty.desc")}
            />
          </div>
        </>
      )}

      <div className="mt-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          {t("monitor.exportsDetail.back")}
        </Button>
      </div>
    </>
  );
}
