"use client";

import { useMemo } from "react";
import {
  PageHeader,
  Panel,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  Button,
  ErrorState,
  Banner,
} from "@/components/ui";
import { formatInt, formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useCallResource, TrendCell, formatFraction } from "./kit";
import { CallChart } from "./Chart";
import type { SummaryData } from "./types";

/**
 * Сводка владельцу (§10.12) — единственный экран директора. Пока вердикт
 * заблокирован — только факты обзвона (из звонилки, не из модели). Балл — только
 * при разблок. вердикте. Тренд — к себе прошлому (отраслевых бенчмарков нет).
 * Цифры возврата денег здесь НЕТ (нет честной атрибуции). [Выгрузить] → CSV.
 */
interface Row {
  key: string;
  label: string;
  value: string;
  trend: number | null;
}

export function SummaryScreen() {
  const t = useT();
  const { state, data, error, reload } = useCallResource<SummaryData>("/api/v1/call-analysis/summary");
  const loading = state !== "data";

  const rows = useMemo(() => (data ? buildRows(data, t) : []), [data, t]);
  const periodLabel = data
    ? t("callsboard.summary.period", { from: formatDate(data.period.from), to: formatDate(data.period.to) })
    : "";

  function exportCsv() {
    if (!data) return;
    const header = [t("callsboard.summary.col.metric"), t("callsboard.summary.col.value"), t("callsboard.summary.col.trend")];
    const body = rows.map((r) => [r.label, r.value, r.trend == null ? "" : (r.trend > 0 ? `+${r.trend}` : String(r.trend))]);
    downloadCsv([header, ...body], `${t("callsboard.summary.csvFile")}.csv`);
  }

  return (
    <>
      <PageHeader
        title={t("callsboard.summary.title")}
        accent={periodLabel}
        lead={t("callsboard.summary.lead")}
        right={
          <Button variant="ghost" onClick={exportCsv} disabled={!data}>
            {t("callsboard.summary.export")}
          </Button>
        }
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <Panel className="mt-6">
            <Table>
              <THead>
                <TR>
                  <TH>{t("callsboard.summary.col.metric")}</TH>
                  <TH>{t("callsboard.summary.col.value")}</TH>
                  <TH>{t("callsboard.summary.col.trend")}</TH>
                </TR>
              </THead>
              <TBody>
                {loading ? (
                  <TR>
                    <TD colSpan={3} className="text-center text-steel">…</TD>
                  </TR>
                ) : (
                  rows.map((r) => (
                    <TR key={r.key}>
                      <TD className="text-left text-slate">{r.label}</TD>
                      <TD mono>{r.value}</TD>
                      <TD>{r.trend == null ? <span className="text-stone">—</span> : <TrendCell value={r.trend} />}</TD>
                    </TR>
                  ))
                )}
              </TBody>
            </Table>
          </Panel>

          {data ? (
            <>
              <p className="mt-4 text-[13.5px] text-slate">
                {t("callsboard.summary.analyzed", {
                  analyzed: formatInt(data.analyzed),
                  connected: formatInt(data.facts.connected),
                })}
              </p>
              {!data.verdict_unlocked ? (
                <Banner>ⓘ {t("callsboard.summary.lockedInfo")}</Banner>
              ) : null}

              {/* Динамика по неделям — данные звонилки, от модели не зависят.
                  Владельцу нужен ТРЕНД к себе прошлому (§10.12), не одна точка. */}
              {data.weekly.length > 1 ? (
                <Panel className="mt-6 p-4">
                  <div className="text-[13px] font-semibold text-ink mb-1">
                    {t("callsboard.summary.weekly.title")}
                  </div>
                  <p className="text-[12px] text-steel mb-2">{t("callsboard.summary.weekly.caption")}</p>
                  <CallChart option={weeklyOption(data.weekly, t)} height={220} />
                </Panel>
              ) : null}
            </>
          ) : null}
        </>
      )}
    </>
  );
}

type TFn = ReturnType<typeof useT>;

/** Бар-чарт по неделям: попытки / дозвоны / разговоры (данные звонилки). */
function weeklyOption(weekly: SummaryData["weekly"], t: TFn) {
  return {
    grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis" },
    legend: {
      top: 0,
      data: [
        t("callsboard.summary.weekly.attempts"),
        t("callsboard.summary.weekly.connected"),
        t("callsboard.summary.weekly.talks"),
      ],
    },
    xAxis: { type: "category", data: weekly.map((w) => w.week.slice(5)) },
    yAxis: { type: "value" },
    series: [
      { name: t("callsboard.summary.weekly.attempts"), type: "bar", data: weekly.map((w) => w.attempts), itemStyle: { color: "#d0d5dd" } },
      { name: t("callsboard.summary.weekly.connected"), type: "bar", data: weekly.map((w) => w.connected), itemStyle: { color: "#465fff" } },
      { name: t("callsboard.summary.weekly.talks"), type: "bar", data: weekly.map((w) => w.talks), itemStyle: { color: "#16a34a" } },
    ],
  };
}

function buildRows(d: SummaryData, t: TFn): Row[] {
  const f = d.facts;
  const p = d.prev_facts;
  const diff = (a: number, b: number | undefined) => (b == null ? null : a - b);
  const rows: Row[] = [
    { key: "assigned", label: t("callsboard.summary.row.assigned"), value: t("callsboard.summary.unit.players", { n: formatInt(f.assigned) }), trend: diff(f.assigned, p?.assigned) },
    { key: "attempts", label: t("callsboard.summary.row.attempts"), value: formatInt(f.attempts), trend: diff(f.attempts, p?.attempts) },
    { key: "connected", label: t("callsboard.summary.row.connected"), value: formatInt(f.connected), trend: diff(f.connected, p?.connected) },
    { key: "talks", label: t("callsboard.summary.row.talks"), value: formatInt(f.talks), trend: diff(f.talks, p?.talks) },
    { key: "never", label: t("callsboard.summary.row.neverCalled"), value: t("callsboard.summary.unit.players", { n: formatInt(f.never_called) }), trend: diff(f.never_called, p?.never_called) },
    { key: "scheduled", label: t("callsboard.summary.row.scheduled"), value: formatInt(d.scheduled_upcoming), trend: null },
    { key: "compliance", label: t("callsboard.summary.row.compliance"), value: t("callsboard.summary.unit.inCalls", { pct: formatFraction(d.compliance_pct) }), trend: null },
    { key: "needsReview", label: t("callsboard.summary.row.needsReview"), value: formatInt(d.needs_review), trend: null },
  ];
  // Средний балл — ТОЛЬКО при разблок. вердикте (§7/§10.12).
  if (d.verdict_unlocked && d.avg_score != null) {
    rows.push({ key: "avg", label: t("callsboard.summary.row.avgScore"), value: formatInt(d.avg_score), trend: d.avg_score_trend ?? null });
  }
  return rows;
}

/** CSV на клиенте из строк сводки. Экранируем кавычки; UTF-8 BOM для Excel. */
function downloadCsv(rows: string[][], filename: string): void {
  const escape = (v: string) => `"${v.replace(/"/g, '""')}"`;
  const csv = rows.map((r) => r.map(escape).join(",")).join("\r\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
