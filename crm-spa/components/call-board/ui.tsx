"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Select } from "@/components/ui";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import { formatFraction } from "./kit";

/* ---------------------------------------------------------------------------
 * Period selection — the [Неделя ▾] / [Сегодня ▾] dropdowns (§10.1/§10.7). The
 * backend takes ?from&to (defaults to the last week); we compute the range from
 * a day count so every screen shares one control and one query builder.
 * ------------------------------------------------------------------------- */
export const PERIOD_DAYS = [1, 7, 14, 28] as const;
export type PeriodDays = (typeof PERIOD_DAYS)[number];

/** ?from&to for the trailing `days`-day window ending now (UTC ISO). */
export function periodQuery(days: number): string {
  const to = new Date();
  const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
  return `from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}`;
}

/**
 * СТАБИЛЬНЫЙ ?from&to для выбранного периода. ОБЯЗАТЕЛЕН вместо periodQuery()
 * прямо в аргументе useCallResource: там new Date() даёт новый timestamp с
 * миллисекундами НА КАЖДОМ рендере → путь меняется → эффект перезапрашивает →
 * рендер → … — бесконечный цикл «загрузка-данные-загрузка» (экран «постоянно
 * перегружается»). Мемоизация по days рвёт цикл; окно пересчитывается при
 * смене периода пользователем.
 */
export function usePeriodQuery(days: number): string {
  return useMemo(() => periodQuery(days), [days]);
}

const PERIOD_LABEL: Record<PeriodDays, MessageKey> = {
  1: "callsboard.period.today",
  7: "callsboard.period.week",
  14: "callsboard.period.twoWeeks",
  28: "callsboard.period.fourWeeks",
};

export function PeriodSelect({
  value,
  onChange,
  options = PERIOD_DAYS,
}: {
  value: number;
  onChange: (days: number) => void;
  options?: readonly PeriodDays[];
}) {
  const t = useT();
  return (
    <Select
      aria-label={t("callsboard.period.label")}
      value={String(value)}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-auto min-w-[132px]"
    >
      {options.map((d) => (
        <option key={d} value={d}>
          {t(PERIOD_LABEL[d])}
        </option>
      ))}
    </Select>
  );
}

/* ---------------------------------------------------------------------------
 * VerdictBanner — the ⓘ callout on the Overview (§10.1). Shows REAL numbers,
 * never an invented target («проверено 64 · согласие 78%», not «64 из 100»).
 * `detailsHref` links to /call-analysis/verdict — only wired for admins, since
 * that page is admin-only (§10.13).
 * ------------------------------------------------------------------------- */
export function VerdictBanner({
  unlocked,
  checked,
  agreement,
  detailsHref,
}: {
  unlocked: boolean;
  checked: number;
  agreement: number | null;
  detailsHref?: string;
}) {
  const t = useT();
  return (
    <div className="bg-cream border border-beige border-l-[3px] border-l-primary rounded-card px-[18px] py-[13px] mt-5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13.5px]">
      <span aria-hidden className="text-primary font-semibold">
        ⓘ
      </span>
      <span className="font-medium text-ink">
        {unlocked ? t("callsboard.verdict.bannerUnlocked") : t("callsboard.verdict.bannerLocked")}
      </span>
      <span className="text-steel">
        {t("callsboard.overview.bannerReconciliation", {
          checked,
          agreement: formatFraction(agreement),
        })}
      </span>
      {detailsHref ? (
        <Link
          href={detailsHref}
          className="ml-auto text-primary font-medium hover:underline"
        >
          {t("callsboard.overview.bannerDetails")}
        </Link>
      ) : null}
    </div>
  );
}
