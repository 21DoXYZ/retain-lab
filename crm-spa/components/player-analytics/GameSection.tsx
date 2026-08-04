"use client";

import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { SectionH2, FieldsGrid, Metric } from "./ui";
import { fmtTry, fmtRatio } from "./format";
import type { PlayerSummaryGame } from "./types";

/**
 * 🎮 Игра — board «Игра» `.fields` grid, exact field list/order/labels from
 * player_board.py def player() (line 1363). Fed by the /summary `game` slice.
 * For vip_manager the casino-P&L keys (`net`, `ggr`) are omitted → those two
 * fields render «—» (fmtTry treats undefined as null), everything else stays.
 */
export function GameSection({ game }: { game: PlayerSummaryGame }) {
  const t = useT();
  return (
    <section className="mt-6" data-section="game">
      <SectionH2>{t("analytics.section.game")}</SectionH2>
      {/* title — расшифровки полей: board CARD_TIP (player_board.py:1282-1296). */}
      <FieldsGrid>
        <Metric label={t("analytics.game.bets")} value={formatInt(game.bets)} title={t("card.tip.field.bets")} />
        <Metric label={t("analytics.game.turnover")} value={fmtTry(game.turnover)} title={t("card.tip.field.turnover")} />
        <Metric label={t("analytics.game.wins")} value={fmtTry(game.wins_sum)} title={t("card.tip.field.wins_sum")} />
        <Metric label={t("analytics.game.net")} value={fmtTry(game.net)} title={t("card.tip.field.net")} />
        <Metric label={t("analytics.game.ggr")} value={fmtTry(game.ggr)} title={t("card.tip.field.ggr")} />
        <Metric label={t("analytics.game.avgBet")} value={fmtTry(game.avg_bet)} title={t("card.tip.field.avg_bet")} />
        <Metric label={t("analytics.game.maxBet")} value={fmtTry(game.max_bet)} title={t("card.tip.field.max_bet")} />
        <Metric label={t("analytics.game.distinctGames")} value={formatInt(game.distinct_games)} title={t("card.tip.field.distinct_games")} />
        <Metric label={t("analytics.game.activeDays")} value={formatInt(game.active_days)} title={t("card.tip.field.active_days")} />
        <Metric label={t("analytics.game.recencyDays")} value={formatInt(game.recency_days)} title={t("card.tip.field.recency_days")} />
        <Metric
          label={t("analytics.game.provider")}
          value={game.primary_provider || "—"}
          title={t("card.tip.field.primary_provider")}
        />
        <Metric label={t("analytics.game.freespinRatio")} value={fmtRatio(game.freespin_ratio)} title={t("card.tip.field.freespin_ratio")} />
        <Metric label={t("analytics.game.nightShare")} value={fmtRatio(game.night_share)} title={t("card.tip.field.night_share")} />
        <Metric label={t("analytics.game.betsPerDay")} value={formatInt(game.bets_per_active_day)} title={t("card.tip.field.bets_per_active_day")} />
        <Metric
          label={t("analytics.game.activationLag")}
          value={formatInt(game.activation_lag_days)}
          title={t("card.tip.field.activation_lag_days")}
        />
      </FieldsGrid>
    </section>
  );
}
