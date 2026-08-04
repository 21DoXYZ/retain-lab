"use client";

import { Panel, DataTable, type Column } from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSection } from "./hooks";
import { Collapsible } from "./Collapsible";
import { SectionBody } from "./SectionShell";
import { fmtNaiveDateTimeShort, fmtTry } from "./format";
import type { SessionsData, SessionItem } from "./types";

/**
 * 🕐 Лог сессий — GET /players/<id>/sessions. Collapsible (default closed, board
 * `<details class="sec coll">`). Reconstructed sessions (когда / игра / длит. /
 * спинов / ставка / выигрыш / net / итог, board srows line 1415). The momentum
 * read («последняя форма» / ctx) now lives at the top of the card in the
 * RecommendationStrip, matching the board (act_sec ctxline, player_board.py:1529).
 */

export function SessionsSection({ playerId }: { playerId: number }) {
  const t = useT();
  const section = useSection<SessionsData>(`/api/v1/players/${playerId}/sessions`);
  const count = section.data?.count ?? null;

  const COLS: Column<SessionItem>[] = [
    { key: "when", header: t("analytics.sessions.colWhen"), mono: true, render: (s) => fmtNaiveDateTimeShort(s.started_at) },
    {
      key: "game",
      header: t("analytics.sessions.colGame"),
      align: "left",
      render: (s) => <span title={s.game_name}>{s.game_name}</span>,
    },
    {
      key: "dur",
      header: t("analytics.sessions.colDuration"),
      mono: true,
      render: (s) => t("analytics.sessions.durationValue", { n: formatInt(s.duration_min) }),
    },
    { key: "spins", header: t("analytics.sessions.colSpins"), mono: true, render: (s) => formatInt(s.spins) },
    { key: "bet", header: t("analytics.sessions.colBet"), mono: true, render: (s) => fmtTry(s.bet) },
    { key: "win", header: t("analytics.sessions.colWin"), mono: true, render: (s) => fmtTry(s.win) },
    {
      key: "net",
      header: t("analytics.sessions.colNet"),
      mono: true,
      render: (s) => <span className={(s.net ?? 0) >= 0 ? "text-pos" : "text-neg"}>{fmtTry(s.net)}</span>,
    },
    { key: "res", header: t("analytics.sessions.colResult"), render: (s) => ((s.net ?? 0) >= 0 ? "🟢" : "🔴") },
  ];

  return (
    <Collapsible
      title={t("analytics.sessions.title")}
      count={count}
      caption={t("analytics.sessions.caption")}
    >
      <SectionBody
        section={section}
        isEmpty={(d) => d.sessions.length === 0}
        emptyTitle={t("analytics.sessions.empty")}
        emptyDescription={t("analytics.sessions.emptyDesc")}
      >
        {(d) => (
          <Panel>
            <DataTable columns={COLS} rows={d.sessions} getRowKey={(s, i) => `${s.started_at}-${i}`} state="data" />
          </Panel>
        )}
      </SectionBody>
    </Collapsible>
  );
}
