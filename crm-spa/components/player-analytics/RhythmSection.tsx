"use client";

import { ChartBox } from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useDow } from "@/lib/dow";
import { useSection } from "./hooks";
import { SectionShell } from "./SectionShell";
import { KGrid, StatTile } from "./ui";
import { EChart } from "./Chart";
import { dowOption, hourOption, heatmapOption, useDowLabels } from "./rhythmCharts";
import type { RhythmData } from "./types";

/**
 * 🕐 Ритм ставок — GET /players/<id>/rhythm. Day-of-week bar + hour-of-day line
 * + weekday×hour heatmap + stats, echarts styled 1:1 with the board RHYTHM_JS
 * (same palette/renderer). Data is naive Europe/Istanbul (board parity).
 *
 * Построители опций живут в ./rhythmCharts — их делит GameDetailModal (ритм
 * внутри одной игры), как борд делит один RHYTHM_JS на оба экрана.
 */
export function RhythmSection({ playerId }: { playerId: number }) {
  const t = useT();
  const section = useSection<RhythmData>(`/api/v1/players/${playerId}/rhythm`);
  const dowLabels = useDowLabels();
  const dow = useDow();

  return (
    <SectionShell
      title={t("analytics.rhythm.title")}
      caption={t("analytics.rhythm.caption")}
      section={section}
      isEmpty={(d) => d.stats.active_days === 0}
      emptyTitle={t("analytics.rhythm.empty")}
      emptyDescription={t("analytics.rhythm.emptyDesc")}
    >
      {(d) => (
        <div className="flex flex-col gap-4">
          <KGrid>
            <StatTile label={t("analytics.rhythm.activeDays")} value={formatInt(d.stats.active_days)} />
            {/* peak_day приходит русской подписью (board DOW_RU) → переводим по коду */}
            <StatTile label={t("analytics.rhythm.peakDay")} value={dow(d.stats.peak_day)} />
            <StatTile label={t("analytics.rhythm.peakHour")} value={`${d.stats.peak_hour}:00`} />
            <StatTile
              label={t("analytics.rhythm.usualInterval")}
              value={t("analytics.rhythm.intervalValue", { n: formatInt(d.stats.med_gap) })}
            />
            <StatTile
              label={t("analytics.rhythm.maxStreak")}
              value={t("analytics.rhythm.streakValue", { n: formatInt(d.stats.longest) })}
            />
            <StatTile label={t("analytics.rhythm.betsPerDay")} value={formatInt(d.stats.bpd)} />
          </KGrid>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartBox title={t("analytics.rhythm.byWeekday")} caption={t("analytics.rhythm.byWeekdayCaption")}>
              <EChart option={dowOption(d.dow, dowLabels)} height={210} />
            </ChartBox>
            <ChartBox title={t("analytics.rhythm.byHour")} caption={t("analytics.rhythm.byHourCaption")}>
              <EChart option={hourOption(d.hour)} height={210} />
            </ChartBox>
          </div>

          <ChartBox title={t("analytics.rhythm.heatmap")} caption={t("analytics.rhythm.heatmapCaption")}>
            <EChart option={heatmapOption(d.hm, dowLabels)} height={230} />
          </ChartBox>
        </div>
      )}
    </SectionShell>
  );
}
