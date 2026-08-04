/**
 * Types for the player card (B3 zone). Two data sources meet here:
 *   1. Analytics/profile — Flask JSON API (A3): GET /api/v1/players/:id/summary,
 *      /heatmap. Read-only, ClickHouse-backed, PII masked by role in the API.
 *   2. Operational rows — Supabase crm.* (A1 schema, RLS): notes / calls /
 *      scheduled_calls / player_assignments. Written directly from the browser
 *      (RLS is the hard boundary; see components/player-card/data.ts).
 *
 * We type only the fields the card actually renders; unknown extra keys from the
 * API are tolerated. Enum string unions mirror the Postgres enums in
 * supabase/migrations/0001_crm_schema.sql — keep them in sync.
 */

// ---------------------------------------------------------------------------
// Flask summary (subset of api/core.py player_summary)
// ---------------------------------------------------------------------------

/**
 * Решение отдела по офферу. Зеркалит OFFER_STATUSES в api/core.py и
 * player_board.OFFER_STATUS — храним КОД, подпись переводится на фронте.
 */
export type OfferStatusCode = "approved" | "edited" | "rejected" | "sent";

export interface PlayerSummary {
  player_id: number;
  stage: string | null;
  vip_level: number | null;
  vip_label: string | null;
  /** 🎯 "beats the casino" — cashed out more than deposited AND net game win. */
  beats_casino: boolean;
  profile: {
    account_type: string | null;
    status: string | null;
    country: string | null;
    reg_date: string | null;
    tenure_days: number | null;
    affiliate_type: string | null;
    affiliate_code: string | null;
    ftd_amount: number | null;
    balance: number | null;
    bonus_balance: number | null;
    activity_status: string | null;
    is_depositor: boolean;
  };
  contact: {
    /** Masked by role in the API (operator → "+90•••••1234"). */
    phone: string | null;
    phone_country_code: string | null;
    email: string | null;
    phone_verified: unknown;
    email_verified: unknown;
  };
  recommendation: {
    action: string | null;
    bonus: string | null;
    when_to: string | null;
    offer_name: string | null;
    offer_terms: string | null;
    offer_reason: string | null;
    /**
     * Последнее решение отдела из retention.player_offers — тот же источник, что
     * у старого борда (он пишет туда через POST /offer/<pid>). offer_saved_text
     * заполнен → показываем ЕГО вместо подобранного offer_name (борд: cur_offer
     * = ot_ if os_ else suggested). Код статуса стабилен, подпись переводим.
     */
    offer_status: OfferStatusCode | null;
    offer_saved_text: string | null;
    offer_saved_note: string | null;
    /** Дата последнего решения отдела (дд.мм.гггг) — для подписи в блоке. */
    offer_saved_at?: string | null;
  };
  /**
   * Casino money/game/scores — present only for money-authorised roles
   * (operator/support/affiliate get them stripped by _restrict_summary_by_role
   * in api/core.py). All optional; the card hides KPIs that are absent.
   */
  game?: {
    bets: number | null;
    turnover: number | null;
    net: number | null;
    ggr: number | null;
    recency_days: number | null;
  } | null;
  money?: {
    dep_count: number | null;
  } | null;
  scores?: {
    p_churn: number | null;
    p_2nd_deposit: number | null;
  } | null;
  meta: { role: string | null; pii: "full" | "masked" | "none" };
}

// ---------------------------------------------------------------------------
// Flask heatmap (api/core.py player_heatmap → pb._rhythm)
// ---------------------------------------------------------------------------

export interface PlayerHeatmap {
  player_id: number;
  heatmap: {
    /** counts by day-of-week, index 0 = Monday … 6 = Sunday. */
    dow: number[];
    /** counts by hour 0..23. */
    hour: number[];
    /** cells [hour, dowIndex(0=Mon), count]. */
    hm: [number, number, number][];
  };
  stats: {
    active_days: number;
    med_gap: number;
    longest: number;
    bpd: number;
    /** Russian weekday name of the busiest day (display only). */
    peak_day: string;
    peak_hour: number;
  };
}

// ---------------------------------------------------------------------------
// crm.* operational rows (Supabase, RLS)
// ---------------------------------------------------------------------------

/** crm.call_outcome enum. */
export type CallOutcome = "answered" | "no_answer" | "busy" | "wrong_number";
/** crm.call_result enum. */
export type CallResult = "interested" | "offer_declined" | "callback_requested" | "refused";
/** crm.sched_status enum. */
export type SchedStatus = "planned" | "done" | "overdue" | "missed";
/** crm.assign_status enum. */
export type AssignStatus =
  | "not_touched"
  | "no_answer"
  | "answered"
  | "agreed"
  | "refused"
  | "returned";

export interface NoteRow {
  id: string;
  casino_player_id: number;
  author_id: string;
  content: string;
  tags: string[];
  linked_offer: string | null;
  created_at: string;
  updated_at: string;
}

export interface CallRow {
  id: string;
  casino_player_id: number;
  operator_id: string;
  started_at: string;
  duration_sec: number | null;
  outcome: CallOutcome;
  result: CallResult | null;
  provider_ref: string | null;
  recording_ref: string | null;
  created_at: string;
}

export interface ScheduledRow {
  id: string;
  casino_player_id: number;
  operator_id: string;
  scheduled_at: string;
  comment: string | null;
  status: SchedStatus;
  by_system: boolean;
  created_at: string;
  updated_at: string;
}

export interface AssignmentRow {
  id: string;
  casino_player_id: number;
  operator_id: string;
  status: AssignStatus;
  last_touch_at: string | null;
}

/** The four screen states required by every card block (plan §0.6). */
export type LoadState = "loading" | "error" | "empty" | "data";
