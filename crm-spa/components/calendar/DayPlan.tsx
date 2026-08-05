"use client";

import { DataTable, LifecycleBadge, Badge, Eyebrow, type Column } from "@/components/ui";
import { formatDateShort } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { DayPlanRow } from "./types";

/**
 * Operator day plan (ТЗ п.5.2): today's scheduled calls sorted by time, with
 * overdue (past-day) touches pinned in their own section on top. Rows link to
 * the player card, where the operator acts and re-plans (B3).
 */
export function DayPlan({ rows }: { rows: DayPlanRow[] }) {
  const t = useT();

  const overdue = rows.filter((r) => r.overdue);
  const today = rows.filter((r) => !r.overdue);

  if (rows.length === 0) {
    return (
      <PlanTable
        rows={[]}
        state="empty"
        emptyTitle={t("calendar.empty.today.title")}
        emptyDescription={t("calendar.empty.today.desc")}
      />
    );
  }

  return (
    <div className="space-y-6">
      {overdue.length > 0 ? (
        <section>
          <Eyebrow>{t("calendar.section.overdue")}</Eyebrow>
          <PlanTable rows={overdue} />
        </section>
      ) : null}
      {today.length > 0 ? (
        <section>
          <Eyebrow>{t("calendar.section.today")}</Eyebrow>
          <PlanTable rows={today} />
        </section>
      ) : null}
    </div>
  );
}

interface PlanTableProps {
  rows: DayPlanRow[];
  state?: "data" | "empty";
  emptyTitle?: string;
  emptyDescription?: string;
}

function PlanTable({ rows, state = "data", emptyTitle, emptyDescription }: PlanTableProps) {
  const t = useT();

  const columns: Column<DayPlanRow>[] = [
    {
      key: "time",
      header: t("calendar.col.time"),
      align: "left",
      mono: true,
      render: (r) => formatDateShort(r.scheduled_at),
    },
    {
      key: "player",
      header: t("calendar.col.player"),
      align: "left",
      id: true,
      render: (r) => r.player?.display_id ?? `#${r.casino_player_id}`,
    },
    {
      key: "stage",
      header: t("calendar.col.stage"),
      align: "left",
      render: (r) => <LifecycleBadge stage={r.player?.lifecycle} />,
    },
    {
      key: "comment",
      header: t("calendar.col.comment"),
      align: "left",
      render: (r) => (
        <span className="text-slate">{r.comment ?? t("common.dash")}</span>
      ),
    },
    {
      key: "mark",
      header: "",
      align: "right",
      render: (r) => (
        <div className="flex gap-1.5 justify-end">
          {r.overdue ? (
            <Badge bg="#fef2f2" fg="#dc2626">
              {t("calendar.badge.overdue")}
            </Badge>
          ) : null}
          {r.by_system ? (
            <Badge bg="#ecf3ff" fg="#3641f5">
              {t("calendar.badge.system")}
            </Badge>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      state={state}
      getRowKey={(r) => r.id}
      getRowHref={(r) => `/players/${r.casino_player_id}`}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
    />
  );
}
