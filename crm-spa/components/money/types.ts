/**
 * Response types for the money/revenue JSON domain (api/money.py, agent C1).
 * Mirrors the {ok,data} envelope payloads for /overview, /ggr, /analytics#cash
 * and /audit. flaskFetch<T>() returns the inner `data` object typed as below.
 */

export interface Delta {
  pct: number;
  tone: "pos" | "neg";
}

// ── /api/v1/money/overview ───────────────────────────────────────────────────
export interface OverviewData {
  period: { from: string; to: string };
  players: {
    total: number;
    played: number;
    depositors: number;
    active30: number;
    active7: number;
    active_period: number;
    new30: number;
    played_pct: number;
    depositors_pct: number;
    snapshot: boolean;
  };
  cash: {
    deposits: number;
    withdrawals: number;
    net_cash: number;
    margin: number;
    wd_dep_ratio: number;   // Д3: выводы/депозиты, %
    bonus_cost: number;
    bonus_ratio: number;
  };
  geo: {
    country: string;
    deposits: number;
    withdrawals: number;
    net_cash: number;
    wd_dep_ratio: number;
    depositors: number;
  }[];
  game: { ggr: number; rtp: number; bets: number; wins: number; hold: number };
  ngr: {
    ngr: number;
    provider_cost: number;
    affiliate_commission: number;
    bonus_usage: number;
    provider_resolved: boolean;
  };
  risk: {
    manual_withdrawals: number;
    vip_at_risk: number;
    dep_rejected: number;
    winners: number;
  };
  series: { dep: number[]; wd: number[]; ggr: number[]; mau: number[] };
  compare: OverviewCompare | null;   // сравнение периодов (0.2), null если не запрошено
  asof: string | null;
}

/** Один дельта-показатель периода: абсолют + процент (pct=null, если базы 0). */
export interface PeriodDelta {
  abs: number;
  pct: number | null;
}

/** Блок сравнения: метрики периода-сравнения + дельты к основному. */
export interface OverviewCompare {
  period: { from: string; to: string };
  cash: OverviewData["cash"];
  game: OverviewData["game"];
  ngr: OverviewData["ngr"];
  delta: {
    cash: Partial<Record<keyof OverviewData["cash"], PeriodDelta>>;
    game: Partial<Record<keyof OverviewData["game"], PeriodDelta>>;
    ngr: Partial<Record<keyof OverviewData["ngr"], PeriodDelta>>;
  };
}

// ── /api/v1/ggr ──────────────────────────────────────────────────────────────
export interface GgrKpi {
  bet: number;
  win: number;
  rounds: number;
  active: number;
  ggr: number;
  rtp: number;
  avg_bet: number;
  bonus: number;
  pcost: number;
  affc: number;
  ngr: number;
  bratio: number;
}

export interface GgrDashboardTab {
  daily: { d: string; label: string; g: number }[];
  neg_days: number;
  high_rtp: { provider: string; rtp: number }[];
  signals: { kind: string; title: string; text: string }[];
  bratio: number;
}
export interface GgrProviderRow {
  name: string;
  bet: number;
  win: number;
  ggr: number;
  rtp: number;
  players: number;
  rounds: number;
}
export interface GgrRatesRow {
  provider: string;
  engr: number;
  infra: number;
  revshare: number;
  fixed_fee: number;
  min_guarantee: number;
  period: string;
}
export interface GgrSegmentsTab {
  vip: {
    level: number;
    label: string;
    players: number;
    deposits: number;
    active: number;
    bet: number;
    ggr: number;
  }[];
  behavioral: { label: string; hint: string; players: number; bet: number; ggr: number }[];
  risk_abuse: number;
}
export interface GgrBonusTab {
  rows: { type: string; events: number; players: number; cost: number; pct: number }[];
  total_cost: number;
  bratio: number;
}
export interface GgrSettleTab {
  waterfall: { label: string; value: number; pct: number; note: string }[];
  affiliates: { code: string; net: number; rate: number; commission: number }[];
}
export interface GgrReportsTab {
  rows: { d: string; bet: number; win: number; ggr: number; active: number; rounds: number }[];
  totals: { bet: number; win: number; ggr: number; rounds: number };
  from: string;
  to: string;
}

export type GgrTabData =
  | GgrDashboardTab
  | { rows: GgrProviderRow[] }
  | { rows: GgrRatesRow[] }
  | GgrSegmentsTab
  | GgrBonusTab
  | GgrSettleTab
  | GgrReportsTab;

export interface GgrData {
  filters: {
    from: string;
    to: string;
    provider: string;
    country: string;
    aff: string;
    limit: number;
    tab: string;
  };
  tabs: { key: string; label: string }[];
  kpi: GgrKpi;
  kpi_prev: GgrKpi;
  deltas: Record<string, Delta | null>;
  provider_options: string[];
  country_options: string[];
  tab_data: GgrTabData;
}

// ── /api/v1/money/cash (analytics) ───────────────────────────────────────────
export interface CashData {
  life: { label: string; value: number }[];
  ret: { w: string; v: number }[];
  rfm: { seg: string; players: number }[];
  cf: { m: string; dep: number; wd: number }[];
  days: { label: string; value: number }[];
}

// ── /api/v1/audit ────────────────────────────────────────────────────────────
export interface AuditData {
  kpi: {
    total: number;
    count: number;
    reviewers: number;
    biggest: number;
    admin_accounts: number;
  };
  reviewers: {
    reviewed_by: string;
    is_admin: boolean;
    count: number;
    sum: number;
    unclear_pct: number;
  }[];
  categories: { cat: string; sum: number }[];
  top: {
    player_id: number;
    account_type: string;
    amount: number;
    date: string;
    reviewed_by: string;
    deposited: number;
    no_deposit_flag: boolean;
  }[];
  monthly: { m: string; v: number }[];
  no_deposit: {
    count: number;
    total: number;
    rows: {
      player_id: number;
      account_type: string;
      withdrawn: number;
      deposited: number;
      ops: number;
    }[];
  };
  test_ops: {
    count: number;
    total: number;
    rows: { player_id: number; account_type: string; sum: number; ops: number }[];
  };
}

// ── /api/v1/audit/reviewer/<rid> — «Оператор списаний» (reviewer() борда) ──────
export interface ReviewerData {
  rid: string;
  is_admin: boolean;
  kpi: {
    count: number;
    sum: number;
    biggest: number;
    players: number;
    no_deposit_count: number;
    no_deposit_sum: number;
  };
  period: { from: string; to: string };
  monthly: { m: string; v: number }[];
  categories: { cat: string; sum: number }[];
  top: {
    player_id: number;
    account_type: string;
    amount: number;
    deposited: number;
    date: string;
    no_deposit_flag: boolean;
  }[];
}
