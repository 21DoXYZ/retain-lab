"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  PageHeader,
  Eyebrow,
  Panel,
  DataTable,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useCallResource } from "./kit";
import { PeriodSelect, usePeriodQuery } from "./ui";
import { CoverageOperatorModal } from "./CoverageOperatorModal";
import type { CoverageData, CoverageOperator } from "./types";

/**
 * Покрытие обзвона (§10.7) — кого переназначить; кто не набирает назначенных.
 * «Не набирали» ≠ «не дозвонились». Переназначение НЕ реализовано (нет ручки в
 * бэкенде) — кнопку не рисуем, показываем, кого пора передать (см. отчёт).
 */
export function CoverageScreen() {
  const t = useT();
  const [days, setDays] = useState(1);
  const period = usePeriodQuery(days);   // стабильный путь — НЕ periodQuery() в аргументе
  const [drill, setDrill] = useState<{ id: string; name: string | null } | null>(null);
  const { state, data, error, reload } = useCallResource<CoverageData>(
    `/api/v1/call-analysis/coverage?${period}`,
  );
  const loading = state !== "data";

  const reviewRows = useMemo(
    () => (data?.operators ?? []).filter((o) => o.in_review > 0),
    [data],
  );

  const totals: { key: string; label: string; value: number | undefined }[] = [
    { key: "assigned", label: t("callsboard.coverage.totals.assigned"), value: data?.totals.assigned },
    { key: "attempts", label: t("callsboard.coverage.totals.attempts"), value: data?.totals.attempts },
    { key: "connected", label: t("callsboard.coverage.totals.connected"), value: data?.totals.connected },
    { key: "talks", label: t("callsboard.coverage.totals.talks"), value: data?.totals.talks },
    { key: "never", label: t("callsboard.coverage.totals.neverCalled"), value: data?.totals.never_called },
    { key: "review", label: t("callsboard.coverage.totals.inReview"), value: data?.totals.in_review },
  ];

  const cols: Column<CoverageOperator>[] = [
    { key: "op", header: t("callsboard.coverage.col.operator"), id: true, render: (r) => r.operator_name ?? r.operator_id.slice(0, 8) },
    { key: "assigned", header: t("callsboard.coverage.col.assigned"), mono: true, render: (r) => formatInt(r.assigned) },
    { key: "never", header: t("callsboard.coverage.col.neverCalled"), mono: true, render: (r) => (r.never_called > 0 ? <span className="text-neg font-medium">{formatInt(r.never_called)}</span> : formatInt(r.never_called)) },
    { key: "connected", header: t("callsboard.coverage.col.connected"), mono: true, render: (r) => formatInt(r.connected) },
    { key: "talks", header: t("callsboard.coverage.col.talks"), mono: true, render: (r) => formatInt(r.talks) },
    { key: "scheduled", header: t("callsboard.coverage.col.scheduled"), mono: true, render: (r) => formatInt(r.scheduled) },
    { key: "review", header: t("callsboard.coverage.col.inReview"), mono: true, render: (r) => formatInt(r.in_review) },
    { key: "detail", header: "", align: "right", render: (r) => (
      <button
        type="button"
        className="text-[12px] text-primary hover:underline"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setDrill({ id: r.operator_id, name: r.operator_name }); }}
      >
        {t("callsboard.coverage.detail")}
      </button>
    ) },
  ];

  return (
    <>
      <PageHeader
        title={t("callsboard.coverage.title")}
        accent={t("callsboard.coverage.subtitle")}
        right={<PeriodSelect value={days} onChange={setDays} />}
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <Eyebrow>{t("callsboard.coverage.needsAction")}</Eyebrow>
          <Panel className="px-5 py-2">
            <ul className="divide-y divide-hair">
              {/* Переназначение вручную в CRM — кнопки нет (нет ручки), только сигнал. */}
              {data && data.totals.never_called > 0 ? (
                <li className="py-3 text-[13.5px] text-slate">
                  {t("callsboard.coverage.action.neverCalled", { count: data.totals.never_called })}
                </li>
              ) : null}
              {reviewRows.map((o) => (
                <li key={o.operator_id} className="flex items-center justify-between gap-4 py-3">
                  <span className="text-[13.5px] text-slate">
                    {t("callsboard.coverage.action.review", { name: o.operator_name ?? o.operator_id.slice(0, 8), count: o.in_review })}
                  </span>
                  <Link href={`/call-analysis/operators/${o.operator_id}`} className="flex-none text-primary font-medium text-[13px] hover:underline">
                    {t("callsboard.coverage.action.review.cta")} →
                  </Link>
                </li>
              ))}
              {(!data || (data.totals.never_called === 0 && reviewRows.length === 0)) && !loading ? (
                <li className="py-3 text-[13.5px] text-steel">{t("callsboard.overview.action.empty")}</li>
              ) : null}
            </ul>
          </Panel>

          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {totals.map((s) => (
              <div key={s.key} className="rounded-card border border-hair bg-canvas px-4 py-3">
                <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel">{s.label}</div>
                <div className="mt-1 font-mono text-[22px] font-extrabold text-ink">{formatInt(s.value)}</div>
              </div>
            ))}
          </div>

          <Eyebrow>{t("callsboard.coverage.col.operator")}</Eyebrow>
          <Panel>
            <DataTable
              columns={cols}
              rows={data?.operators ?? []}
              getRowKey={(r) => r.operator_id}
              getRowHref={(r) => `/call-analysis/operators/${r.operator_id}`}
              state={loading ? "loading" : data?.operators.length ? "data" : "empty"}
              emptyTitle={t("callsboard.coverage.empty")}
            />
          </Panel>

          <p className="mt-3 text-[13px] text-steel">{t("callsboard.coverage.note.neverCalled")}</p>
          <p className="mt-1.5 text-[13px] text-steel">{t("callsboard.coverage.note.reassign")}</p>
        </>
      )}

      <CoverageOperatorModal
        operatorId={drill?.id ?? null}
        operatorName={drill?.name ?? null}
        onClose={() => setDrill(null)}
      />
    </>
  );
}
