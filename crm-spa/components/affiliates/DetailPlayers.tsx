"use client";

import { DataTable, Button, LifecycleBadge, type Column } from "@/components/ui";
import { formatInt, formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { DetailPlayer, DetailPlayersBlock, PlayerSortKey } from "./types";

/**
 * Detail player table (board affiliate() players table). Real cash per player
 * (auto deposit/withdrawal, completed). Sort + server pagination are driven by
 * the parent (path change → refetch). Row click → the player card /players/<id>.
 */

interface DetailPlayersProps {
  block: DetailPlayersBlock;
  loading: boolean;
  onSort: (key: PlayerSortKey) => void;
  onPage: (page: number) => void;
}

const NEG = (v: number) =>
  v < 0 ? <span className="text-neg">{formatMoney(v)}</span> : <span className="text-pos">{formatMoney(v)}</span>;

export function DetailPlayers({ block, loading, onSort, onPage }: DetailPlayersProps) {
  const t = useT();
  const { rows, total, page, page_size, sort, dir } = block;

  function SortHead({ label, sortKey, title }: { label: string; sortKey: PlayerSortKey; title?: string }) {
    const on = sort === sortKey;
    const arrow = on ? (dir === "desc" ? " ▾" : " ▴") : "";
    return (
      <button
        type="button"
        title={title}
        onClick={() => onSort(sortKey)}
        className={`uppercase tracking-[0.5px] transition-colors hover:text-primary ${on ? "text-primary" : ""}`}
      >
        {label}
        {arrow}
      </button>
    );
  }

  const columns: Column<DetailPlayer>[] = [
    { key: "id", header: <SortHead label="ID" sortKey="casino_player_id" />, align: "left", id: true, render: (p) => p.casino_player_id },
    { key: "stage", header: t("monitor.detailPlayers.col.stage"), align: "left", render: (p) => <LifecycleBadge stage={p.lifecycle} /> },
    { key: "country", header: t("monitor.detailPlayers.col.country"), align: "left", render: (p) => p.country ?? "—" },
    { key: "reg", header: <SortHead label={t("monitor.detailPlayers.col.reg")} sortKey="reg_date" />, mono: true, render: (p) => p.reg_date ?? "—" },
    { key: "ftd", header: <SortHead label={t("monitor.affiliates.col.ftdSum")} sortKey="ftd_amount" />, mono: true, render: (p) => formatInt(p.ftd_amount) },
    { key: "dep_cnt", header: <SortHead label={t("monitor.detailPlayers.col.depCnt")} sortKey="dep_cnt" />, mono: true, render: (p) => formatInt(p.dep_cnt) },
    { key: "dep", header: <SortHead label={t("monitor.affiliates.col.dep")} sortKey="dep" />, mono: true, render: (p) => formatMoney(p.dep) },
    { key: "wd_cnt", header: <SortHead label={t("monitor.detailPlayers.col.wdCnt")} sortKey="wd_cnt" />, mono: true, render: (p) => formatInt(p.wd_cnt) },
    { key: "wd", header: <SortHead label={t("monitor.affiliates.col.wd")} sortKey="wd" title={t("monitor.detailPlayers.col.wdTitle")} />, mono: true, render: (p) => formatMoney(p.wd) },
    { key: "net_cash", header: <SortHead label={t("monitor.detailPlayers.col.netCash")} sortKey="net_cash" title={t("monitor.detailPlayers.col.netCashTitle")} />, mono: true, render: (p) => NEG(p.net_cash) },
    { key: "turnover", header: <SortHead label={t("monitor.detailPlayers.col.turnover")} sortKey="turnover" />, mono: true, render: (p) => formatInt(p.turnover) },
    { key: "net", header: <SortHead label={t("monitor.detailPlayers.col.netPlayer")} sortKey="net" />, mono: true, render: (p) => (p.net < 0 ? <span className="text-neg">{formatInt(p.net)}</span> : <span className="text-pos">{formatInt(p.net)}</span>) },
    { key: "provider", header: t("monitor.detailPlayers.col.provider"), align: "left", render: (p) => p.provider ?? "—" },
    { key: "recency", header: <SortHead label="Recency" sortKey="recency_days" />, mono: true, render: (p) => (p.recency_days == null ? "—" : t("monitor.detailPlayers.recencyDays", { n: formatInt(p.recency_days) })) },
  ];

  const from = total === 0 ? 0 : page * page_size + 1;
  const to = Math.min((page + 1) * page_size, total);
  const hasPrev = page > 0;
  const hasNext = (page + 1) * page_size < total;

  return (
    <div className="overflow-hidden rounded-card border border-hair bg-canvas">
      <DataTable
        columns={columns}
        rows={rows}
        state={loading ? "loading" : rows.length === 0 ? "empty" : "data"}
        getRowKey={(p) => p.casino_player_id}
        getRowHref={(p) => `/players/${p.casino_player_id}`}
        emptyTitle={t("monitor.detailPlayers.empty.title")}
        emptyDescription={t("monitor.detailPlayers.empty.desc")}
      />
      <div className="flex items-center justify-between gap-3 border-t border-hair px-4 py-3 text-[12.5px] text-steel">
        <span>
          {t("monitor.detailPlayers.pageInfo", { from: formatInt(from), to: formatInt(to), total: formatInt(total) })}
        </span>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" disabled={!hasPrev || loading} onClick={() => onPage(page - 1)}>
            {t("monitor.detailPlayers.prevPage")}
          </Button>
          <Button variant="ghost" size="sm" disabled={!hasNext || loading} onClick={() => onPage(page + 1)}>
            {t("monitor.detailPlayers.nextPage")}
          </Button>
        </div>
      </div>
    </div>
  );
}
