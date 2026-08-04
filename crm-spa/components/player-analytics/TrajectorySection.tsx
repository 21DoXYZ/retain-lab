"use client";

import { useState } from "react";
import { formatInt } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { useSection } from "./hooks";
import { Collapsible } from "./Collapsible";
import { SectionBody } from "./SectionShell";
import { GameDetailModal } from "./GameDetailModal";
import { fmtNaiveDate } from "./format";
import type { GamesData, GameJourneyItem } from "./types";

/**
 * 🗺 Траектория игр — GET /players/<id>/games. Collapsible (default closed).
 * Board `.journey`/`.jrow` layout 1:1 (player_board.py jrow_html line 1370): a
 * proportional bet-bar behind each row, ★ favourite pinned on top with the
 * `.stuck` accent, then the full trajectory in order of first contact. Columns:
 * первая ставка / игра / провайдер / ставок / дней. Names, not hashes.
 */
const COLS = "grid-cols-[96px_minmax(140px,200px)_1fr_74px_62px]";

function Row({
  g,
  maxBets,
  pinned,
  onOpen,
  t,
}: {
  g: GameJourneyItem;
  maxBets: number;
  pinned?: boolean;
  onOpen: (g: GameJourneyItem) => void;
  t: ReturnType<typeof useT>;
}) {
  const bar = Math.round(((Number(g.bets) || 0) / maxBets) * 100);
  return (
    // Клик открывает детали игры — паритет с бордом (player_board.py:1371:
    // onclick → /player/<pid>/game/<gid>, cursor:pointer, тот же тултип).
    // button, а не div с onClick: нужны клавиатура и фокус.
    <button
      type="button"
      onClick={() => onOpen(g)}
      title={t("analytics.trajectory.openDetail")}
      className={cn(
        "relative grid w-full items-center gap-2.5 overflow-hidden rounded-ctl border px-[13px] py-[9px] text-left text-[13px]",
        "cursor-pointer transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-primary",
        COLS,
        pinned ? "border-primary bg-cream" : "border-hair bg-canvas",
      )}
    >
      <span className="absolute inset-y-0 left-0 z-0 bg-primary/10" style={{ width: `${bar}%` }} aria-hidden />
      <span className="relative z-[1] font-mono text-steel truncate">
        {pinned || g.is_favourite ? "★ " : ""}
        {fmtNaiveDate(g.first_played)}
      </span>
      <span className="relative z-[1] text-primary truncate" title={g.game_name}>
        {g.game_name}
      </span>
      <span className="relative z-[1] text-steel truncate">{g.provider || "—"}</span>
      <span className="relative z-[1] font-mono text-steel text-right">
        {t("analytics.trajectory.betsShort", { n: formatInt(g.bets) })}
      </span>
      <span className="relative z-[1] font-mono text-steel text-right">
        {t("analytics.trajectory.daysShort", { n: formatInt(g.days_played) })}
      </span>
    </button>
  );
}

function Journey({
  data,
  onOpen,
  t,
}: {
  data: GamesData;
  onOpen: (g: GameJourneyItem) => void;
  t: ReturnType<typeof useT>;
}) {
  const maxBets = Math.max(1, ...data.games.map((g) => Number(g.bets) || 0));
  const fav = data.games.find((g) => g.is_favourite);

  return (
    <div className="overflow-x-auto">
      <div className="flex flex-col gap-[5px] min-w-[560px]">
        {fav ? (
          <>
            <div className="text-[12px] font-semibold text-steel">{t("analytics.trajectory.favouriteNote")}</div>
            <Row g={fav} maxBets={maxBets} pinned onOpen={onOpen} t={t} />
            <div className="text-[12px] text-steel mt-2">{t("analytics.trajectory.restNote")}</div>
          </>
        ) : null}
        <div className={cn("grid gap-2.5 px-[13px] pb-0.5 text-[10.5px] uppercase tracking-[0.5px] text-stone", COLS)}>
          <span>{t("analytics.trajectory.colFirstBet")}</span>
          <span>{t("analytics.trajectory.colGame")}</span>
          <span>{t("analytics.trajectory.colProvider")}</span>
          <span className="text-right">{t("analytics.trajectory.colBets")}</span>
          <span className="text-right">{t("analytics.trajectory.colDays")}</span>
        </div>
        {data.games.map((g, i) => (
          <Row key={`${g.game_uuid}-${i}`} g={g} maxBets={maxBets} onOpen={onOpen} t={t} />
        ))}
      </div>
    </div>
  );
}

export function TrajectorySection({ playerId }: { playerId: number }) {
  const t = useT();
  const section = useSection<GamesData>(`/api/v1/players/${playerId}/games`);
  const count = section.data?.count ?? null;
  const [game, setGame] = useState<{ uuid: string; name: string } | null>(null);

  return (
    <>
      <Collapsible
        title={t("analytics.trajectory.title")}
        count={count}
        caption={t("analytics.trajectory.caption")}
      >
        <SectionBody
          section={section}
          isEmpty={(d) => d.games.length === 0}
          emptyTitle={t("analytics.trajectory.empty")}
          emptyDescription={t("analytics.trajectory.emptyDesc")}
        >
          {(d) => (
            <Journey
              data={d}
              onOpen={(g) => setGame({ uuid: g.game_uuid, name: g.game_name })}
              t={t}
            />
          )}
        </SectionBody>
      </Collapsible>
      <GameDetailModal playerId={playerId} game={game} onClose={() => setGame(null)} />
    </>
  );
}
