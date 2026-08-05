"use client";

import { useState } from "react";
import {
  PageHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Panel,
  Card,
  Tabs,
  DataTable,
  ActionBadge,
  LifecycleBadge,
  Badge,
  type Column,
} from "@/components/ui";
import { formatInt, formatMoneyMn, formatPct } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useFlaskData } from "./useFlaskData";
import { VipScoresBlock } from "./VipScoresBlock";
import type { ActionsResponse, ActionRow, VipScoreSet } from "./types";

/** Compact cell that shows the three in-house VIP scores (0..1) as mini-chips. */
function VipScoreCell({ scores }: { scores: VipScoreSet }) {
  const t = useT();
  const allChips: { key: keyof VipScoreSet; icon: string; title: string }[] = [
    { key: "vip_churn", icon: "🚨", title: t("marketing.actions.vipChip.churn") },
    { key: "early_vip", icon: "💎", title: t("marketing.actions.vipChip.early") },
    { key: "non_promising", icon: "🧹", title: t("marketing.actions.vipChip.nonPromising") },
  ];
  const chips = allChips.filter((c) => scores[c.key] != null);
  if (chips.length === 0) return <span className="text-steel">—</span>;
  return (
    <span className="inline-flex gap-1 justify-end">
      {chips.map((c) => (
        <span
          key={c.key}
          title={`${c.title}: ${formatPct((scores[c.key] ?? 0) * 100)}`}
          className="text-[11px] font-mono text-steel"
        >
          {c.icon}
          {Math.round((scores[c.key] ?? 0) * 100)}
        </span>
      ))}
    </span>
  );
}

