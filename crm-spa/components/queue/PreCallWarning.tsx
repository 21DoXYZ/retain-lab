"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { formatDateShort } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { CALL_OUTCOME_KEY, type CallOutcome } from "./labels";
import type { TodayCall } from "./types";

/**
 * Soft, NON-blocking «сегодня уже звонил X» warning (ТЗ КЦ п.2.2).
 * Reused by the queue rows and (optionally) B3's player card. Two forms:
 *   <PreCallWarning touches={...} />                 — pre-resolved touches
 *   <PreCallWarningForPlayer playerId={..} ... />    — self-fetches today's calls
 * It never prevents a call; it only reminds the operator so the player is not
 * called twice in a day.
 */

function line(call: TodayCall, t: ReturnType<typeof useT>): string {
  const when = formatDateShort(call.started_at);
  const outcome = t(CALL_OUTCOME_KEY[call.outcome]);
  const who = call.operatorName ?? t("players.precall.otherOperator");
  return t("players.precall.line", { when, who, outcome });
}

export function PreCallWarning({
  touches,
  className,
}: {
  touches: TodayCall[];
  className?: string;
}) {
  const t = useT();
  if (!touches || touches.length === 0) return null;
  return (
    <div
      className={
        "flex items-start gap-2 text-[12.5px] text-[#854d0e] bg-[#fef9c3] border border-[#fde68a] rounded-ctl px-3 py-2 " +
        (className ?? "")
      }
      role="status"
    >
      <span aria-hidden className="leading-none mt-[1px]">
        🔔
      </span>
      <div className="min-w-0">
        <span className="font-semibold">{t("players.precall.header")}</span>{" "}
        {touches.map((call, i) => (
          <span key={`${call.operator_id}-${call.started_at}`}>
            {i > 0 ? "; " : ""}
            {line(call, t)}
          </span>
        ))}
        {t("players.precall.footer")}
      </div>
    </div>
  );
}

/**
 * Self-fetching variant for the player card: reads crm.calls for TODAY
 * (Europe/Istanbul) under RLS, optionally excluding the current operator and
 * mapping operator ids → names. Renders nothing until/unless a touch is found.
 */
export function PreCallWarningForPlayer({
  playerId,
  excludeOperatorId,
  operatorNames,
  className,
}: {
  playerId: number;
  excludeOperatorId?: string;
  operatorNames?: Record<string, string>;
  className?: string;
}) {
  const [touches, setTouches] = useState<TodayCall[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      const supabase = createClient();
      // Start of today in Europe/Istanbul, expressed as an absolute instant.
      const now = new Date();
      const istanbulNoonOffsetMs = 3 * 60 * 60 * 1000; // +03:00, no DST in TR
      const key = new Date(now.getTime() + istanbulNoonOffsetMs)
        .toISOString()
        .slice(0, 10);
      const startIso = new Date(`${key}T00:00:00+03:00`).toISOString();
      const { data } = await supabase
        .schema("crm")
        .from("calls")
        .select("casino_player_id, operator_id, started_at, outcome")
        .eq("casino_player_id", playerId)
        .gte("started_at", startIso)
        .order("started_at", { ascending: false });
      if (cancelled) return;
      const rows = (data ?? [])
        .filter((c) => c.operator_id !== excludeOperatorId)
        .map((c) => ({
          casino_player_id: c.casino_player_id as number,
          operator_id: c.operator_id as string,
          operatorName: operatorNames?.[c.operator_id as string] ?? null,
          started_at: c.started_at as string,
          outcome: c.outcome as CallOutcome,
        }));
      setTouches(rows);
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [playerId, excludeOperatorId, operatorNames]);

  return <PreCallWarning touches={touches} className={className} />;
}
