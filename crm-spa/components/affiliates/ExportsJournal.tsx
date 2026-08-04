"use client";

import {
  SCard,
  SCardGrid,
  DataTable,
  Button,
  Pill,
  PillRow,
  ErrorState,
  Badge,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useResource } from "./data";
import type { ExportRow, ExportsJournalData } from "./types";

/**
 * /exports (journal) — log of lists handed to the call-center and what happened
 * AFTER each hand-off (deposited / bonus / returned to play, and money in/out).
 * 1:1 with the board exports_view() list. Row → detail (parent state, no route).
 */

const MONEY_TRY = (v: number) => `${formatInt(v)} ₺`;

export function ExportsJournal({ onOpen }: { onOpen: (exp: string, seg: string) => void }) {
  const t = useT();
  const { state, data, error, reload } = useResource<ExportsJournalData>("/api/v1/exports");
  const totals = data?.totals;

  const columns: Column<ExportRow>[] = [
    { key: "disp", header: t("monitor.exportsJournal.col.exportDate"), align: "left", render: (r) => <span className="text-steel">{r.disp}</span> },
    {
      key: "segment",
      header: t("monitor.exportsJournal.col.segment"),
      align: "left",
      render: (r) => (
        <span className="inline-flex items-center gap-2">
          <b>{r.segment}</b>
          {r.is_demo ? <Badge bg="#fef3c7" fg="#92400e">{t("monitor.exportsJournal.demoBadge")}</Badge> : null}
        </span>
      ),
    },
    { key: "players", header: t("monitor.exportsJournal.col.players"), mono: true, render: (r) => formatInt(r.players) },
    {
      key: "deposited",
      header: t("monitor.exportsJournal.col.deposited"),
      mono: true,
      render: (r) => (
        <span className="text-pos">
          {formatInt(r.deposited)} <span className="text-steel">({r.deposited_pct}%)</span>
        </span>
      ),
    },
    { key: "dep_try", header: t("monitor.exportsJournal.col.depTry"), mono: true, render: (r) => <span className="text-pos">{MONEY_TRY(r.dep_try)}</span> },
    { key: "wd_try", header: t("monitor.exportsJournal.col.wdTry"), mono: true, render: (r) => <span className="text-neg">{MONEY_TRY(r.wd_try)}</span> },
    { key: "net", header: t("monitor.exportsJournal.col.net"), mono: true, render: (r) => <span className={r.net >= 0 ? "text-pos" : "text-neg"}><b>{MONEY_TRY(r.net)}</b></span> },
    { key: "bonus_given", header: t("monitor.exportsJournal.col.bonusGiven"), mono: true, render: (r) => formatInt(r.bonus_given) },
    { key: "returned", header: t("monitor.exportsJournal.col.returned"), mono: true, render: (r) => formatInt(r.returned) },
    { key: "dep_no_play", header: t("monitor.exportsJournal.col.depNoPlay"), mono: true, render: (r) => (r.dep_no_play ? <span className="text-neg">{formatInt(r.dep_no_play)}</span> : "0") },
    {
      key: "open",
      header: "",
      align: "right",
      render: (r) => (
        <Button variant="ghost" size="sm" onClick={() => onOpen(r.ets, r.segment)}>
          {t("monitor.exportsJournal.openDetails")}
        </Button>
      ),
    },
  ];

  if (state === "error") {
    return (
      <div className="mt-6">
        <ErrorState description={error ?? undefined} onRetry={reload} />
      </div>
    );
  }

  return (
    <>
      <div className="mt-[18px]">
        <SCardGrid className="lg:grid-cols-5">
          <SCard icon="📋" label={t("monitor.exportsJournal.kpi.exports.label")} value={totals ? formatInt(totals.exports) : "—"} sub={t("monitor.exportsJournal.kpi.exports.sub")} loading={state === "loading"} />
          <SCard variant="cream" icon="👥" label={t("monitor.exportsJournal.kpi.players.label")} value={totals ? formatInt(totals.players) : "—"} sub={t("monitor.exportsJournal.kpi.players.sub")} loading={state === "loading"} />
          <SCard icon="💰" label={t("monitor.exportsJournal.kpi.deposited.label")} value={totals ? formatInt(totals.deposited) : "—"} sub={totals ? t("monitor.exportsJournal.kpi.deposited.sub", { n: formatInt(totals.dep_try) }) : undefined} loading={state === "loading"} />
          <SCard icon="💸" label={t("monitor.exportsJournal.kpi.withdrawn.label")} value={totals ? MONEY_TRY(totals.wd_try) : "—"} sub={t("monitor.exportsJournal.kpi.withdrawn.sub")} loading={state === "loading"} />
          <SCard variant={totals && totals.net < 0 ? "alert" : "orange"} icon="💵" label={t("monitor.exportsJournal.kpi.net.label")} value={totals ? MONEY_TRY(totals.net) : "—"} sub={t("monitor.exportsJournal.kpi.net.sub")} loading={state === "loading"} />
        </SCardGrid>
      </div>

      <div className="mt-4 overflow-hidden rounded-card border border-hair bg-canvas">
        <DataTable
          columns={columns}
          rows={data?.rows ?? []}
          state={state === "loading" ? "loading" : (data?.rows.length ?? 0) === 0 ? "empty" : "data"}
          getRowKey={(r) => `${r.ets}|${r.segment}`}
          emptyTitle={t("monitor.exportsJournal.empty.title")}
          emptyDescription={t("monitor.exportsJournal.empty.desc")}
        />
      </div>
    </>
  );
}
