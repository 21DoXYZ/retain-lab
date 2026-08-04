"use client";

import { Panel, DataTable, type Column } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { useSection } from "./hooks";
import { Collapsible } from "./Collapsible";
import { SectionBody } from "./SectionShell";
import { fmtTry } from "./format";

/**
 * 💳 Депозиты — GET /players/<id>/deposits. Collapsible (default closed, board
 * `<details class="sec coll">`). Columns 1:1 with the board dep_sec table
 * (player_board.py line 1462): когда · сумма ₺ · способ/комментарий · тип · статус
 * (ручной = бонус, не кэш). Same SQL as the HTML card → parity by construction.
 */
interface DepositRow {
  ts: string;
  amount: number | null;
  how: string;
  kind: string;
  status: string;
  completed: boolean;
  ts_raw: string;
}
interface DepositsData {
  player_id: number;
  count: number;
  deposits: DepositRow[];
}

export function DepositsSection({ playerId }: { playerId: number }) {
  const t = useT();
  const section = useSection<DepositsData>(`/api/v1/players/${playerId}/deposits`);

  const COLS: Column<DepositRow>[] = [
    { key: "ts", header: t("analytics.deposits.colWhen"), mono: true, render: (d) => d.ts },
    { key: "amt", header: t("analytics.deposits.colAmount"), mono: true, render: (d) => fmtTry(d.amount) },
    { key: "how", header: t("analytics.deposits.colMethod"), align: "left", render: (d) => d.how },
    { key: "kind", header: t("analytics.deposits.colType"), render: (d) => <span className="text-steel">{d.kind}</span> },
    {
      key: "status",
      header: t("analytics.deposits.colStatus"),
      render: (d) => <span className={d.completed ? "text-pos" : "text-neg"}>{d.status}</span>,
    },
    {
      // мост в «Макс-баланс за период» (режим А): окно от этого депозита
      key: "maxbal",
      header: "",
      align: "right",
      render: (d) =>
        d.completed ? (
          <button
            type="button"
            title={t("analytics.deposits.toMaxbal")}
            className="text-primary hover:underline cursor-pointer text-[13px]"
            onClick={() => window.dispatchEvent(new CustomEvent("maxbal:deposit", { detail: d.ts_raw }))}
          >
            💹
          </button>
        ) : null,
    },
  ];

  return (
    <Collapsible
      title={t("analytics.deposits.title")}
      count={section.data?.count ?? null}
      caption={t("analytics.deposits.caption")}
    >
      <SectionBody
        section={section}
        isEmpty={(d) => d.deposits.length === 0}
        emptyTitle={t("analytics.deposits.empty")}
      >
        {(d) => (
          <Panel>
            <DataTable
              columns={COLS}
              rows={d.deposits}
              getRowKey={(r, i) => `${r.ts}-${i}`}
              state="data"
            />
          </Panel>
        )}
      </SectionBody>
    </Collapsible>
  );
}
