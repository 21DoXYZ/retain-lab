"use client";

import type { ReactNode } from "react";
import { Card } from "@/components/ui";
import { formatInt, formatMoney, formatPct } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { LabelValue, MonthMoney, TopGame } from "./types";

/**
 * Presentational bar/table blocks for the affiliate detail — CSS-only, 1:1 with
 * the board's `.trow` distribution bars and the top-games / money-flow tables.
 * No chart library: keeps the screen self-contained and light.
 */

/** Section wrapper with a title + optional caption (board .chbox). */
export function ChartCard({
  title,
  caption,
  children,
  className,
}: {
  title: ReactNode;
  caption?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {caption ? <div className="text-xs text-steel mb-2.5">{caption}</div> : null}
      <div className="mt-2">{children}</div>
    </Card>
  );
}

/** Horizontal distribution bars (board .tbl / .trow), value right-aligned. */
export function MiniBars({
  data,
  money = false,
}: {
  data: LabelValue[];
  money?: boolean;
}) {
  if (!data.length) return <div className="text-[12.5px] text-steel">—</div>;
  const max = Math.max(...data.map(([, v]) => v)) || 1;
  return (
    <div className="flex flex-col gap-[3px]">
      {data.map(([label, value]) => (
        <div
          key={label}
          className="relative flex justify-between items-center overflow-hidden rounded-md px-2.5 py-1.5 text-[12.5px]"
        >
          <span
            className="absolute inset-y-0 left-0 bg-primary/10"
            style={{ width: `${Math.round((value / max) * 100)}%` }}
          />
          <span className="relative z-[1] max-w-[70%] truncate text-slate">{label}</span>
          <span className="relative z-[1] font-mono text-primary">
            {money ? formatMoney(value) : formatInt(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Funnel — registrations → FTD → active, scaled to the widest step (board's
 * three-stage source funnel). Each step shows count + share of registrations.
 */
export function Funnel({
  registrations,
  ftd,
  active,
}: {
  registrations: number;
  ftd: number;
  active: number;
}) {
  const t = useT();
  const base = registrations || 1;
  const steps: { key: string; label: string; value: number; color: string }[] = [
    { key: "reg", label: t("monitor.bars.funnel.registrations"), value: registrations, color: "#2563eb" },
    { key: "ftd", label: t("monitor.bars.funnel.ftd"), value: ftd, color: "#60a5fa" },
    { key: "act", label: t("monitor.bars.funnel.active"), value: active, color: "#16a34a" },
  ];
  return (
    <div className="flex flex-col gap-2">
      {steps.map((s) => (
        <div key={s.key} className="flex items-center gap-3">
          <span className="w-[168px] flex-none text-[12.5px] text-slate">{s.label}</span>
          <div className="relative h-8 flex-1 overflow-hidden rounded-md bg-hair2/40">
            <span
              className="absolute inset-y-0 left-0 rounded-md"
              style={{
                width: `${Math.max(2, Math.round((s.value / base) * 100))}%`,
                background: s.color,
              }}
            />
          </div>
          <span className="w-[128px] flex-none text-right font-mono text-[12.5px]">
            {formatInt(s.value)}
            <span className="ml-1 text-steel">
              {formatPct(base ? (s.value / base) * 100 : 0)}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

/** Deposits vs Withdrawals by month (board money chart, as a compact table). */
export function MoneyByMonth({ data }: { data: MonthMoney[] }) {
  const t = useT();
  if (!data.length) return <div className="text-[12.5px] text-steel">—</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-[11px] uppercase tracking-[0.5px] text-steel">
            <th className="border-b border-hair px-3 py-2 text-left font-normal">{t("monitor.bars.money.month")}</th>
            <th className="border-b border-hair px-3 py-2 text-right font-normal">{t("monitor.bars.money.deposits")}</th>
            <th className="border-b border-hair px-3 py-2 text-right font-normal">{t("monitor.bars.money.withdrawals")}</th>
          </tr>
        </thead>
        <tbody>
          {data.map(([m, dep, wd]) => (
            <tr key={m}>
              <td className="border-b border-hair px-3 py-2 text-left">{m}</td>
              <td className="border-b border-hair px-3 py-2 text-right font-mono text-pos">
                {formatMoney(dep)}
              </td>
              <td className="border-b border-hair px-3 py-2 text-right font-mono text-neg">
                {formatMoney(wd)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Top games in the window (board top-games table). */
export function TopGamesTable({ rows }: { rows: TopGame[] }) {
  const t = useT();
  if (!rows.length) return <div className="text-[12.5px] text-steel">{t("monitor.bars.topGames.empty")}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-[11px] uppercase tracking-[0.5px] text-steel">
            <th className="border-b border-hair px-3 py-2 text-left font-normal">{t("monitor.bars.topGames.game")}</th>
            <th className="border-b border-hair px-3 py-2 text-left font-normal">{t("monitor.bars.topGames.provider")}</th>
            <th className="border-b border-hair px-3 py-2 text-right font-normal">{t("monitor.bars.topGames.players")}</th>
            <th className="border-b border-hair px-3 py-2 text-right font-normal">{t("monitor.bars.topGames.bets")}</th>
            <th className="border-b border-hair px-3 py-2 text-right font-normal">{t("monitor.bars.topGames.turnover")}</th>
            <th className="border-b border-hair px-3 py-2 text-right font-normal">Net</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => (
            <tr key={g.game}>
              <td className="border-b border-hair px-3 py-2 text-left">{g.game}</td>
              <td className="border-b border-hair px-3 py-2 text-left text-steel">
                {g.provider || "—"}
              </td>
              <td className="border-b border-hair px-3 py-2 text-right font-mono">
                {formatInt(g.players)}
              </td>
              <td className="border-b border-hair px-3 py-2 text-right font-mono">
                {formatInt(g.bets)}
              </td>
              <td className="border-b border-hair px-3 py-2 text-right font-mono">
                {formatInt(g.turnover)}
              </td>
              <td
                className={`border-b border-hair px-3 py-2 text-right font-mono ${
                  g.net < 0 ? "text-neg" : "text-pos"
                }`}
              >
                {formatInt(g.net)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
