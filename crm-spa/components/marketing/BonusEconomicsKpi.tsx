"use client";

import type { ReactNode } from "react";
import { Badge, SCard, SCardGrid } from "@/components/ui";
import { formatInt, formatMoneyMn, formatPct } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import type { BonusKpiItem, BonusKpiKey, EconStatus } from "./types";

/**
 * BonusEconomicsKpi — 7 KPI-плашек P&L бонусов (ТЗ §3.3) с бейджем доступности
 * метрики. У метрик со status='needs_event' в поле значения — поясняющий текст
 * «нужно событие bonus_converted», а не заглушка-ноль (плашка честно говорит,
 * чего не хватает). Данные — из GET /api/v1/bonus/economics.
 */

// тона бейджей — из общей палитры дашборда (совпадают с RFM_META в борде)
const STATUS_TONE: Record<EconStatus, { bg: string; fg: string }> = {
  ok: { bg: "#dcfce7", fg: "#166534" },
  partial: { bg: "#fef9c3", fg: "#854d0e" },
  needs_event: { bg: "#f2f4f7", fg: "#344054" },
  missing: { bg: "#f2f4f7", fg: "#98a2b3" },
  indirect: { bg: "#ffedd5", fg: "#9a3412" },
};

const STATUS_KEY: Record<EconStatus, MessageKey> = {
  ok: "marketing.eco.status.ok",
  partial: "marketing.eco.status.partial",
  needs_event: "marketing.eco.status.needs_event",
  missing: "marketing.eco.status.missing",
  indirect: "marketing.eco.status.indirect",
};

const KPI_ORDER: BonusKpiKey[] = [
  "issued", "cost", "incr_deposits", "ggr", "ngr", "roi", "uplift",
];

const KPI_LABEL: Record<BonusKpiKey, MessageKey> = {
  issued: "marketing.eco.kpi.issued.label",
  cost: "marketing.eco.kpi.cost.label",
  incr_deposits: "marketing.eco.kpi.incr_deposits.label",
  ggr: "marketing.eco.kpi.ggr.label",
  ngr: "marketing.eco.kpi.ngr.label",
  roi: "marketing.eco.kpi.roi.label",
  uplift: "marketing.eco.kpi.uplift.label",
};

const KPI_ICON: Record<BonusKpiKey, string> = {
  issued: "🎁", cost: "💸", incr_deposits: "📈", ggr: "🎰",
  ngr: "💰", roi: "📊", uplift: "🧠",
};

const MONEY_KEYS = new Set<BonusKpiKey>(["issued", "cost", "ggr", "ngr"]);

/** Бейдж доступности метрики (считается / частично / нужно событие / …). */
export function StatusBadge({ status }: { status: EconStatus }) {
  const t = useT();
  const tone = STATUS_TONE[status];
  return (
    <Badge bg={tone.bg} fg={tone.fg}>
      {t(STATUS_KEY[status])}
    </Badge>
  );
}

/** Знаковое число с одним знаком после запятой (для CI, как в BonusScreen). */
function sgn(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}`;
}

interface Props {
  items: BonusKpiItem[] | null;
  loading: boolean;
}

export function BonusEconomicsKpi({ items, loading }: Props) {
  const t = useT();

  function renderValue(item: BonusKpiItem): ReactNode {
    // needs_event: вместо числа — поясняющий текст (ТЗ §4.1), не ноль-заглушка
    if (item.status === "needs_event") {
      return (
        <span className="text-[13.5px] font-medium text-steel leading-snug block">
          {t("marketing.eco.needsEvent")}
        </span>
      );
    }
    if (item.value == null) return "—";
    if (MONEY_KEYS.has(item.key)) return formatMoneyMn(item.value);
    if (item.key === "incr_deposits") return formatInt(item.value);
    if (item.key === "roi") return formatPct(item.value);
    if (item.key === "uplift") {
      return `${item.value >= 0 ? "+" : ""}${item.value.toFixed(1)} ${t("marketing.bonus.ppSuffix")}`;
    }
    return formatInt(item.value);
  }

  function renderSub(item: BonusKpiItem): ReactNode {
    const badge = <StatusBadge status={item.status} />;
    let extra: ReactNode = null;
    if (item.key === "issued" && item.count != null) {
      extra = t("marketing.eco.kpi.issued.sub", {
        count: formatInt(item.count),
        uniq: formatInt(item.uniq),
      });
    } else if (item.key === "uplift" && item.ci_lo != null) {
      extra = t("marketing.eco.kpi.uplift.sub", {
        lo: sgn(item.ci_lo),
        hi: sgn(item.ci_hi),
        nt: formatInt(item.n_treated),
        nc: formatInt(item.n_control),
      });
    } else if (item.key === "incr_deposits" && item.value != null) {
      extra = t("marketing.eco.kpi.incr_deposits.sub");
    }
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        {badge}
        {extra ? <span>{extra}</span> : null}
      </span>
    );
  }

  // loading / нет данных — 7 плашек-скелетонов в стабильном порядке
  if (loading || !items) {
    return (
      <SCardGrid>
        {KPI_ORDER.map((k) => (
          <SCard key={k} loading label={t(KPI_LABEL[k])} value="" />
        ))}
      </SCardGrid>
    );
  }

  const byKey = new Map(items.map((i) => [i.key, i]));

  return (
    <SCardGrid>
      {KPI_ORDER.map((k) => {
        const item = byKey.get(k);
        if (!item) return null;
        const negNgr = k === "ngr" && item.value != null && item.value < 0;
        return (
          <SCard
            key={k}
            icon={KPI_ICON[k]}
            variant={k === "issued" ? "orange" : "default"}
            valueTone={negNgr ? "neg" : "default"}
            label={t(KPI_LABEL[k])}
            value={renderValue(item)}
            sub={renderSub(item)}
          />
        );
      })}
    </SCardGrid>
  );
}
