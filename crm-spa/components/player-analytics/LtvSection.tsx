"use client";

import { SCard, SCardGrid, TierBadge } from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { SectionShell } from "./SectionShell";
import { KGrid } from "./ui";
import { fmtTry } from "./format";
import type { Section } from "./hooks";
import type { LtvData, LtvBlock } from "./types";

/**
 * 💎 LTV-прогноз — /players/<id>/ltv (forecast block only; the ladder is its own
 * section). Board «LTV-прогноз» kc tiles + lead (player_board.py line 1397):
 * Тир / Депозит 1-й нед / Прогноз D90 / Диапазон D90 (P10–P90) / Ещё ожидаем.
 * Non-depositors get the honest «депозитный LTV не прогнозируется». The /ltv
 * fetch is shared with LadderSection (one request, passed down as `section`).
 */
function Forecast({ ltv }: { ltv: LtvBlock }) {
  const t = useT();
  const provn = ltv.provisional ? t("analytics.ltv.provisional") : "";
  const modn = ltv.is_ml ? t("analytics.ltv.modelMl") : t("analytics.ltv.modelTier");
  const rangeNote = ltv.quantiles ? t("analytics.ltv.rangeNote") : "";

  return (
    <div className="flex flex-col gap-2">
      <KGrid>
        {/* Подсказки — board SCARD_TIP (player_board.py:1312-1316). */}
        {/* Видимая подсказка (sub) у терсных метрик — задача 6.2: определения были
            только в тултипе, лейбл голый. Оператор/аналитик не наводит мышь. */}
        <SCard label={t("analytics.ltv.tier")} value={<TierBadge tier={ltv.tier} />} sub={t("analytics.ltv.tier.sub")} title={t("card.tip.scard.tier")} />
        <SCard
          label={t("analytics.ltv.depWeek1")}
          value={fmtTry(ltv.dep_d7)}
          title={t("card.tip.scard.depWeek1")}
        />
        <SCard
          label={t("analytics.ltv.forecastD90")}
          value={fmtTry(ltv.pred_ltv_d90)}
          valueTone="pos"
          title={t("card.tip.scard.forecastD90")}
        />
        {ltv.quantiles ? (
          <SCard
            label={t("analytics.ltv.rangeD90")}
            value={
              <span className="text-[20px]">
                {formatInt(ltv.quantiles.p10)}–{formatInt(ltv.quantiles.p90)} ₺
              </span>
            }
            title={t("card.tip.scard.rangeD90")}
          />
        ) : null}
        <SCard
          label={t("analytics.ltv.headroom")}
          value={fmtTry(ltv.headroom)}
          sub={t("analytics.ltv.headroom.sub")}
          variant="cream"
          title={t("card.tip.scard.headroom")}
        />
      </KGrid>
      <div className="text-[13.5px] text-steel leading-relaxed">
        {t("analytics.ltv.daysSince", { days: formatInt(ltv.days_since_ftd) })}
        {provn} · {modn}
        {rangeNote}
      </div>
    </div>
  );
}

export function LtvSection({ section }: { section: Section<LtvData> }) {
  const t = useT();
  return (
    <SectionShell title={t("analytics.ltv.title")} caption={t("analytics.ltv.caption")} section={section}>
      {(d) =>
        d.ltv ? (
          <Forecast ltv={d.ltv} />
        ) : (
          <SCardGrid className="grid-cols-1">
            <div className="text-[13.5px] text-steel leading-relaxed">{t("analytics.ltv.noDeposit")}</div>
          </SCardGrid>
        )
      }
    </SectionShell>
  );
}
