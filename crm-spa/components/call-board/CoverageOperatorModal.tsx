"use client";

import { useEffect, useState } from "react";
import { Modal, DataTable, SkeletonText, ErrorState, type Column } from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { formatInt } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import type { CoverageOperatorDetail, CoveragePlayerRow } from "./types";

/**
 * Дриллдаун по оператору (вопрос заказчика): «кому дозвонился, кому нет, кому
 * назначил следующий звонок». По каждому назначенному игроку — попытки,
 * дозвонился ли, последний исход, когда назначен перезвон. GET
 * /coverage/operator/<id>. Роли — как у экрана покрытия.
 */
const CALL_OUTCOME_KEY: Record<string, MessageKey> = {
  answered: "card.outcome.answered",
  no_answer: "card.outcome.noAnswer",
  busy: "card.outcome.busy",
  wrong_number: "card.outcome.wrongNumber",
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 16).replace("T", " ");
}

export function CoverageOperatorModal({
  operatorId,
  operatorName,
  onClose,
}: {
  operatorId: string | null;
  operatorName: string | null;
  onClose: () => void;
}) {
  const t = useT();
  const [data, setData] = useState<CoverageOperatorDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!operatorId) return;
    setData(null);
    setErr(null);
    let alive = true;
    flaskFetch<CoverageOperatorDetail>(`/api/v1/call-analysis/coverage/operator/${operatorId}`)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(flaskErrorText(e, t, "callsboard.common.loadFailed")));
    return () => {
      alive = false;
    };
  }, [operatorId, t]);

  const cols: Column<CoveragePlayerRow>[] = [
    { key: "pid", header: t("callsboard.coverageOp.col.player"), id: true, render: (r) => String(r.casino_player_id) },
    {
      key: "att",
      header: t("callsboard.coverageOp.col.attempts"),
      mono: true,
      render: (r) => (r.attempts === 0 ? <span className="text-neg font-medium">0</span> : formatInt(r.attempts)),
    },
    {
      key: "last",
      header: t("callsboard.coverageOp.col.lastOutcome"),
      align: "left",
      render: (r) =>
        r.last_outcome
          ? t(CALL_OUTCOME_KEY[r.last_outcome] ?? "card.outcome.noAnswer")
          : t("callsboard.coverageOp.notCalled"),
    },
    { key: "lastat", header: t("callsboard.coverageOp.col.lastAt"), mono: true, render: (r) => fmtDate(r.last_at) },
    {
      key: "next",
      header: t("callsboard.coverageOp.col.nextCall"),
      mono: true,
      render: (r) =>
        r.next_at ? <span className="text-primary">{fmtDate(r.next_at)}</span> : <span className="text-stone">—</span>,
    },
  ];

  return (
    <Modal
      open={operatorId !== null}
      onClose={onClose}
      widthClass="max-w-3xl"
      title={
        <span className="flex items-baseline gap-2">
          {t("callsboard.coverageOp.title")}
          <span className="text-[13px] font-normal text-steel">{operatorName ?? operatorId?.slice(0, 8)}</span>
        </span>
      }
    >
      {err ? (
        <ErrorState description={err} />
      ) : !data ? (
        <SkeletonText lines={8} />
      ) : (
        <>
          <p className="mb-3 text-[12.5px] text-steel">{t("callsboard.coverageOp.hint")}</p>
          <DataTable
            columns={cols}
            rows={data.players}
            getRowKey={(r) => String(r.casino_player_id)}
            getRowHref={(r) => `/players/${r.casino_player_id}`}
            state={data.players.length ? "data" : "empty"}
            emptyTitle={t("callsboard.coverageOp.empty")}
          />
        </>
      )}
    </Modal>
  );
}
