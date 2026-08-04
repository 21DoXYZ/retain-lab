"use client";

import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSection } from "./hooks";
import { SectionShell } from "./SectionShell";
import { FieldsGrid, Metric } from "./ui";
import { fmtRatio } from "./format";
import type { PatternData } from "./types";

/**
 * 🧭 Паттерн — GET /players/<id>/pattern. Board «Паттерн» `.fields` grid, exact
 * field list/order/labels (player_board.py line 1368): основная игра / ставок в
 * ней / концентрация / 🔁 дольше возвращался / дней возврата / бросил после 1 дня.
 * Names, not hashes (board parity).
 */
export function PatternSection({ playerId }: { playerId: number }) {
  const t = useT();
  const section = useSection<PatternData>(`/api/v1/players/${playerId}/pattern`);
  return (
    <SectionShell title={t("analytics.pattern.title")} section={section} emptyTitle={t("analytics.pattern.empty")}>
      {/* title — расшифровки полей: board CARD_TIP (player_board.py:1298-1303). */}
      {(p) => (
        <FieldsGrid>
          <Metric
            label={t("analytics.pattern.favouriteGame")}
            value={p.favourite_game_name || "—"}
            title={t("card.tip.field.favourite_game")}
          />
          <Metric label={t("analytics.pattern.favouriteBets")} value={formatInt(p.favourite_game_bets)} title={t("card.tip.field.favourite_game_bets")} />
          <Metric
            label={t("analytics.pattern.concentration")}
            value={fmtRatio(p.game_concentration)}
            title={t("card.tip.field.game_concentration")}
          />
          <Metric
            label={t("analytics.pattern.stuckGame")}
            value={p.stuck_game_name || "—"}
            title={t("card.tip.field.stuck_game")}
          />
          <Metric label={t("analytics.pattern.stuckDays")} value={formatInt(p.stuck_game_days)} title={t("card.tip.field.stuck_game_days")} />
          <Metric
            label={t("analytics.pattern.oneshot")}
            value={formatInt(p.oneshot_games)}
            title={t("card.tip.field.oneshot_games")}
          />
        </FieldsGrid>
      )}
    </SectionShell>
  );
}
