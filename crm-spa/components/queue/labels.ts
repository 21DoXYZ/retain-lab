/**
 * Label + colour maps for the operator queue / assignment pool (B2).
 * Pure module (no client/server imports) — safe on both sides. Colours follow
 * the same inline bg/fg convention as components/ui/badges.ts so the touch
 * status / call outcome pills read 1:1 with the live dashboard palette.
 *
 * Text is i18n keys (labelKey), not literal strings — the pure data-layer
 * modules cannot call useT(); the client renderers (QueueBoard, PoolBoard,
 * PreCallWarning) resolve the key at render time. See lib/i18n/README.md.
 */

import type { MessageKey } from "@/lib/i18n";

/** crm.assign_status — «по кому звонили» (ТЗ КЦ п.2.6). */
export type AssignStatus =
  | "not_touched"
  | "no_answer"
  | "answered"
  | "agreed"
  | "refused"
  | "returned";

/** crm.call_outcome — исход звонка (2 клика, ТЗ КЦ п.3.2). */
export type CallOutcome = "answered" | "no_answer" | "busy" | "wrong_number";

/** crm.call_result — результат разговора. */
export type CallResult =
  | "interested"
  | "offer_declined"
  | "callback_requested"
  | "refused";

/** crm.sched_status — план дня. */
export type SchedStatus = "planned" | "done" | "overdue" | "missed";

export interface AssignTone {
  bg: string;
  fg: string;
  /** i18n key for the pill text (players.queue.status.*). */
  labelKey: MessageKey;
}

/** Touch status → badge tone + i18n key (не тронут / дозвонились / недозвон / …). */
export const ASSIGN_STATUS: Record<AssignStatus, AssignTone> = {
  not_touched: { bg: "#f2f4f7", fg: "#667085", labelKey: "players.queue.status.not_touched" },
  answered: { bg: "#dde9ff", fg: "#1e40af", labelKey: "players.queue.status.answered" },
  no_answer: { bg: "#fef9c3", fg: "#854d0e", labelKey: "players.queue.status.no_answer" },
  agreed: { bg: "#dcfce7", fg: "#166534", labelKey: "players.queue.status.agreed" },
  refused: { bg: "#fee2e2", fg: "#991b1b", labelKey: "players.queue.status.refused" },
  returned: { bg: "#e0e7ff", fg: "#4338ca", labelKey: "players.queue.status.returned" },
};

/** bg/fg for an unrecognised status; no label text (dash — not translatable copy). */
export const ASSIGN_STATUS_FALLBACK: { bg: string; fg: string } = {
  bg: "#f2f4f7",
  fg: "#667085",
};

/** Call outcome → i18n key (players.precall.outcome.*) — «сегодня звонил X — недозвон». */
export const CALL_OUTCOME_KEY: Record<CallOutcome, MessageKey> = {
  answered: "players.precall.outcome.answered",
  no_answer: "players.precall.outcome.no_answer",
  busy: "players.precall.outcome.busy",
  wrong_number: "players.precall.outcome.wrong_number",
};

/** Call result → i18n key. Same crm.call_result enum as player-card's
 * CallResult (access.ts RESULT_LABELS) — reuses the "card.result.*" copy so
 * the two never drift. */
export const CALL_RESULT_KEY: Record<CallResult, MessageKey> = {
  interested: "card.result.interested",
  offer_declined: "card.result.offerDeclined",
  callback_requested: "card.result.callbackRequested",
  refused: "card.result.refused",
};

/** Resolve a touch-status tone, tolerating unknown values from the DB. */
export function assignStatusTone(status: string | null | undefined): { bg: string; fg: string } {
  if (status && status in ASSIGN_STATUS) {
    const { bg, fg } = ASSIGN_STATUS[status as AssignStatus];
    return { bg, fg };
  }
  return ASSIGN_STATUS_FALLBACK;
}
