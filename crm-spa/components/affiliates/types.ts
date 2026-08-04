/**
 * Response types for the internal affiliates JSON domain (api/affiliates.py, C5).
 * Mirrors the {ok,data} envelope payloads returned by:
 *   GET /api/v1/affiliates             → AffiliatesListData
 *   GET /api/v1/affiliates/<code>      → AffiliateDetailData
 *   GET /api/v1/exports                → ExportsJournalData
 *   GET /api/v1/exports/detail?exp&seg → ExportsDetailData
 * flaskFetch<T>() returns the inner `data` object typed as below.
 *
 * NOTE: this is the INTERNAL admin traffic module (/affiliates, plural). Not to
 * be confused with the external affiliate cabinet (/affiliate, singular, B4).
 */

/** Verdict of a source, as the board badges it (api/affiliates._status). */
export type AffiliateStatus = "loss" | "risk" | "cash_drain" | "profit";

// ── GET /api/v1/affiliates ───────────────────────────────────────────────────
export interface AffiliateRow {
  code: string;
  players: number;
  ftd: number;
  ftd_sum: number;
  dep: number;
  wd: number;
  net_profit: number;
  turn: number;
  ggr: number;
  ggr_real: number;
  ngr: number;
  hold: number;
  /** Commission = max(net_profit,0) × rate% — by THIS affiliate's rate. */
  commission: number;
  /** Commission rate (%) of this affiliate. */
  rate: number;
  players_win: boolean;
  cash_drain: boolean;
  status: AffiliateStatus;
}

export interface AffiliatesTotals {
  affiliates: number;
  players: number;
  ftd: number;
  players_win: number;
  cash_drain: number;
  risk: number;
}

export interface AffiliatesListData {
  rows: AffiliateRow[];
  totals: AffiliatesTotals;
  sort: string;
  dir: "asc" | "desc";
  asof: string | null;
  /** Окно дат списка (0-слепок → период): границы данных + флаг фильтра. */
  window?: { from: string; to: string; filtered: boolean; dmin: string; dmax: string };
}

/** Sortable numeric columns of the overview (api/affiliates AFF_OV_SORTS). */
export type AffiliateSortKey =
  | "players"
  | "ftd"
  | "ftd_sum"
  | "dep"
  | "wd"
  | "net_profit"
  | "turn"
  | "ggr"
  | "ggr_real"
  | "ngr"
  | "hold"
  | "commission";

// ── GET /api/v1/affiliates/<code> ────────────────────────────────────────────
export interface AffiliateReconciliation {
  registrations: number;
  conversion: number;
  ftd: number;
  ftd_rate: number;
  avg_ftd: number;
  last_ftd: string | null;
  deposits_approved: number;
  deposits_count: number;
  withdrawals_approved: number;
  withdrawals_count: number;
  withdrawals_rejected: number;
  bonus_cost: number;
  bonus_ratio: number;
  net_profit: number;
  commission: number;
  commission_rate: number;
  active_players: number;
}

export interface AffiliateGame {
  turnover: number;
  real_bets: number;
  fs_bets: number;
  ggr: number;
  hold: number;
  ggr_real: number;
  hold_real: number;
  ggr_fs: number;
  ngr: number;
  manual_withdrawals: number;
  manual_deposits: number;
  ftd_sum: number;
}

export interface TopGame {
  game: string;
  provider: string;
  players: number;
  bets: number;
  turnover: number;
  net: number;
}

/** [label, value] pair used by the distribution charts. */
export type LabelValue = [string, number];
/** [month, deposits, withdrawals] triple used by the money-flow chart. */
export type MonthMoney = [string, number, number];

export interface AffiliateCharts {
  regs: LabelValue[];
  money: MonthMoney[];
  life: LabelValue[];
  prov: LabelValue[];
  top_games: TopGame[];
  pays: LabelValue[];
}

export interface DetailPlayer {
  casino_player_id: number;
  lifecycle: string | null;
  country: string | null;
  reg_date: string | null;
  ftd_amount: number;
  dep: number;
  dep_cnt: number;
  wd: number;
  wd_cnt: number;
  net_cash: number;
  turnover: number;
  net: number;
  provider: string | null;
  recency_days: number | null;
}

/** Sortable columns of the detail player table (api/affiliates _P_SORTS). */
export type PlayerSortKey =
  | "casino_player_id"
  | "reg_date"
  | "ftd_amount"
  | "dep_cnt"
  | "dep"
  | "wd_cnt"
  | "wd"
  | "net_cash"
  | "turnover"
  | "net"
  | "recency_days";

export interface DetailPlayersBlock {
  rows: DetailPlayer[];
  total: number;
  page: number;
  page_size: number;
  sort: PlayerSortKey;
  dir: "asc" | "desc";
}

export interface AffiliateDetailData {
  code: string;
  affiliate_type: string | null;
  window: {
    from: string;
    to: string;
    filtered: boolean;
    dmin: string;
    dmax: string;
  };
  status_filter: "normal" | "all";
  breakdown: { normal: number; test: number; blocked: number; all: number };
  total_players: number;
  reconciliation: AffiliateReconciliation;
  game: AffiliateGame;
  verdict: AffiliateStatus;
  funnel: { registrations: number; ftd: number; active: number };
  charts: AffiliateCharts;
  players: DetailPlayersBlock;
  asof: string | null;
}

// ── GET /api/v1/exports ──────────────────────────────────────────────────────
export interface ExportRow {
  ets: string;
  disp: string;
  segment: string;
  players: number;
  deposited: number;
  deposited_pct: number;
  bonus_given: number;
  returned: number;
  dep_no_play: number;
  is_demo: boolean;
  dep_try: number;
  wd_try: number;
  net: number;
}

export interface ExportsTotals {
  exports: number;
  players: number;
  deposited: number;
  dep_try: number;
  wd_try: number;
  net: number;
}

export interface ExportsJournalData {
  rows: ExportRow[];
  totals: ExportsTotals;
}

// ── GET /api/v1/exports/detail ───────────────────────────────────────────────
export type ExportResult = "deposit" | "returned" | "bonus" | "none";

export interface ExportPlayer {
  player_id: number;
  rec_bonus: string | null;
  dep_n: number;
  dep_sum: number;
  dep_first: string | null;
  bonus_n: number;
  bonus_first: string | null;
  bets_after: number;
  wd_sum: number;
  net: number;
  not_played: boolean;
  result: ExportResult;
}

export interface ExportsDetailData {
  segment: string;
  disp: string;
  exp: string;
  summary: {
    total: number;
    deposited: number;
    bonus: number;
    returned: number;
    dep_no_play: number;
    dep_try: number;
    wd_try: number;
    net: number;
  };
  rows: ExportPlayer[];
}
