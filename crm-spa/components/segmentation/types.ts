/**
 * Response types for the /api/v1 segmentation endpoints (api/segmentation.py).
 * Shapes mirror the Flask envelope's `data` field exactly — one source of truth
 * with the board's numbers.
 */

// ── /cohorts ────────────────────────────────────────────────────────────────
export type CohortItemType = "bar" | "time" | "area" | "donut" | "table";

export interface CohortDatum {
  label: string;
  value: number;
}

export interface CohortItem {
  id: string;
  title: string;
  type: CohortItemType;
  /** Present for chart types (bar/time/area/donut). */
  data?: CohortDatum[];
  /** Present for `table` type: [label, value] pairs. */
  rows?: [string, number][];
}

export interface CohortGroup {
  name: string;
  items: CohortItem[];
}

export interface CohortsResponse {
  groups: CohortGroup[];
  meta: { title: string; subtitle: string; note: string; as_of: string; count: number };
}

// ── /rfm ────────────────────────────────────────────────────────────────────
export interface RfmSegment {
  seg: string;
  n: number;
  pct: number;
  avg_turn: number;
  avg_rec: number | null;
  avg_act: number | null;
  bg: string;
  fg: string;
  mean: string;
  action: string;
}

export interface RfmResponse {
  segments: RfmSegment[];
  never: RfmSegment;
  base: number;
  played: number;
  never_count: number;
  meta: { title: string; subtitle: string };
}

// ── /dist ───────────────────────────────────────────────────────────────────
export interface LtvDecile {
  decile: number;
  players: number;
  avg_ltv: number;
  sum_ltv: number;
  pct_of_value: number;
  is_whale: boolean;
}

export interface ChurnDecile {
  decile: number;
  players: number;
  avg_risk: number;
  lo: number;
  hi: number;
}

export interface Percentile {
  label: string;
  value: number;
}

export interface ChurnBreakdownRow {
  group: string;
  desc: string;
  players: number;
  note: string;
}

export interface DistResponse {
  cards: {
    top10_pct_of_value: number;
    median_deposit: number;
    p90_deposit: number;
    p99_deposit: number;
    max_deposit: number;
  };
  ltv_deciles: LtvDecile[];
  ltv_base: number;
  churn_deciles: ChurnDecile[];
  churn_base: number;
  deposit_percentiles: Percentile[];
  depositors: number;
  churn_breakdown: ChurnBreakdownRow[];
  churn_breakdown_total: number;
  meta: { title: string; subtitle: string };
}

// ── /archetypes ─────────────────────────────────────────────────────────────
export interface Archetype {
  persona: string;
  emoji: string;
  name: string;
  desc: string;
  count: number;
  pct: number;
  avg_bet: number;
  active_days: number;
  distinct_games: number;
  depositor_pct: number;
  turnover_mn: number;
}

export interface ArchetypesResponse {
  total: number;
  archetypes: Archetype[];
  meta: { title: string; subtitle: string };
}

// ── /funnel ─────────────────────────────────────────────────────────────────
export interface FunnelStage {
  name: string;
  n: number;
  pct_of_reg: number;
  step_conv: number | null;
  bar_pct: number;
}

export interface FunnelResponse {
  reg: number;
  stages: FunnelStage[];
  meta: { title: string; subtitle: string };
}
