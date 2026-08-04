"use client";

import { useMemo } from "react";
import {
  PageHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Panel,
  Pill,
  PillRow,
  DataTable,
  TierBadge,
  ActionBadge,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useResource, usePolling, pctRatio, tryAmount, Note } from "./kit";
import type { SignalsData, SignalRow, SignalsOnline } from "./types";

/**
 * /signals — «Сигналы модели» (paritet с signals() борда). Топ-200 по приоритету:
 * LTV / риск / P(2-й деп) / тир / действие / бонус — ровно то, что уходит казино.
 * Онлайн-оверлей (зелёная точка «в потоке сейчас») реализован ОПРОСОМ
 * /api/v1/signals/online каждые 30 сек — polling-замена SSE /signals/stream.
 * Роли: SIGNALS_ROLES.
 */

const ONLINE_POLL_MS = 30_000;

export function SignalsScreen() {
  const t = useT();
  const { state, data, error, reload } = useResource<SignalsData>("/api/v1/signals");
  // Overlay poll — its own failures never disrupt the main table.
  const online = usePolling<SignalsOnline>("/api/v1/signals/online", ONLINE_POLL_MS, t("monitor.fetchError"));
  const loading = state === "loading";
  const d = data;

  const onlineSet = useMemo(() => new Set(online.data?.online ?? []), [online.data]);

  const cols: Column<SignalRow>[] = [
    {
      key: "player",
      header: t("monitor.signals.col.player"),
      id: true,
      render: (r) => (
        <span className="inline-flex items-center gap-1.5">
          {onlineSet.has(r.player_id) ? (
            <span
              className="w-2 h-2 rounded-full bg-pos inline-block"
              title={t("monitor.signals.onlineNowTitle")}
              aria-label={t("monitor.signals.onlineNowAria")}
            />
          ) : null}
          {r.player_id}
        </span>
      ),
    },
    { key: "ltv", header: t("monitor.signals.col.ltv"), mono: true, render: (r) => tryAmount(r.pred_ltv_d90) },
    {
      key: "risk",
      header: t("monitor.signals.col.risk"),
      mono: true,
      render: (r) =>
        r.p_churn != null && r.p_churn >= 0.7 ? (
          <span className="text-neg font-semibold">{pctRatio(r.p_churn)}</span>
        ) : (
          pctRatio(r.p_churn)
        ),
    },
    { key: "p2", header: t("monitor.signals.col.p2"), mono: true, render: (r) => pctRatio(r.p_2nd_deposit) },
    { key: "tier", header: t("monitor.signals.col.tier"), align: "left", render: (r) => <TierBadge tier={r.early_tier} /> },
    { key: "action", header: t("monitor.signals.col.action"), align: "left", render: (r) => <ActionBadge action={r.action} /> },
    { key: "bonus", header: t("monitor.signals.col.bonus"), align: "left", render: (r) => (r.bonus != null && r.bonus !== "" ? String(r.bonus) : "—") },
    { key: "prio", header: t("monitor.signals.col.priority"), mono: true, render: (r) => formatInt(r.priority) },
  ];

  return (
    <>
      <PageHeader
        title={t("monitor.signals.title")}
        accent={t("monitor.signals.accent")}
        lead={t("monitor.signals.lead")}
        right={
          <PillRow>
            <Pill live>{t("monitor.signals.pill.overlay", { sec: ONLINE_POLL_MS / 1000 })}</Pill>
            <Pill>{t("monitor.signals.pill.inStream", { n: onlineSet.size })}</Pill>
          </PillRow>
        }
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <SCardGrid className="mt-6">
            <SCard loading={loading} icon="🧠" label={t("monitor.signals.kpi.total.label")} value={formatInt(d?.kpi.total)} sub={t("monitor.signals.kpi.total.sub")} />
            <SCard loading={loading} variant="cream" icon="🐋" label={t("monitor.signals.kpi.whales.label")} value={formatInt(d?.kpi.whales)} sub={t("monitor.signals.kpi.whales.sub")} />
            <SCard loading={loading} icon="📊" label={t("monitor.signals.kpi.avgPriority.label")} value={formatInt(d?.kpi.avg_priority)} sub={t("monitor.signals.kpi.avgPriority.sub")} />
            {/* top_action — сырое значение витрины («WINBACK · вернуть»); ActionBadge
                переводит подпись по КОДУ, как и везде, где показывается действие. */}
            <SCard
              loading={loading}
              icon="🎯"
              label={t("monitor.signals.kpi.topAction.label")}
              value={d?.kpi.top_action ? <ActionBadge action={d.kpi.top_action} /> : "—"}
              sub={t("monitor.signals.kpi.topAction.sub")}
            />
          </SCardGrid>

          <Eyebrow>{t("monitor.signals.eyebrow.top")}</Eyebrow>
          <Panel>
            <DataTable
              columns={cols}
              rows={d?.rows ?? []}
              getRowKey={(r) => r.player_id}
              getRowHref={(r) => `/players/${r.player_id}`}
              state={loading ? "loading" : d && d.rows.length ? "data" : "empty"}
              emptyTitle={t("monitor.signals.empty.title")}
              emptyDescription={t("monitor.signals.empty.desc")}
            />
          </Panel>

          <Note>{t("monitor.signals.note")}</Note>
        </>
      )}
    </>
  );
}
