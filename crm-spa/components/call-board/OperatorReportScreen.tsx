"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  PageHeader,
  Eyebrow,
  Card,
  Panel,
  DataTable,
  EmptyState,
  ErrorState,
  type Column,
} from "@/components/ui";
import { flaskFetch, flaskErrorText, FlaskApiError } from "@/lib/api";
import { formatInt, formatDate } from "@/lib/format";
import { useRole } from "@/lib/role-context";
import { useT, useLocale } from "@/lib/i18n";
import {
  useCriterionLabel,
  useOutcomeLabel,
  formatDuration,
} from "./kit";
import { PeriodSelect, usePeriodQuery } from "./ui";
import { ScoreChart } from "./ScoreChart";
import { isOperatorRole } from "./roles";
import type { OperatorReportData, CriterionRow, WorstCall } from "./types";

/**
 * Отчёт по оператору (§10.5) — растёт или падает; о чём говорить с человеком.
 * График с отметкой смены версии + таблица критериев с дельтами + худшие дозвоны.
 * Оператору доступен ТОЛЬКО при разблок. вердикте (сервер сам 403 → мягкий экран).
 */
type ScreenState = "loading" | "error" | "locked" | "data";

export function OperatorReportScreen({ operatorId }: { operatorId: string }) {
  const t = useT();
  const { locale } = useLocale();
  const me = useRole();
  const criterionLabel = useCriterionLabel();
  const outcomeLabel = useOutcomeLabel();
  const [days, setDays] = useState(28);
  const period = usePeriodQuery(days);   // стабильный путь — НЕ periodQuery() в аргументе
  const [state, setState] = useState<ScreenState>("loading");
  const [data, setData] = useState<OperatorReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setState("loading");
    setError(null);
    flaskFetch<OperatorReportData>(
      `/api/v1/call-analysis/operators/${operatorId}/report?${period}`,
    )
      .then((d) => {
        if (!alive) return;
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => {
        if (!alive) return;
        // Оператор при заблок. вердикте → сервер отдаёт 403 (§10.5) — мягкий экран.
        if (e instanceof FlaskApiError && e.status === 403 && isOperatorRole(me.role)) {
          setState("locked");
          return;
        }
        setError(flaskErrorText(e, t, "callsboard.common.loadFailed"));
        setState("error");
      });
    return () => {
      alive = false;
    };
  }, [operatorId, days, nonce, locale, me.role, t]);

  const critCols: Column<CriterionRow>[] = [
    { key: "crit", header: t("callsboard.report.col.criterion"), align: "left", render: (r) => criterionLabel(r.criterion) },
    { key: "avg", header: t("callsboard.report.col.score"), mono: true, render: (r) => r.avg.toFixed(1) },
    { key: "delta", header: t("callsboard.report.col.change"), align: "right", render: (r) => <DeltaText value={r.delta} /> },
  ];

  const worstCols: Column<WorstCall>[] = [
    { key: "call", header: t("callsboard.report.col.call"), id: true, render: (r) => `#${r.call_id.slice(0, 4).toUpperCase()}` },
    { key: "dur", header: t("callsboard.report.col.duration"), mono: true, render: (r) => formatDuration(r.duration_s) },
    { key: "score", header: t("callsboard.report.col.score"), mono: true, render: (r) => (r.score == null ? "—" : formatInt(r.score)) },
    { key: "out", header: t("callsboard.report.col.outcome"), align: "left", render: (r) => outcomeLabel(r.offer_outcome) },
    {
      key: "open",
      header: "",
      align: "right",
      render: (r) => (
        <Link href={`/call-analysis/calls/${r.call_id}`} className="text-primary font-medium hover:underline">
          {t("callsboard.report.open")}
        </Link>
      ),
    },
  ];

  const title = data?.operator_name ?? operatorId.slice(0, 8);

  if (state === "locked") {
    return (
      <>
        <BackHeader title={t("callsboard.overview.title")} />
        <div className="mt-8">
          <EmptyState icon="🔒" title={t("callsboard.report.locked.title")} description={t("callsboard.report.locked.body")} />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <Link href="/call-analysis" className="text-[14px] font-medium text-primary hover:underline">
              ← {t("callsboard.report.back")}
            </Link>
            <span>{title}</span>
          </span>
        }
        right={<PeriodSelect value={days} onChange={setDays} options={[7, 14, 28]} />}
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={() => setNonce((n) => n + 1)} />
      ) : (
        <>
          <Eyebrow>{t("callsboard.report.chartTitle")}</Eyebrow>
          <Card>
            {state === "loading" ? (
              <div className="h-[260px] animate-pulse rounded-md bg-hair2/60" />
            ) : data && data.weekly.length ? (
              <>
                <ScoreChart weekly={data.weekly} scriptChanges={data.script_changes} />
                {data.script_changes.map((c) => (
                  <p key={`${c.version}-${c.activated_at}`} className="mt-3 text-[13px] text-steel">
                    ⓘ {t("callsboard.report.scriptChangeNote", { date: formatDate(c.activated_at) })}
                  </p>
                ))}
              </>
            ) : (
              <div className="py-8 text-center text-steel text-[13.5px]">{t("callsboard.report.noWeekly")}</div>
            )}
          </Card>

          <Eyebrow>{t("callsboard.report.criteria")}</Eyebrow>
          <Panel>
            <DataTable
              columns={critCols}
              rows={data?.criteria ?? []}
              getRowKey={(r) => r.criterion}
              state={state === "loading" ? "loading" : data?.criteria.length ? "data" : "empty"}
              emptyTitle={t("callsboard.report.empty")}
            />
          </Panel>

          <Eyebrow>{t("callsboard.report.worst")}</Eyebrow>
          <Panel>
            <DataTable
              columns={worstCols}
              rows={data?.worst_calls ?? []}
              getRowKey={(r) => r.call_id}
              state={state === "loading" ? "loading" : data?.worst_calls.length ? "data" : "empty"}
              emptyTitle={t("callsboard.report.empty")}
            />
          </Panel>
        </>
      )}
    </>
  );
}

function BackHeader({ title }: { title: string }) {
  return (
    <PageHeader
      title={
        <Link href="/call-analysis" className="text-[15px] font-medium text-primary hover:underline">
          ← {title}
        </Link>
      }
    />
  );
}

/** Дельта критерия с одним знаком после запятой (§10.5) — не целое, свой рендер. */
function DeltaText({ value }: { value: number | null }) {
  if (value == null) return <span className="font-mono text-stone">—</span>;
  const r = Math.round(value * 10) / 10;
  if (r === 0) return <span className="font-mono text-steel">→ 0</span>;
  const up = r > 0;
  return (
    <span className={`font-mono font-medium ${up ? "text-pos" : "text-neg"}`}>
      {up ? "↑ +" : "↓ −"}
      {Math.abs(r).toFixed(1)}
    </span>
  );
}
