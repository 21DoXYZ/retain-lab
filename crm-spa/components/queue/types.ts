/**
 * Shared types for the operator queue (/queue) and the assignment pool (/pool).
 * Mirrors crm.* columns (supabase/migrations/0001) plus the Flask queue
 * priorities payload (GET /api/v1/queue/priorities — api/core.py).
 */

import type { AssignStatus, CallOutcome, SchedStatus } from "./labels";

/** A row of crm.player_directory (light sync from ClickHouse). */
export interface DirectoryInfo {
  casino_player_id: number;
  display_id: string | null;
  affiliate_code: string | null;
  country: string | null;
  vip_level: number | null;
  lifecycle: string | null;
  is_valid: boolean;
}

/**
 * One item from GET /api/v1/queue/priorities (player_actions). Drives queue
 * sorting (priority DESC) and the action / bonus / when hints per row.
 * NOTE: player_actions has no "beats casino" (🎯) column yet — see QueueRow.
 */
export interface PriorityInfo {
  player_id: number;
  priority: number | null;
  action: string | null;
  bonus: string | null;
  when_to: string | null;
  value_try: number | null;
  p_churn: number | null;
  p_2nd_deposit: number | null;
  lifecycle: string | null;
}

/** A call made today (for the soft "сегодня уже звонил X" pre-call warning). */
export interface TodayCall {
  casino_player_id: number;
  operator_id: string;
  operatorName: string | null;
  started_at: string;
  outcome: CallOutcome;
}

/** The nearest overdue/today plan for a player in the current operator's day. */
export interface ScheduledInfo {
  id: string;
  scheduled_at: string;
  comment: string | null;
  status: SchedStatus;
  by_system: boolean;
  /** True when scheduled_at is in the past (просрочено — сверху очереди). */
  overdue: boolean;
  /** True when scheduled_at falls on today (Europe/Istanbul). */
  today: boolean;
}

/** A fully-enriched queue row for the operator's /queue screen. */
export interface QueueRow {
  assignmentId: string;
  playerId: number;
  status: AssignStatus;
  directory: DirectoryInfo | null;
  priority: PriorityInfo | null;
  /** Last touch (call/note) — assignment.last_touch_at, else latest call/note. */
  lastTouchAt: string | null;
  hasNotes: boolean;
  notesCount: number;
  /**
   * 🎯 «обыгрывает казино». player_actions/queue-priorities does not expose this
   * flag yet — reserved so the UI is ready once A3 adds `beats_casino` to the
   * queue priorities payload. Currently always false.
   */
  beatsCasino: boolean;
  /** Names of other operators who also have this player («также у: …»). */
  coAssignees: string[];
  /** Nearest overdue/today plan for this player (this operator). */
  scheduled: ScheduledInfo | null;
  /** Calls made TODAY by other operators (soft warning source). */
  todayTouchesByOthers: TodayCall[];
}

/** Data bundle handed from the server /queue page to the client board. */
export interface OperatorQueueData {
  rows: QueueRow[];
  /** Plan-of-day counters for the header (today / overdue). */
  plannedToday: number;
  overdue: number;
  /** True when the Flask priorities enrichment failed (queue still usable). */
  prioritiesDegraded: boolean;
}

/** A selectable operator for the assignment pool. */
export interface OperatorOption {
  id: string;
  full_name: string;
  department: string | null;
}

/** A pool row: a player visible to a head, with current assignees + priority. */
export interface PoolRow {
  playerId: number;
  directory: DirectoryInfo;
  priority: PriorityInfo | null;
  /** Operators this player is currently assigned to (id + name). */
  assignees: { id: string; name: string }[];
}

/** Data bundle handed from the server /pool page to the client board. */
export interface PoolData {
  rows: PoolRow[];
  operators: OperatorOption[];
  prioritiesDegraded: boolean;
}
