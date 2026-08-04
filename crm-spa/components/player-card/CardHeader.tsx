"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { LifecycleBadge, VipBadge, BeatsCasinoBadge } from "@/components/ui";
import { useT } from "@/lib/i18n";
import type { PlayerSummary } from "./types";

/**
 * Card header (ТЗ / plan §6) — 1:1 with the board card top (player_board.py
 * def player): id, badges, then the 6-KPI row (Ставок · Оборот ₺ · Net ₺ ·
 * GGR ₺ · Депозитов · Recency). The KPI row appears only for money-authorised
 * roles (summary.game is stripped for operator/support/affiliate by the API).
 */
interface CardHeaderProps {
  playerId: number;
  summary: PlayerSummary | null;
  /** e.g. "также у: Ayşe, Can" — other operators with this player in queue. */
  alsoWith?: string[];
}

/** Integer with space-grouped thousands — matches the board f() formatter. */
function f(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("ru-RU");
}

// Board `.scard` + `kc()` KPI tile: tall (min-height 128px), 26px value, hairline.
// `title` = native hover tooltip (board SCARD_TIP data-tip, player_board.py:1389).
function Kpi({ label, value, tone, title }: { label: string; value: ReactNode; tone?: "pos" | "neg"; title?: string }) {
  const color = tone === "neg" ? "text-neg" : tone === "pos" ? "text-pos" : "text-ink";
  return (
    <div title={title} className="bg-canvas border border-hair rounded-card px-5 py-[18px] min-h-[128px]">
      <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel">{label}</div>
      <div className={`font-extrabold text-[26px] leading-[1.05] mt-[9px] tracking-[-1px] ${color}`}>
        {value}
      </div>
    </div>
  );
}

export function CardHeader({ playerId, summary, alsoWith }: CardHeaderProps) {
  const t = useT();
  const stage = summary?.stage ?? null;
  const vip = summary?.vip_level ?? null;
  const country = summary?.profile?.country ?? null;
  const g = summary?.game ?? null;
  const depCount = summary?.money?.dep_count ?? null;
  const recency = g?.recency_days;
  const net = g?.net ?? null;
  const ggr = g?.ggr ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="font-extrabold text-[28px] tracking-[-0.6px] text-ink">
              {t("card.header.playerLabel")} <span className="font-mono text-primary">#{playerId}</span>
            </h1>
            {summary?.beats_casino ? <BeatsCasinoBadge /> : null}
          </div>
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            {stage ? <LifecycleBadge stage={stage} /> : null}
            {vip != null ? <VipBadge level={vip} /> : null}
            {summary?.vip_label ? (
              <span className="text-[12.5px] text-steel">{summary.vip_label}</span>
            ) : null}
            {country ? <span className="text-[12.5px] text-steel">· {country}</span> : null}
            {summary?.profile?.is_depositor === false ? (
              <span className="text-[12.5px] text-stone">{t("card.header.noDeposit")}</span>
            ) : null}
          </div>
          {alsoWith && alsoWith.length > 0 ? (
            <div className="mt-2 text-[12.5px] text-steel">
              {t("card.header.alsoWith")} <b className="text-slate">{alsoWith.join(", ")}</b>
            </div>
          ) : null}
        </div>

        <Link
          href="/players"
          className="text-[13px] text-steel hover:text-primary transition-colors whitespace-nowrap"
        >
          {t("card.header.backToList")}
        </Link>
      </div>

      {/* KPI row — board `.kgrid` (repeat(auto-fit,minmax(150px,1fr)), gap 14) */}
      {g ? (
        <div className="grid gap-[14px] grid-cols-[repeat(auto-fit,minmax(150px,1fr))]">
          <Kpi label={t("card.header.kpi.bets")} value={f(g.bets)} title={t("card.tip.scard.bets")} />
          <Kpi label={t("card.header.kpi.turnover")} value={f(g.turnover)} title={t("card.tip.scard.turnover")} />
          <Kpi
            label={t("card.header.kpi.net")}
            value={f(net)}
            tone={net != null && net < 0 ? "neg" : "pos"}
            title={t("card.tip.scard.net")}
          />
          <Kpi
            label={t("card.header.kpi.ggr")}
            value={f(ggr)}
            tone={ggr != null && ggr >= 0 ? "pos" : "neg"}
            title={t("card.tip.scard.ggr")}
          />
          <Kpi label={t("card.header.kpi.deposits")} value={f(depCount)} title={t("card.tip.scard.deposits")} />
          <Kpi
            label={t("card.header.kpi.recency")}
            value={recency == null ? "—" : t("card.header.daysShort", { n: f(recency) })}
            title={t("card.tip.scard.recency")}
          />
        </div>
      ) : null}
    </div>
  );
}
