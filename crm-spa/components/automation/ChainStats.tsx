"use client";

import {
  DataTable,
  SCard,
  SCardGrid,
  EmptyState,
  ErrorState,
  Skeleton,
  Card,
  type Column,
  type TableState,
} from "@/components/ui";
import { useT } from "@/lib/i18n";
import { formatInt, formatPct } from "@/lib/format";
import { useFlaskData } from "@/components/marketing/useFlaskData";
import type { ChainStatsData, StatNode } from "./chainModel";

/**
 * ChainStats — per-node funnel + goal conversion for one chain (W4-T5, §4).
 *
 * The runner (W4-T4) fills retention.chain_events; until it has run, the endpoint
 * answers {available:false} and we show the explanatory empty state
 * («статистика появится после запуска исполнителя»). When data exists we render
 * entered / passed / dropped (+ drop reasons) per node and main-vs-control goal
 * conversion. `nodeLabels` maps node_id → a human step label when opened from the
 * editor; otherwise the raw id is shown.
 */

interface ChainStatsProps {
  chainId: string;
  nodeLabels?: Record<string, string>;
}

function conversion(g: { n: number; conv: number }): number | null {
  return g.n > 0 ? (g.conv / g.n) * 100 : null;
}

export function ChainStats({ chainId, nodeLabels }: ChainStatsProps) {
  const t = useT();
  const statsQ = useFlaskData<ChainStatsData>(`/api/v1/chains/${chainId}/stats`);

  if (statsQ.state === "loading") {
    return (
      <div className="space-y-3">
        <SCardGrid>
          {Array.from({ length: 2 }).map((_, i) => (
            <SCard key={i} loading label="" value="" />
          ))}
        </SCardGrid>
        <Card>
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-full mt-3" />
          <Skeleton className="h-5 w-2/3 mt-3" />
        </Card>
      </div>
    );
  }

  if (statsQ.state === "error") {
    return (
      <ErrorState
        title={t("automation.chains.stats.error.title")}
        description={statsQ.error ?? t("automation.chains.stats.error.desc")}
        onRetry={statsQ.reload}
      />
    );
  }

  const data = statsQ.data;
  if (!data || !data.available) {
    return (
      <EmptyState
        icon="📊"
        title={t("automation.chains.stats.pending.title")}
        description={t("automation.chains.stats.pending.desc")}
      />
    );
  }

  const label = (id: string) => nodeLabels?.[id] ?? id;

  const columns: Column<StatNode>[] = [
    {
      key: "node",
      header: t("automation.chains.stats.col.node"),
      align: "left",
      render: (n) => (
        <div className="flex flex-col">
          <span className="text-ink">{label(n.node_id)}</span>
          <span className="text-[11px] text-stone font-mono">{n.node_id}</span>
        </div>
      ),
    },
    {
      key: "entered",
      header: t("automation.chains.stats.col.entered"),
      mono: true,
      render: (n) => formatInt(n.entered),
    },
    {
      key: "passed",
      header: t("automation.chains.stats.col.passed"),
      mono: true,
      render: (n) => formatInt(n.passed),
    },
    {
      key: "dropped",
      header: t("automation.chains.stats.col.dropped"),
      mono: true,
      render: (n) => (n.dropped > 0 ? <span className="text-neg">{formatInt(n.dropped)}</span> : formatInt(n.dropped)),
    },
    {
      key: "reasons",
      header: t("automation.chains.stats.col.reasons"),
      align: "left",
      render: (n) => {
        const entries = Object.entries(n.drop_reasons ?? {});
        if (entries.length === 0) return <span className="text-stone">—</span>;
        return (
          <div className="flex flex-wrap gap-1.5">
            {entries.map(([reason, count]) => (
              <span
                key={reason}
                className="inline-flex items-center gap-1 rounded-full bg-cream text-ink text-[11px] px-2 py-[2px]"
              >
                <span>{reason}</span>
                <span className="font-mono text-steel">{formatInt(count)}</span>
              </span>
            ))}
          </div>
        );
      },
    },
  ];

  const tableState: TableState = data.nodes.length === 0 ? "empty" : "data";
  const goal = data.goal;
  const mainConv = goal ? conversion(goal.main) : null;
  const controlConv = goal ? conversion(goal.control) : null;
  const uplift = mainConv != null && controlConv != null ? mainConv - controlConv : null;

  return (
    <div className="space-y-5">
      {goal ? (
        <SCardGrid className="lg:grid-cols-3">
          <SCard
            label={t("automation.chains.stats.goal.main")}
            value={mainConv != null ? formatPct(mainConv) : "—"}
            sub={t("automation.chains.stats.goal.sub", {
              conv: formatInt(goal.main.conv),
              n: formatInt(goal.main.n),
            })}
            icon="🎯"
          />
          <SCard
            label={t("automation.chains.stats.goal.control")}
            value={controlConv != null ? formatPct(controlConv) : "—"}
            sub={t("automation.chains.stats.goal.sub", {
              conv: formatInt(goal.control.conv),
              n: formatInt(goal.control.n),
            })}
            icon="🧪"
          />
          <SCard
            label={t("automation.chains.stats.goal.uplift")}
            value={uplift != null ? formatPct(uplift, { sign: true }) : "—"}
            valueTone={uplift != null ? (uplift >= 0 ? "pos" : "neg") : "default"}
            sub={t("automation.chains.stats.goal.upliftSub")}
            variant="cream"
          />
        </SCardGrid>
      ) : null}

      <div className="overflow-hidden rounded-card border border-hair bg-canvas">
        <DataTable
          columns={columns}
          rows={data.nodes}
          getRowKey={(n) => n.node_id}
          state={tableState}
          emptyTitle={t("automation.chains.stats.pending.title")}
          emptyDescription={t("automation.chains.stats.pending.desc")}
        />
      </div>
    </div>
  );
}
