"use client";

import { Modal, ChartBox, ErrorState, Skeleton } from "@/components/ui";
import { formatInt } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { useDow } from "@/lib/dow";
import { useSection } from "./hooks";
import { KGrid, StatTile } from "./ui";
import { EChart } from "./Chart";
import { dowOption, hourOption, heatmapOption, useDowLabels } from "./rhythmCharts";
import type { GameDetailData } from "./types";

/**
 * Детали одной игры — GET /players/<id>/game/<gid>. Паритет с HTML-роутом борда
 * `/player/<pid>/game/<gid>` (player_board.py:1602-1630): те же плитки (ставок /
 * оборот / активных дней / любимый день / любимый час), тот же ритм «когда
 * ставил в этой игре» и та же разбивка по дням с пропорциональной полосой.
 *
 * Борд открывает отдельную страницу; здесь — модалка поверх карточки: оператор
 * разбирает очередь и не должен терять контекст игрока. Содержимое то же.
 */
function DayRow({ date, bets, turnover, max, t }: {
  date: string;
  bets: number;
  turnover: number;
  max: number;
  t: ReturnType<typeof useT>;
}) {
  const bar = Math.round((bets / max) * 100);
  return (
    <div className="relative grid items-center gap-2.5 overflow-hidden rounded-ctl border border-hair bg-canvas px-[13px] py-[9px] text-[13px] grid-cols-[110px_1fr_74px_92px]">
      <span className="absolute inset-y-0 left-0 z-0 bg-primary/10" style={{ width: `${bar}%` }} aria-hidden />
      <span className="relative z-[1] font-mono text-steel">{date}</span>
      <span className="relative z-[1]" />
      <span className="relative z-[1] font-mono text-steel text-right">
        {t("analytics.gameDetail.betsShort", { n: formatInt(bets) })}
      </span>
      <span className="relative z-[1] font-mono text-steel text-right">
        {t("analytics.gameDetail.turnoverShort", { n: formatInt(turnover) })}
      </span>
    </div>
  );
}

function Body({ d, t }: { d: GameDetailData; t: ReturnType<typeof useT> }) {
  const dowLabels = useDowLabels();
  const dow = useDow();
  const max = Math.max(1, ...d.by_day.map((x) => Number(x.bets) || 0));

  return (
    <div className="flex flex-col gap-4">
      <div className="text-[13px] text-steel">
        {t("analytics.gameDetail.lead", {
          player: d.player_id,
          provider: d.provider || t("common.dash"),
        })}
      </div>

      <KGrid>
        <StatTile label={t("analytics.gameDetail.bets")} value={formatInt(d.bets)} />
        <StatTile label={t("analytics.gameDetail.turnover")} value={formatInt(d.turnover)} />
        <StatTile label={t("analytics.gameDetail.activeDays")} value={formatInt(d.active_days)} />
        {/* peak_day приходит русской подписью (board DOW_RU) → переводим по коду */}
        <StatTile label={t("analytics.rhythm.peakDay")} value={dow(d.rhythm.stats.peak_day)} />
        <StatTile label={t("analytics.rhythm.peakHour")} value={`${d.rhythm.stats.peak_hour}:00`} />
      </KGrid>

      <div className="text-[15px] font-bold text-ink">{t("analytics.gameDetail.whenTitle")}</div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartBox title={t("analytics.rhythm.byWeekday")} caption={t("analytics.rhythm.byWeekdayCaption")}>
          <EChart option={dowOption(d.rhythm.dow, dowLabels)} height={190} />
        </ChartBox>
        <ChartBox title={t("analytics.rhythm.byHour")} caption={t("analytics.rhythm.byHourCaption")}>
          <EChart option={hourOption(d.rhythm.hour)} height={190} />
        </ChartBox>
      </div>
      <ChartBox title={t("analytics.rhythm.heatmap")} caption={t("analytics.rhythm.heatmapCaption")}>
        <EChart option={heatmapOption(d.rhythm.hm, dowLabels)} height={210} />
      </ChartBox>

      <div className="text-[15px] font-bold text-ink">
        {t("analytics.gameDetail.byDayTitle")}{" "}
        <span className="text-[12px] font-normal text-steel">{t("analytics.gameDetail.byDayCaption")}</span>
      </div>
      <div className="overflow-x-auto">
        <div className="flex flex-col gap-[5px] min-w-[420px]">
          <div className={cn(
            "grid gap-2.5 px-[13px] pb-0.5 text-[10.5px] uppercase tracking-[0.5px] text-stone",
            "grid-cols-[110px_1fr_74px_92px]",
          )}>
            <span>{t("analytics.gameDetail.colDate")}</span>
            <span />
            <span className="text-right">{t("analytics.gameDetail.colBets")}</span>
            <span className="text-right">{t("analytics.gameDetail.colTurnover")}</span>
          </div>
          {d.by_day.map((x) => (
            <DayRow
              key={x.date}
              date={x.date}
              bets={Number(x.bets) || 0}
              turnover={Number(x.turnover) || 0}
              max={max}
              t={t}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function GameDetailModal({
  playerId,
  game,
  onClose,
}: {
  playerId: number;
  /** Выбранная игра (null → модалка закрыта). name — для заголовка до загрузки. */
  game: { uuid: string; name: string } | null;
  onClose: () => void;
}) {
  const t = useT();
  // Хуки нельзя звать условно → секция всегда объявлена, но enabled=false пока
  // игра не выбрана: закрытая модалка не должна ходить в сеть.
  const section = useSection<GameDetailData>(
    `/api/v1/players/${playerId}/game/${encodeURIComponent(game?.uuid ?? "")}`,
    game !== null,
  );

  return (
    <Modal
      open={game !== null}
      onClose={onClose}
      widthClass="max-w-4xl"
      title={
        <span className="flex items-baseline gap-2 flex-wrap">
          {t("analytics.gameDetail.title")}
          <em className="not-italic font-bold text-primary">{section.data?.game_name ?? game?.name}</em>
        </span>
      }
    >
      {section.state === "loading" ? (
        <Skeleton className="h-[320px]" />
      ) : section.state === "error" ? (
        <ErrorState description={section.error ?? undefined} onRetry={section.reload} />
      ) : section.data ? (
        <Body d={section.data} t={t} />
      ) : null}
    </Modal>
  );
}
