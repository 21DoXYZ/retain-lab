/**
 * TS types for the C2 «player analytics» API responses (api/players_analytics.py
 * + the money/game slices of core's /players/<id>/summary). Numbers may be null
 * (ClickHouse NULLs are cleaned to null by the Flask envelope). Kept local to
 * this module — the SPA-wide domain types live in lib/types.ts.
 */

export type Num = number | null;

/* ── list (/api/v1/players) ─────────────────────────────────────────────── */
export interface PlayerListItem {
  player_id: number;
  lifecycle: string | null;
  is_depositor: boolean;
  bets: Num;
  turnover: Num;
  net: Num;
  recency_days: Num;
  dep_count: Num;
  dep_sum: Num;
  bonus_sum: Num;
  distinct_games: Num;
  churned_30d: boolean;
  account_type: string | null;
  net_cash: Num;
  beats_casino: boolean;
  exported_at: string | null;
}

export interface PlayerListFilters {
  q: string;
  life: string;
  dep: string;
  at: string;
  seg: string;
  game: string;
  aff: string;
  exp: string;
  vip: string;
}

export interface PlayerListResponse {
  items: PlayerListItem[];
  total: number;
  page: number;
  per_page: number;
  has_next: boolean;
  sort: string;
  dir: "asc" | "desc";
  filters: PlayerListFilters;
  sorts: string[];
}

/* ── /summary (core A3) — money + game slices used by C2 sections ────────── */
export interface PlayerSummaryMoney {
  cash_deposits: Num;
  withdrawals_abs: Num;
  net_cash: Num;
  bonus_cost: Num;
  dep_sum: Num;
  dep_count: Num;
  dep_failed: Num;
  wd_count: Num;
  wd_sum: Num;
  wd_rejected: Num;
  bonus_count: Num;
  bonus_sum: Num;
  primary_payment_method: string | null;
  deposit_recency_days: Num;
}

export interface PlayerSummaryGame {
  bets: Num;
  turnover: Num;
  wins_sum: Num;
  /** Casino P&L — ABSENT (key omitted) for vip_manager (_restrict_summary_by_role). */
  net?: Num;
  /** Casino P&L — ABSENT (key omitted) for vip_manager (_restrict_summary_by_role). */
  ggr?: Num;
  avg_bet: Num;
  max_bet: Num;
  distinct_games: Num;
  active_days: Num;
  recency_days: Num;
  primary_provider: string | null;
  favourite_game: string | null;
  favourite_game_name: string | null;
  favourite_game_bets: Num;
  game_concentration: Num;
  freespin_ratio: Num;
  night_share: Num;
  bets_per_active_day: Num;
  activation_lag_days: Num;
}

/* ── /summary profile slice (👤 Профиль section) ─────────────────────────── */
export interface PlayerSummaryProfile {
  account_type: string | null;
  status: string | null;
  country: string | null;
  reg_date: string | null;
  tenure_days: Num;
  affiliate_type: string | null;
  affiliate_code: string | null;
  /** Money — absent (undefined) in safe_profile for restricted roles. */
  ftd_amount?: Num;
  phone_verified: boolean | null;
  email_verified: boolean | null;
  /** Money snapshot — absent for restricted roles. */
  balance?: Num;
  bonus_balance?: Num;
  activity_status: string | null;
  is_depositor: boolean | null;
}

export interface PlayerSummary {
  player_id: number;
  stage?: string | null;
  vip_level?: number | null;
  vip_label?: string | null;
  /** ABSENT for operator/support/affiliate (казино-деньги не отдаются урезанным ролям). */
  money?: PlayerSummaryMoney;
  /** ABSENT for operator/support/affiliate; present-but-без-ggr/net для vip_manager. */
  game?: PlayerSummaryGame;
  /** safe_profile для урезанных ролей (без денежных полей), полный — для прочих. */
  profile?: PlayerSummaryProfile;
}

/* ── /pattern ───────────────────────────────────────────────────────────── */
export interface PatternData {
  player_id: number;
  favourite_game: string | null;
  favourite_game_name: string | null;
  favourite_game_bets: Num;
  game_concentration: Num;
  stuck_game: string | null;
  stuck_game_name: string | null;
  stuck_game_days: Num;
  oneshot_games: Num;
}

/* ── /games (trajectory) ────────────────────────────────────────────────── */
export interface GameJourneyItem {
  first_played: string | null;
  game_uuid: string;
  provider: string | null;
  bets: Num;
  days_played: Num;
  game_name: string;
  is_favourite: boolean;
}

export interface GamesData {
  player_id: number;
  count: number;
  favourite_game: string | null;
  favourite_game_name: string | null;
  games: GameJourneyItem[];
}

/* ── /sessions ──────────────────────────────────────────────────────────── */
export interface SessionItem {
  game_name: string;
  started_at: string;
  duration_min: Num;
  spins: Num;
  bet: Num;
  win: Num;
  net: Num;
}

export interface SessionsData {
  player_id: number;
  count: number;
  sessions: SessionItem[];
  momentum: { recent_net_14d: number; loss_streak: number };
}

/* ── /rhythm & game-detail rhythm ───────────────────────────────────────── */
export interface RhythmStats {
  active_days: number;
  med_gap: number;
  longest: number;
  bpd: number;
  peak_day: string;
  peak_hour: number;
}

export interface RhythmData {
  player_id: number;
  dow: number[];
  hour: number[];
  hm: [number, number, number][]; // [hour, dowIndex, count]
  stats: RhythmStats;
}

/* ── /ltv ───────────────────────────────────────────────────────────────── */
export interface LtvQuantiles {
  p10: Num;
  p50: Num;
  p90: Num;
}

export interface LtvBlock {
  days_since_ftd: Num;
  provisional: boolean;
  tier: string | null;
  dep_d7: Num;
  pred_ltv_d30: Num;
  pred_ltv_d90: Num;
  pred_ltv_d120: Num;
  headroom: Num;
  is_ml: boolean;
  quantiles: LtvQuantiles | null;
}

export interface LadderStep {
  deposit_no: number;
  conv_pct: Num;
}

export interface LadderBlock {
  current: number;
  target: number;
  p_next_personal: Num;
  p_next_base: Num;
  steps: LadderStep[];
}

export interface LtvData {
  player_id: number;
  is_depositor: boolean;
  ltv: LtvBlock | null;
  ladder: LadderBlock | null;
}

/* ── /game/<gid> (detail) ───────────────────────────────────────────────── */
export interface GameDayItem {
  date: string;
  bets: Num;
  turnover: Num;
}

export interface GameDetailData {
  player_id: number;
  game_uuid: string;
  game_name: string;
  provider: string | null;
  total_txns: Num;
  bets: Num;
  turnover: Num;
  active_days: Num;
  rhythm: { dow: number[]; hour: number[]; hm: [number, number, number][]; stats: RhythmStats };
  by_day: GameDayItem[];
}
