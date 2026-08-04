"use client";

import type { ReactNode } from "react";
import { DataTable, Panel, type Column } from "@/components/ui";
import { formatInt, formatMoneyMn, formatPct } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { StatusBadge } from "./BonusEconomicsKpi";
import type { BonusFunnelKey, BonusFunnelStage } from "./types";

/**
 * BonusFunnel — воронка бонуса из 7 этапов (ТЗ §3.3): выдан → активирован →
 * отыгрыш начат/завершён → конвертирован/сгорел → депозит в 14 дн → удержан в
 * 30 дн. Строки без потока статусов (status='missing') приглушены и несут бейдж
 * «ждёт события API» — колонку НЕ скрываем (ТЗ). Данные — GET /api/v1/bonus/economics.
 */

const STAGE_KEY: Record<BonusFunnelKey, MessageKey> = {
  issued: "marketing.eco.funnel.issued",
  activated: "marketing.eco.funnel.activated",
  wagering_started: "marketing.eco.funnel.wagering_started",
  wagering_done: "marketing.eco.funnel.wagering_done",
  converted_or_expired: "marketing.eco.funnel.converted_or_expired",
  deposit_14d: "marketing.eco.funnel.deposit_14d",
  retained_30d: "marketing.eco.funnel.retained_30d",
};

const NOTE_KEY: Record<string, MessageKey> = {
  issued: "marketing.eco.funnel.note.issued",
  waitsEvent: "marketing.eco.funnel.note.waitsEvent",
  indirect: "marketing.eco.funnel.note.indirect",
  mart: "marketing.eco.funnel.note.mart",
};

interface Props {
  stages: BonusFunnelStage[] | null;
  loading: boolean;
}

export function BonusFunnel({ stages, loading }: Props) {
  const t = useT();

  function stageValue(s: BonusFunnelStage): ReactNode {
    if (s.value == null) return <span className="text-stone">—</span>;
    if (s.unit === "pct") return formatPct(s.value);
    if (s.stage === "converted_or_expired") return formatMoneyMn(s.value);
    return formatInt(s.value); // счётчики (выдачи, статусы)
  }

  const cols: Column<BonusFunnelStage>[] = [
    {
      key: "stage",
      header: t("marketing.eco.funnel.col.stage"),
      align: "left",
      render: (s) => {
        const muted = s.status === "missing";
        return (
          <div>
            <span className={muted ? "text-stone" : "text-ink"}>{t(STAGE_KEY[s.stage])}</span>
            {s.note_key && NOTE_KEY[s.note_key] ? (
              <div className="text-stone text-[12px] mt-0.5">{t(NOTE_KEY[s.note_key])}</div>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "value",
      header: t("marketing.eco.funnel.col.value"),
      mono: true,
      render: stageValue,
    },
    {
      key: "status",
      header: t("marketing.eco.funnel.col.status"),
      render: (s) => <StatusBadge status={s.status} />,
    },
  ];

  return (
    <Panel>
      <DataTable
        columns={cols}
        rows={stages ?? []}
        getRowKey={(s) => s.stage}
        state={loading ? "loading" : "data"}
      />
    </Panel>
  );
}
