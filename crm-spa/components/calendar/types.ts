/**
 * Shared shapes for the calendar aggregate views (B4). Creation of a scheduled
 * call lives in the player card (B3) — these views only READ crm.scheduled_calls
 * / crm.player_assignments (under RLS) and render the operator day plan, the
 * heatmap auto-plan suggestions, and the head-of-department summary.
 */

/** Light player info joined from crm.player_directory. */
export interface PlayerLite {
  casino_player_id: number;
  display_id: string | null;
  lifecycle: string | null;
  vip_level: number | null;
  country: string | null;
}

/** One row of an operator's day plan (today + overdue). */
export interface DayPlanRow {
  id: string;
  casino_player_id: number;
  scheduled_at: string; // ISO
  comment: string | null;
  by_system: boolean;
  /** Past-day touch (pinned on top with an "overdue" mark). */
  overdue: boolean;
  player: PlayerLite | null;
}

/** Assigned player with NO scheduled touch — auto-plan suggests a slot. */
export interface AutoPlanCandidate {
  casino_player_id: number;
  player: PlayerLite | null;
}

/** Per-operator discipline counters for the head-of-department summary. */
export interface OperatorSummary {
  operator_id: string;
  name: string;
  department: string | null;
  planned: number;
  done: number;
  overdue: number;
  total: number;
}
