"use client";

import { SCard, SCardGrid, Banner, type ValueTone } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { useSection } from "./hooks";
import { SectionShell } from "./SectionShell";

/**
 * 💠 VIP-скоры (инхаус-линейка, аналог vip-intelligence) — GET /players/<id>/vip-intel.
 * Три модели: риск депозитного оттока VIP (30д), потенциал VIP по первой неделе
 * (Gold за 90д), перспектива роста тира (инверсия non-promising). Абсолютные
 * вероятности у этих моделей обманчивы (база churn ~0.75) — показываем
 * ПЕРЦЕНТИЛЬ по популяции модели: «рискованнее N% VIP». null = игрок не в
 * населении модели (не VIP / вершина тиров) — плитка честно говорит об этом.
 */

interface ScoreRank {
  score: number;
  pct_rank: number | null;
}

interface VipIntelData {
  player_id: number;
  vip_churn: ScoreRank | null;
  early_vip: ScoreRank | null;
  growth: ScoreRank | null;
}

function tone(rank: number | null | undefined, hotIsBad: boolean): ValueTone {
  if (rank == null) return "default";
  if (rank >= 80) return hotIsBad ? "neg" : "pos";
  if (rank <= 20) return hotIsBad ? "pos" : "default";
  return "default";
}

export function VipIntelSection({ playerId }: { playerId: number }) {
  const t = useT();
  const section = useSection<VipIntelData>(`/api/v1/players/${playerId}/vip-intel`);

  return (
    <SectionShell
      title={t("analytics.vipintel.title")}
      caption={t("analytics.vipintel.caption")}
      section={section}
      isEmpty={(d) => !d.vip_churn && !d.early_vip && !d.growth}
      emptyTitle={t("analytics.vipintel.empty")}
      emptyDescription={t("analytics.vipintel.emptyDesc")}
    >
      {(d) => (
        <>
          <SCardGrid>
            <SCard
              label={t("analytics.vipintel.churn")}
              value={d.vip_churn ? `${Math.round(d.vip_churn.score * 100)}%` : "—"}
              valueTone={tone(d.vip_churn?.pct_rank, true)}
              sub={
                d.vip_churn?.pct_rank != null
                  ? t("analytics.vipintel.churnSub", { n: d.vip_churn.pct_rank })
                  : t("analytics.vipintel.notInSegment")
              }
              title={t("analytics.vipintel.churnHint")}
            />
            <SCard
              label={t("analytics.vipintel.early")}
              value={d.early_vip ? `${Math.round(d.early_vip.score * 100)}%` : "—"}
              valueTone={tone(d.early_vip?.pct_rank, false)}
              sub={
                d.early_vip?.pct_rank != null
                  ? t("analytics.vipintel.earlySub", { n: d.early_vip.pct_rank })
                  : t("analytics.vipintel.notInSegment")
              }
              title={t("analytics.vipintel.earlyHint")}
            />
            <SCard
              label={t("analytics.vipintel.growth")}
              value={d.growth ? `${Math.round((1 - d.growth.score) * 100)}%` : "—"}
              valueTone={tone(d.growth?.pct_rank, false)}
              sub={
                d.growth?.pct_rank != null
                  ? t("analytics.vipintel.growthSub", { n: d.growth.pct_rank })
                  : t("analytics.vipintel.notInSegment")
              }
              title={t("analytics.vipintel.growthHint")}
            />
          </SCardGrid>
          <Banner className="mt-3">{t("analytics.vipintel.note")}</Banner>
        </>
      )}
    </SectionShell>
  );
}
