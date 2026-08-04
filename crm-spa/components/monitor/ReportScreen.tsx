"use client";

import {
  PageHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Panel,
  Pill,
  PillRow,
  DataTable,
  LifecycleBadge,
  ActionBadge,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useResource, pctRatio, tryAmount, OfferCell, Note } from "./kit";
import type {
  ReportData,
  ReportTaskRow,
  ReportTopPriority,
  ReportBonusRow,
  ReportOfferLogRow,
} from "./types";

/**
 * /report — «Отчёт отдела» (paritet с report() борда). Что отдел должен делать
 * (движок: распределение задач + топ-приоритеты) и что уже сделал (офферы: статусы
 * + журнал). Данные из /api/v1/report. Роли: DESK_ROLES.
 */
export function ReportScreen() {
  const t = useT();
  const { state, data, error, reload } = useResource<ReportData>("/api/v1/report");
  const loading = state === "loading";
  const d = data;

  const taskCols: Column<ReportTaskRow>[] = [
    { key: "action", header: t("monitor.report.col.task"), align: "left", render: (r) => <ActionBadge action={r.action} /> },
    { key: "players", header: t("monitor.report.col.players"), mono: true, render: (r) => formatInt(r.players) },
    { key: "value", header: t("monitor.report.col.value"), mono: true, render: (r) => tryAmount(r.value) },
    { key: "prio", header: t("monitor.report.col.avgPriority"), mono: true, render: (r) => formatInt(r.avg_priority) },
  ];

  const topCols: Column<ReportTopPriority>[] = [
    { key: "player", header: t("monitor.report.col.player"), id: true, render: (r) => r.player_id },
    { key: "stage", header: t("monitor.report.col.stage"), align: "left", render: (r) => <LifecycleBadge stage={r.lifecycle} /> },
    { key: "action", header: t("monitor.report.col.action"), align: "left", render: (r) => <ActionBadge action={r.action} /> },
    { key: "value", header: t("monitor.report.col.value"), mono: true, render: (r) => tryAmount(r.value_try) },
    { key: "risk", header: t("monitor.report.col.risk"), mono: true, render: (r) => pctRatio(r.p_churn) },
    { key: "offer", header: t("monitor.report.col.offer"), align: "left", render: (r) => <OfferCell offer={r.offer} /> },
  ];

  const bonusCols: Column<ReportBonusRow>[] = [
    { key: "bonus", header: t("monitor.report.col.bonus"), align: "left", render: (r) => r.bonus },
    { key: "players", header: t("monitor.report.col.players"), mono: true, render: (r) => formatInt(r.players) },
    { key: "value", header: t("monitor.report.col.value"), mono: true, render: (r) => tryAmount(r.value) },
  ];

  const logCols: Column<ReportOfferLogRow>[] = [
    { key: "player", header: t("monitor.report.col.player"), id: true, render: (r) => r.player_id },
    { key: "status", header: t("monitor.report.col.status"), align: "left", render: (r) => r.status || "—" },
    { key: "offer", header: t("monitor.report.col.offer"), align: "left", render: (r) => r.offer_text || "—" },
    { key: "operator", header: t("monitor.report.col.operator"), align: "left", render: (r) => r.operator || "—" },
    { key: "ts", header: t("monitor.report.col.when"), mono: true, render: (r) => r.ts || "—" },
  ];

  return (
    <>
      <PageHeader
        title={t("monitor.report.title")}
        accent={t("monitor.report.accent")}
        lead={t("monitor.report.lead")}
        right={
          <PillRow>
            <Pill live>{t("monitor.pill.liveClickhouse")}</Pill>
          </PillRow>
        }
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <SCardGrid className="mt-6">
            <SCard loading={loading} variant="alert" icon="📋" label={t("monitor.report.kpi.inWork.label")} value={formatInt(d?.kpi.in_work)} sub={t("monitor.report.kpi.inWork.sub")} />
            <SCard loading={loading} icon="💰" label={t("monitor.report.kpi.valueAtRisk.label")} value={tryAmount(d?.kpi.value_at_risk)} sub={t("monitor.report.kpi.valueAtRisk.sub")} />
            <SCard loading={loading} variant="cream" icon="📈" label={t("monitor.report.kpi.headroom.label")} value={tryAmount(d?.kpi.headroom)} sub={t("monitor.report.kpi.headroom.sub")} />
            <SCard
              loading={loading}
              icon="🎁"
              label={t("monitor.report.kpi.offers.label")}
              value={formatInt(d?.kpi.offers_total)}
              sub={t("monitor.report.kpi.offers.sub", { sent: formatInt(d?.kpi.offers_sent), rejected: formatInt(d?.kpi.offers_rejected) })}
            />
          </SCardGrid>

          <Eyebrow>{t("monitor.report.eyebrow.tasks")}</Eyebrow>
          <Panel>
            <DataTable
              columns={taskCols}
              rows={d?.task_dist ?? []}
              getRowKey={(r) => r.action}
              state={loading ? "loading" : d && d.task_dist.length ? "data" : "empty"}
              emptyTitle={t("monitor.report.empty.tasks")}
            />
          </Panel>

          <Eyebrow>{t("monitor.report.eyebrow.top")}</Eyebrow>
          <Panel>
            <DataTable
              columns={topCols}
              rows={d?.top_priorities ?? []}
              getRowKey={(r) => r.player_id}
              getRowHref={(r) => `/players/${r.player_id}`}
              state={loading ? "loading" : d && d.top_priorities.length ? "data" : "empty"}
              emptyTitle={t("monitor.report.empty.top")}
            />
          </Panel>

          <Eyebrow>{t("monitor.report.eyebrow.bonuses")}</Eyebrow>
          <Panel>
            <DataTable
              columns={bonusCols}
              rows={d?.bonus_dist ?? []}
              getRowKey={(r, i) => `${r.bonus}-${i}`}
              state={loading ? "loading" : d && d.bonus_dist.length ? "data" : "empty"}
              emptyTitle={t("monitor.report.empty.bonuses")}
            />
          </Panel>

          <Eyebrow>{t("monitor.report.eyebrow.log")}</Eyebrow>
          <Panel>
            <DataTable
              columns={logCols}
              rows={d?.offer_log ?? []}
              getRowKey={(r, i) => `${r.player_id}-${i}`}
              getRowHref={(r) => `/players/${r.player_id}`}
              state={loading ? "loading" : d && d.offer_log.length ? "data" : "empty"}
              emptyTitle={t("monitor.report.empty.log.title")}
              emptyDescription={t("monitor.report.empty.log.desc")}
            />
          </Panel>

          <Note>{t("monitor.report.note")}</Note>
        </>
      )}
    </>
  );
}
