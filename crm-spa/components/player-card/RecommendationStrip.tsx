"use client";

import type { ReactNode } from "react";
import { ActionBadge } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { useSection } from "@/components/player-analytics/hooks";
import type { SessionsData } from "@/components/player-analytics/types";
import type { PlayerSummary } from "./types";

/**
 * «🎯 Рекомендованное действие» — 1:1 с бордом (player_board.py act_sec):
 * 5 высоких плиток `.scard` (Действие / Реком. бонус+термины / Когда / Риск ухода
 * 30д / P(2-й деп, 30д)) + строка-примечание + баннер (offer_reason). Скоры
 * риск-ухода/2-го депа приходят только money-ролям (иначе «—»).
 */
function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

/** Цвет риска ухода — как в борде: ≥0.7 красный, ≥0.4 янтарный, иначе зелёный. */
function riskColor(v: number | null | undefined): string | undefined {
  if (v == null || Number.isNaN(v)) return undefined;
  return v >= 0.7 ? "#b91c1c" : v >= 0.4 ? "#b45309" : "#166534";
}

/** Высокая плитка `.scard` с произвольным значением. `title` — нативный тултип. */
function Tile({ label, value, sub, title }: { label: string; value: ReactNode; sub?: ReactNode; title?: string }) {
  return (
    <div title={title} className="bg-canvas border border-hair rounded-card px-5 py-[18px] min-h-[128px] min-w-0">
      <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel">{label}</div>
      <div className="mt-[9px]">{value}</div>
      {sub ? <div className="text-[11.5px] text-steel mt-1.5 leading-snug">{sub}</div> : null}
    </div>
  );
}

/** Баннер ctx-моментума (board `<div class=banner>`, player_board.py:1529/1539). */
function MomentumBanner({ text }: { text: string }) {
  const t = useT();
  return (
    <div className="bg-cream border border-beige border-l-[3px] border-l-primary rounded-card px-[18px] py-[15px] text-[13.5px] leading-relaxed text-slate">
      {/* ярлык: это ТЕКУЩЕЕ состояние игрока (динамика последних сессий), а не правило движка */}
      <div className="text-[11px] uppercase tracking-[0.5px] text-steel mb-1">
        {t("card.momentum.liveLabel")}
      </div>
      {text}
    </div>
  );
}

/**
 * ctx-моментум — «последняя форма» (board player_board.py:1435-1438). Мёртвая
 * зона ±avg_bet*20: recent_net в её пределах → «ровно»; ниже (или серия ≥3
 * проигрышей) → «в минусе»; выше → «на волне». Возвращает готовый текст или null
 * (board: `if not srows: ctx=''`). `avgBet` NaN/None → 0 (board ab, :1433-1434).
 */
function momentumText(
  t: ReturnType<typeof useT>,
  sessions: SessionsData | null,
  avgBet: number,
): string | null {
  if (!sessions || sessions.count <= 0) return null;
  const ab = Number.isFinite(avgBet) ? avgBet : 0;
  const rn = sessions.momentum.recent_net_14d;
  if (sessions.momentum.loss_streak >= 3 || rn < -ab * 20) return t("card.momentum.down");
  if (rn > ab * 20) return t("card.momentum.up");
  return t("card.momentum.flat");
}

export function RecommendationStrip({ summary }: { summary: PlayerSummary | null }) {
  const t = useT();
  // ctx-моментум берётся из /sessions (recent_net_14d / loss_streak) — тот же
  // источник, что у SessionsSection; борд считает ctx из тех же srows (:1425).
  const sessions = useSection<SessionsData>(
    `/api/v1/players/${summary?.player_id ?? 0}/sessions`,
    summary != null,
  );

  const rec = summary?.recommendation;
  if (!rec) return null;

  // avg_bet есть в /summary.game (api/core.py:673), но не типизирован на уровне
  // карточки — читаем расширенной формой; null/undefined → 0 (board ab, :1433).
  const avgBet = (summary?.game as { avg_bet?: number | null } | null | undefined)?.avg_bet ?? 0;
  const ctx = momentumText(t, sessions.data, avgBet);

  const hasOffer = rec.offer_name && rec.offer_name !== "—";
  const hasRec = Boolean(rec.action || hasOffer || rec.bonus);

  // Борд рисует ctx даже без строки в player_actions → «🎯 Контекст по игре» (:1540).
  if (!hasRec) {
    if (!ctx) return null;
    return (
      <div className="flex flex-col gap-3">
        <h2 className="font-bold text-[20px] leading-tight text-ink">{t("card.momentum.contextTitle")}</h2>
        <MomentumBanner text={ctx} />
      </div>
    );
  }

  const sc = summary?.scores ?? null;
  const offer = hasOffer ? rec.offer_name : rec.bonus;
  const big = "font-extrabold text-[26px] leading-[1.05] tracking-[-1px]";

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-bold text-[20px] leading-tight text-ink flex items-baseline gap-2 flex-wrap">
        {t("card.recommendation.title")}
        <span className="text-[13px] text-steel font-normal">{t("card.recommendation.subtitle")}</span>
      </h2>

      <div className="grid gap-[14px] grid-cols-[repeat(auto-fit,minmax(150px,1fr))]">
        <Tile
          label={t("card.recommendation.action")}
          value={rec.action ? <ActionBadge action={rec.action} /> : <span className="text-steel text-[15px]">—</span>}
        />
        <Tile
          label={t("card.recommendation.bonus")}
          value={<span className="text-[15px] leading-snug font-bold text-ink block">{offer ?? "—"}</span>}
          sub={rec.offer_terms}
        />
        <Tile
          label={t("card.recommendation.when")}
          value={<span className="text-[15px] leading-snug font-semibold text-ink">{rec.when_to ?? "—"}</span>}
        />
        <Tile
          label={t("card.recommendation.churnRisk")}
          value={<span className={big} style={{ color: riskColor(sc?.p_churn) }}>{pct(sc?.p_churn)}</span>}
        />
        <Tile
          label={t("card.recommendation.secondDepositProb")}
          value={<span className={`${big} text-ink`}>{pct(sc?.p_2nd_deposit)}</span>}
        />
      </div>

      <div className="text-[12px] text-stone">
        {t("card.recommendation.priorityNote")}
      </div>

      {rec.offer_reason ? (
        <div className="bg-cream border border-beige border-l-[3px] border-l-primary rounded-card px-[18px] py-[15px] text-[13.5px] leading-relaxed text-slate">
          {rec.offer_reason}
        </div>
      ) : null}

      {/* ctx-моментум внизу блока рекомендации — board ctxline (player_board.py:1537). */}
      {ctx ? <MomentumBanner text={ctx} /> : null}
    </div>
  );
}
