"use client";

import { useState } from "react";
import {
  PageHeader,
  SCard,
  SCardGrid,
  Panel,
  Chip,
  ChipBar,
  Badge,
  DataTable,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useResource, pctRatio, tryAmount } from "./kit";
import { AssignButton } from "./AssignButton";

/**
 * /vip-risk — очередь «риск × перспективность» (инхаус vip-intelligence).
 * Данные из /api/v1/vip-risk: активные VIP по убыванию риска депозитного оттока
 * (vip_churn, 30д), разложенные на два бакета по матрице use case:
 *   менеджеру  — высокий риск × перспективный (или Platinum+: расти некуда,
 *                ценность и так высокая) → персональный звонок;
 *   автокампании — высокий риск × «не вырастет» (non_promising) → бонус без
 *                менеджерского времени.
 * Назначение оператору — тот же AssignButton, что на Пульте. Роли: DESK_ROLES.
 */

interface VipRiskRow {
  player_id: number;
  risk: number;
  growth: number | null;
  promising: boolean | null;
  vip_level: number;
  tier: string;
  cum_try: number;
  dep_recency: number | null;
  recency_days: number | null;
  dep_count: number;
  reco: "manager" | "auto";
}

interface VipRiskData {
  manager: VipRiskRow[];
  auto: VipRiskRow[];
  total_scored: number;
  manager_count: number;
  auto_count: number;
}

const TIER_COLORS: Record<string, { bg: string; fg: string }> = {
  Silver: { bg: "#f1f5f9", fg: "#475569" },
  Gold: { bg: "#fef9c3", fg: "#854d0e" },
  Platinum: { bg: "#e0e7ff", fg: "#3730a3" },
  Diamond: { bg: "#cffafe", fg: "#155e75" },
  Royal: { bg: "#fce7f3", fg: "#9d174d" },
};

export function VipRiskScreen() {
  const t = useT();
  const [tab, setTab] = useState<"manager" | "auto">("manager");
  const { state, data, error, reload } = useResource<VipRiskData>("/api/v1/vip-risk");
  const loading = state === "loading";
  const d = data;

  if (state === "error") {
    return <ErrorState description={error ?? undefined} onRetry={reload} />;
  }

  const cols: Column<VipRiskRow>[] = [
    { key: "player", header: t("monitor.vipRisk.col.player"), id: true, render: (r) => r.player_id },
    {
      key: "tier",
      header: t("monitor.vipRisk.col.tier"),
      align: "left",
      render: (r) => {
        const c = TIER_COLORS[r.tier] ?? { bg: "#f1f5f9", fg: "#475569" };
        return <Badge bg={c.bg} fg={c.fg}>{r.tier}</Badge>;
      },
    },
    { key: "cum", header: t("monitor.vipRisk.col.cum"), mono: true, render: (r) => tryAmount(r.cum_try) },
    {
      key: "risk",
      header: t("monitor.vipRisk.col.risk"),
      mono: true,
      render: (r) =>
        r.risk >= 0.8 ? (
          <span className="text-neg font-semibold">{pctRatio(r.risk)}</span>
        ) : (
          pctRatio(r.risk)
        ),
    },
    {
      key: "growth",
      header: t("monitor.vipRisk.col.growth"),
      align: "left",
      render: (r) =>
        r.promising === null ? (
          <span className="text-steel">{t("monitor.vipRisk.growthTop")}</span>
        ) : r.promising ? (
          <span className="text-pos">{t("monitor.vipRisk.growthYes", { pct: pctRatio(r.growth) })}</span>
        ) : (
          <span className="text-stone">{t("monitor.vipRisk.growthNo")}</span>
        ),
    },
    {
      key: "deprec",
      header: t("monitor.vipRisk.col.depRecency"),
      mono: true,
      render: (r) => (r.dep_recency != null ? t("monitor.vipRisk.daysAgo", { n: r.dep_recency }) : "—"),
    },
    { key: "deps", header: t("monitor.vipRisk.col.deps"), mono: true, render: (r) => formatInt(r.dep_count) },
    { key: "assign", header: "", align: "right", render: (r) => <AssignButton playerId={r.player_id} /> },
  ];

  const rows = tab === "manager" ? d?.manager ?? [] : d?.auto ?? [];

  return (
    <>
      <PageHeader title={t("monitor.vipRisk.title")} accent={t("monitor.vipRisk.subtitle")} />

      <SCardGrid className="mt-5">
        <SCard label={t("monitor.vipRisk.kpi.total")} value={d ? formatInt(d.total_scored) : "…"} loading={loading} />
        <SCard
          label={t("monitor.vipRisk.kpi.manager")}
          value={d ? formatInt(d.manager_count) : "…"}
          valueTone="neg"
          sub={t("monitor.vipRisk.kpi.managerSub")}
          loading={loading}
        />
        <SCard
          label={t("monitor.vipRisk.kpi.auto")}
          value={d ? formatInt(d.auto_count) : "…"}
          sub={t("monitor.vipRisk.kpi.autoSub")}
          loading={loading}
        />
      </SCardGrid>

      <ChipBar>
        <Chip active={tab === "manager"} onClick={() => setTab("manager")}>
          {t("monitor.vipRisk.tab.manager")}{d ? ` · ${Math.min(d.manager_count, d.manager.length)}` : ""}
        </Chip>
        <Chip active={tab === "auto"} onClick={() => setTab("auto")}>
          {t("monitor.vipRisk.tab.auto")}{d ? ` · ${Math.min(d.auto_count, d.auto.length)}` : ""}
        </Chip>
      </ChipBar>

      <Panel>
        <DataTable
          columns={cols}
          rows={rows}
          getRowKey={(r) => r.player_id}
          getRowHref={(r) => `/players/${r.player_id}`}
          state={loading ? "loading" : "data"}
          emptyTitle={t("monitor.vipRisk.empty")}
        />
      </Panel>
      <p className="mt-2 text-[12.5px] text-steel">ⓘ {t("monitor.vipRisk.note")}</p>
    </>
  );
}
