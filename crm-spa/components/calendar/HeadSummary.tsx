"use client";

import { DataTable, type Column } from "@/components/ui";
import { DEPT_LABELS } from "@/lib/permissions";
import type { Department } from "@/lib/types";
import { useT, type MessageKey } from "@/lib/i18n";
import type { OperatorSummary } from "./types";

/**
 * Head-of-department calendar summary (ТЗ п.5.5): planned / done / overdue per
 * operator — discipline control ("может, они целый день сидят и не звонят").
 * Read-only aggregate; operators with zero scheduled calls are shown too so the
 * gaps are visible.
 */
export function HeadSummary({ rows }: { rows: OperatorSummary[] }) {
  const t = useT();

  const columns: Column<OperatorSummary>[] = [
    {
      key: "operator",
      header: t("calendar.col.operator"),
      align: "left",
      render: (r) => (
        <div className="flex flex-col">
          <span className="font-medium text-ink">{r.name}</span>
          {r.department ? (
            <span className="text-[12px] text-steel">
              {/* Отдел — через словарь ("admin.dept.*"), как в UserMenu;
                  DEPT_LABELS остаётся русским фолбэком для незнакомого кода. */}
              {t(`admin.dept.${r.department}` as MessageKey) ||
                DEPT_LABELS[r.department as Department] ||
                r.department}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      key: "planned",
      header: t("calendar.col.planned"),
      mono: true,
      render: (r) => r.planned,
    },
    {
      key: "done",
      header: t("calendar.col.done"),
      mono: true,
      render: (r) => <span className={r.done > 0 ? "text-pos" : undefined}>{r.done}</span>,
    },
    {
      key: "overdue",
      header: t("calendar.col.overdue"),
      mono: true,
      render: (r) => <span className={r.overdue > 0 ? "text-neg font-semibold" : undefined}>{r.overdue}</span>,
    },
    {
      key: "total",
      header: t("calendar.col.total"),
      mono: true,
      render: (r) => <span className="font-semibold text-ink">{r.total}</span>,
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      state={rows.length === 0 ? "empty" : "data"}
      getRowKey={(r) => r.operator_id}
      emptyTitle={t("calendar.empty.summary.title")}
      emptyDescription={t("calendar.empty.summary.desc")}
    />
  );
}
