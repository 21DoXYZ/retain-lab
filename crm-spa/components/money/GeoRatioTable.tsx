"use client";

import { formatMoneyMn, formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { OverviewData } from "@/components/money/types";

/**
 * Разбивка выводы/депозиты по гео (Д3, разбор с Василием). Ключевая метрика
 * здоровья: сколько внесённого утекает обратно. Порог ~67% — тревожно, у Tier-3
 * ~70%, выше — гео убыточно. Строку красим, когда ratio перешёл порог.
 * На моно-гео казино (сейчас всё TR) — одна строка; на мульти-гео — по стране.
 */
const WARN = 67;   // порог здоровья по Василию, %

export function GeoRatioTable({ geo }: { geo: OverviewData["geo"] }) {
  const t = useT();
  if (!geo?.length) return null;
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full text-[13px] border-collapse">
        <thead>
          <tr className="text-steel text-[11px] uppercase tracking-[0.5px] text-left">
            <th className="py-1.5 pr-3 font-semibold">{t("geo.col.country")}</th>
            <th className="py-1.5 pr-3 font-semibold text-right">{t("geo.col.deposits")}</th>
            <th className="py-1.5 pr-3 font-semibold text-right">{t("geo.col.withdrawals")}</th>
            <th className="py-1.5 pr-3 font-semibold text-right">{t("geo.col.ratio")}</th>
            <th className="py-1.5 font-semibold text-right">{t("geo.col.depositors")}</th>
          </tr>
        </thead>
        <tbody>
          {geo.map((g) => {
            const hot = g.wd_dep_ratio >= WARN;
            return (
              <tr key={g.country} className="border-t border-hair">
                <td className="py-1.5 pr-3 font-medium">{g.country}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{formatMoneyMn(g.deposits)}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{formatMoneyMn(g.withdrawals)}</td>
                <td className={`py-1.5 pr-3 text-right tabular-nums font-semibold ${hot ? "text-neg" : "text-pos"}`}>
                  {g.wd_dep_ratio}%
                </td>
                <td className="py-1.5 text-right tabular-nums text-steel">{formatInt(g.depositors)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1.5 text-[12px] text-steel">{t("geo.ratioHint")}</p>
    </div>
  );
}
