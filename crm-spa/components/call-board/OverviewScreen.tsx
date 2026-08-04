"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  PageHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Panel,
  DataTable,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useRole } from "@/lib/role-context";
import { useT } from "@/lib/i18n";
import {
  useCallResource,
  useCriterionLabel,
  TrendCell,
  formatFraction,
} from "./kit";
import { PeriodSelect, usePeriodQuery, VerdictBanner } from "./ui";
import { ADMIN } from "./roles";
import type { OverviewData, OverviewOperator } from "./types";

/**
 * Обзор (§10.1) — «с чего начать день». Верх — список действий, цифры ниже как
 * обоснование. Роли: head_department / head_retention / analyst (RO) / super_admin.
 */

interface ActionItem {
  key: string;
  text: string;
  cta: string;
  href: string;
}

export function OverviewScreen() {
  const t = useT();
  const me = useRole();
  const criterionLabel = useCriterionLabel();
  const [days, setDays] = useState(7);
  const period = usePeriodQuery(days);   // стабильный путь — НЕ periodQuery() в аргументе
  const { state, data, error, reload } = useCallResource<OverviewData>(
    `/api/v1/call-analysis/overview?${period}`,
  );
  const loading = state !== "data";

  const actions = useMemo(() => buildActions(data, t), [data, t]);

  const avgScore = useMemo(() => teamAvg(data?.operators ?? []), [data]);
  const analyzedPct =
    data && data.totals.connected > 0
      ? formatFraction(data.totals.analyzed / data.totals.connected)
      : "—";

  const isAdmin = (ADMIN as readonly string[]).includes(me.role);

  const cols: Column<OverviewOperator>[] = [
    { key: "op", header: t("callsboard.overview.col.operator"), id: true, render: (r) => r.operator_name ?? r.operator_id.slice(0, 8) },
    { key: "connected", header: t("callsboard.overview.col.connected"), mono: true, render: (r) => formatInt(r.connected) },
    { key: "score", header: t("callsboard.overview.col.score"), mono: true, render: (r) => (r.avg_score == null ? "—" : formatInt(r.avg_score)) },
    { key: "trend", header: t("callsboard.overview.col.trend"), align: "right", render: (r) => <TrendCell value={r.trend} /> },
    {
      key: "weak",
      header: t("callsboard.overview.col.weakSpot"),
      align: "left",
      render: (r) =>
        r.weak_spot ? (
          <span>
            {criterionLabel(r.weak_spot.criterion)}{" "}
            <span className="font-mono text-steel">{r.weak_spot.avg.toFixed(1)}/5</span>
          </span>
        ) : (
          <span className="text-stone">—</span>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("callsboard.overview.title")}
        accent={t("callsboard.overview.subtitle")}
        right={<PeriodSelect value={days} onChange={setDays} />}
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          {data ? (
            <VerdictBanner
              unlocked={data.verdict_unlocked}
              checked={data.reconciliation.checked}
              agreement={data.reconciliation.agreement}
              detailsHref={isAdmin ? "/call-analysis/verdict" : undefined}
            />
          ) : null}

          <Eyebrow>{t("callsboard.overview.needsAction")}</Eyebrow>
          <Panel className="px-5 py-2">
            {loading ? (
              <div className="py-6 text-steel text-[13.5px]">…</div>
            ) : actions.length === 0 ? (
              <div className="py-4 text-steel text-[13.5px]">{t("callsboard.overview.action.empty")}</div>
            ) : (
              <ul className="divide-y divide-hair">
                {actions.map((a) => (
                  <li key={a.key} className="flex items-center justify-between gap-4 py-3">
                    <span className="text-[13.5px] text-slate">{a.text}</span>
                    <Link
                      href={a.href}
                      className="flex-none text-primary font-medium text-[13px] hover:underline"
                    >
                      {a.cta} →
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <SCardGrid className="mt-6">
            <SCard loading={loading} icon="📞" label={t("callsboard.overview.kpi.connected")} value={formatInt(data?.totals.connected)} />
            <SCard
              loading={loading}
              icon="✅"
              label={t("callsboard.overview.kpi.analyzed")}
              value={formatInt(data?.totals.analyzed)}
              sub={t("callsboard.overview.kpi.analyzedSub", { pct: analyzedPct })}
            />
            <SCard
              loading={loading}
              icon="📊"
              label={t("callsboard.overview.kpi.avgScore")}
              value={avgScore == null ? "—" : formatInt(avgScore)}
              title={t("callsboard.overview.kpi.avgScore.hint")}
            />
            <SCard
              loading={loading}
              variant="alert"
              icon="🚫"
              label={t("callsboard.overview.kpi.neverCalled")}
              value={formatInt(data?.totals.never_called)}
              title={t("callsboard.overview.kpi.neverCalled.hint")}
            />
          </SCardGrid>

          {data ? (
            <p className="mt-3 text-[13px] text-steel">
              {t("callsboard.overview.analyzedProof", {
                analyzed: formatInt(data.totals.analyzed),
                connected: formatInt(data.totals.connected),
              })}
            </p>
          ) : null}

          <Eyebrow>{t("callsboard.overview.operators")}</Eyebrow>
          <Panel>
            <DataTable
              columns={cols}
              rows={data?.operators ?? []}
              getRowKey={(r) => r.operator_id}
              getRowHref={(r) => `/call-analysis/operators/${r.operator_id}`}
              state={loading ? "loading" : data?.operators.length ? "data" : "empty"}
              emptyTitle={t("callsboard.overview.empty")}
            />
          </Panel>
        </>
      )}
    </>
  );
}

/** Взвешенное по разобранным среднее балла операторов — тренда в /overview нет. */
function teamAvg(ops: OverviewOperator[]): number | null {
  let sum = 0;
  let n = 0;
  for (const o of ops) {
    if (o.avg_score != null && o.analyzed > 0) {
      sum += o.avg_score * o.analyzed;
      n += o.analyzed;
    }
  }
  return n > 0 ? Math.round(sum / n) : null;
}

type TFn = ReturnType<typeof useT>;

function buildActions(data: OverviewData | null, t: TFn): ActionItem[] {
  if (!data) return [];
  const na = data.needs_action;
  const out: ActionItem[] = [];
  const push = (cond: boolean, key: string, text: string, cta: string, href: string) => {
    if (cond) out.push({ key, text, cta, href });
  };
  push(na.never_called > 0, "never", t("callsboard.overview.action.neverCalled", { count: na.never_called }), t("callsboard.overview.action.neverCalled.cta"), "/call-analysis/coverage");
  push(na.queue_needs_review > 0, "queue", t("callsboard.overview.action.queue", { count: na.queue_needs_review }), t("callsboard.overview.action.queue.cta"), "/call-analysis/queue");
  push(na.cards_pending_approve > 0, "approve", t("callsboard.overview.action.approve", { count: na.cards_pending_approve }), t("callsboard.overview.action.approve.cta"), "/call-analysis/queue");
  for (const d of na.score_drops) {
    out.push({
      key: `drop-${d.operator_id}`,
      text: t("callsboard.overview.action.scoreDrop", { name: d.operator_name ?? d.operator_id.slice(0, 8), from: d.from, to: d.to }),
      cta: t("callsboard.overview.action.scoreDrop.cta"),
      href: `/call-analysis/operators/${d.operator_id}`,
    });
  }
  push(na.disputed_cards > 0, "disputed", t("callsboard.overview.action.disputed", { count: na.disputed_cards }), t("callsboard.overview.action.disputed.cta"), "/call-analysis/queue");
  push(na.manual_review > 0, "manual", t("callsboard.overview.action.manual", { count: na.manual_review }), t("callsboard.overview.action.manual.cta"), "/call-analysis/queue");
  push(na.failed_records > 0, "failed", t("callsboard.overview.action.failed", { count: na.failed_records }), t("callsboard.overview.action.failed.cta"), "/call-analysis/queue");
  return out;
}