export function ActionsScreen() {
  const t = useT();
  const [filter, setFilter] = useState("SAVE");
  const { state, data, error, reload } = useFlaskData<ActionsResponse>(
    `/api/v1/actions?act=${encodeURIComponent(filter)}`,
  );
  const loading = state === "loading";
  const c = data?.cards;

  /** Static fallback so the filter bar renders before the first response lands. */
  const fallbackFilters: { key: string; label: string }[] = [
    { key: "SAVE", label: t("marketing.actions.filter.save") },
    { key: "WINBACK", label: t("marketing.actions.filter.winback") },
    { key: "NUDGE", label: t("marketing.actions.filter.nudge") },
    { key: "CONVERT", label: t("marketing.actions.filter.convert") },
    { key: "NURTURE", label: t("marketing.actions.filter.nurture") },
    { key: "all", label: t("marketing.actions.filter.all") },
  ];
  const tabs = (data?.filters ?? fallbackFilters).map((f) => ({ key: f.key, label: f.label }));

  const distCols: Column<ActionsResponse["distribution"][number]>[] = [
    { key: "action", header: t("marketing.actions.col.action"), align: "left", render: (r) => r.action },
    { key: "players", header: t("marketing.actions.col.players"), mono: true, render: (r) => formatInt(r.players) },
    {
      key: "value",
      header: t("marketing.actions.col.valueAtStake"),
      mono: true,
      render: (r) => `${formatInt(r.value_try)} ₺`,
    },
  ];

  const rowCols: Column<ActionRow>[] = [
    {
      key: "id",
      header: t("marketing.actions.col.id"),
      id: true,
      render: (r) => r.player_id,
    },
    { key: "lifecycle", header: t("marketing.actions.col.stage"), align: "left", render: (r) => <LifecycleBadge stage={r.lifecycle} /> },
    { key: "action", header: t("marketing.actions.col.action"), align: "left", render: (r) => <ActionBadge action={r.action} /> },
    { key: "value", header: t("marketing.actions.col.value"), mono: true, render: (r) => `${formatInt(r.value_try)} ₺` },
    {
      key: "churn",
      header: t("marketing.actions.col.churnRisk"),
      mono: true,
      render: (r) => (r.p_churn != null ? formatPct(r.p_churn * 100) : "—"),
    },
    {
      key: "p2",
      header: t("marketing.actions.col.p2ndDep"),
      mono: true,
      render: (r) => (r.p_2nd_deposit != null ? formatPct(r.p_2nd_deposit * 100) : "—"),
    },
    {
      key: "offer",
      header: t("marketing.actions.col.recBonus"),
      align: "left",
      render: (r) =>
        r.offer_name ? (
          <span title={[r.offer_terms, r.offer_reason].filter(Boolean).join(" — ")} className="cursor-help">
            {r.offer_name}
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "vip",
      header: t("marketing.actions.col.vipScores"),
      render: (r) => <VipScoreCell scores={r.vip_scores ?? {}} />,
    },
    { key: "when", header: t("marketing.actions.col.when"), align: "left", render: (r) => r.when_to || "—" },
  ];

  return (
    <>
      <PageHeader
        title={<>{t("marketing.actions.title")}</>}
        lead={t("marketing.actions.lead")}
      />

      {state === "error" ? (
        <Card className="mt-5">
          <div className="text-neg text-[13.5px]">{error}</div>
          <button onClick={reload} className="mt-2 text-primary text-[13px] underline">
            {t("common.retry")}
          </button>
        </Card>
      ) : (
        <>
          <div className="mt-5">
            <SCardGrid>
              <SCard
                loading={loading && !data}
                variant="orange"
                icon="🚨"
                label={t("marketing.actions.card.save.label")}
                value={formatInt(c?.save_n)}
                sub={t("marketing.actions.card.save.sub", { value: formatMoneyMn(c?.save_v) })}
              />
              <SCard
                loading={loading && !data}
                icon="↩"
                label={t("marketing.actions.card.winback.label")}
                value={formatInt(c?.wb_n)}
                sub={t("marketing.actions.card.winback.sub")}
              />
              <SCard
                loading={loading && !data}
                icon="👉"
                label={t("marketing.actions.card.nudge.label")}
                value={formatInt(c?.nudge_n)}
                sub={t("marketing.actions.card.nudge.sub")}
              />
              <SCard
                loading={loading && !data}
                icon="💳"
                label={t("marketing.actions.card.convert.label")}
                value={formatInt(c?.conv_n)}
                sub={t("marketing.actions.card.convert.sub")}
              />
            </SCardGrid>
          </div>

          <div className="mt-6">
            <Eyebrow>
              {t("marketing.actions.distEyebrow.main", { n: formatInt(data?.distribution_total) })}{" "}
              <span className="text-steel font-normal">{t("marketing.actions.distEyebrow.note")}</span>
            </Eyebrow>
            <Panel>
              <DataTable
                columns={distCols}
                rows={data?.distribution ?? []}
                getRowKey={(r) => r.action}
                state={loading && !data ? "loading" : "data"}
              />
            </Panel>
          </div>

          <div className="mt-6">
            <Eyebrow>
              {t("marketing.actions.priorityEyebrow.main")}{" "}
              <span className="text-steel font-normal">{t("marketing.actions.priorityEyebrow.note")}</span>
            </Eyebrow>
            <div className="mt-1 mb-2">
              <Tabs tabs={tabs} value={filter} onChange={setFilter} />
            </div>
            <Panel>
              <DataTable
                columns={rowCols}
                rows={data?.rows ?? []}
                getRowKey={(r) => r.player_id}
                getRowHref={(r) => `/players/${r.player_id}`}
                state={
                  loading ? "loading" : data && data.rows.length === 0 ? "empty" : "data"
                }
                emptyTitle={t("marketing.actions.empty.title")}
                emptyDescription={t("marketing.actions.empty.desc")}
              />
            </Panel>
          </div>

          <Card className="mt-3" padded>
            <div className="text-[13px] text-steel leading-relaxed">
              📖 <b>{t("marketing.actions.footnote.bold")}</b> {t("marketing.actions.footnote.mid")}{" "}
              <Badge bg="#f2f4f7" fg="#344054">🚨NN</Badge> {t("marketing.actions.footnote.post")}
            </div>
          </Card>

          <VipScoresBlock />
        </>
      )}
    </>
  );
}
