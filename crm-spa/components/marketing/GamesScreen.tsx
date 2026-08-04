"use client";

import Link from "next/link";
import { PageHeader, Card } from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useFlaskData } from "./useFlaskData";
import type { GamesResponse, GameSegment } from "./types";

function GameCard({ g }: { g: GameSegment }) {
  const t = useT();
  const meta = [
    g.provider,
    t("marketing.games.turnoverLabel", { n: g.turnover_mn }),
    g.avg_days != null ? t("marketing.games.avgDaysLabel", { n: g.avg_days }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-[15px] leading-snug">🎮 {g.name}</div>
        <div className="text-[20px] font-extrabold text-primary tracking-[-0.5px] whitespace-nowrap">
          {formatInt(g.players)}
          <span className="text-[12px] font-normal text-steel"> {t("marketing.games.playersSuffix")}</span>
        </div>
      </div>
      <div className="text-[13px] text-steel leading-snug">{meta}</div>
      <div className="text-[13px] leading-snug">💡 {t("marketing.games.offerFreeSpins")}</div>
      {/* «список» → /players (не на лаунчер /). Фильтр матчит startsWith(game_uuid, …)
          (борд player_board.py:1031), поэтому шлём game=<uuid>; gname=<имя> — только
          для баннера на списке (uuid читать неудобно). */}
      <Link
        href={`/players?game=${encodeURIComponent(g.game_uuid)}&gname=${encodeURIComponent(g.name)}`}
        className="text-primary text-[13px] font-medium hover:underline mt-1"
      >
        {t("marketing.games.playersListLink")}
      </Link>
    </Card>
  );
}

function CardSkeleton() {
  return <div className="min-h-[148px] rounded-card border border-hair bg-canvas animate-pulse" />;
}

export function GamesScreen() {
  const t = useT();
  const { state, data, error, reload } = useFlaskData<GamesResponse>("/api/v1/games");
  const loading = state === "loading";

  return (
    <>
      <PageHeader
        title={<>{t("marketing.games.title")}</>}
        lead={t("marketing.games.lead")}
      />

      {state === "error" ? (
        <Card className="mt-5">
          <div className="text-neg text-[13.5px]">{error}</div>
          <button onClick={reload} className="mt-2 text-primary text-[13px] underline">
            {t("common.retry")}
          </button>
        </Card>
      ) : (
        <div className="mt-5 grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
          {loading
            ? Array.from({ length: 9 }).map((_, i) => <CardSkeleton key={i} />)
            : (data?.games ?? []).map((g) => <GameCard key={g.name} g={g} />)}
        </div>
      )}
    </>
  );
}
