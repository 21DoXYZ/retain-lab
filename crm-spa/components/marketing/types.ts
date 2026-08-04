/**
 * TypeScript shapes for the api/marketing.py responses (C4 domain).
 * Kept 1:1 with the JSON the Flask endpoints return.
 */

// ── /api/v1/ltv ──────────────────────────────────────────────────────────────
export interface LtvKpi {
  tot_head: number | null;
  whales: number;
  whales_head: number | null;
  young: number;
  growth_d120_d1: number | null;
}
export interface LtvCurvePoint {
  day: number;
  cohort_n: number;
  avg: number | null;
  median: number | null;
  x_d1: number;
}
export interface LtvTier {
  tier: string;
  cohort_n: number;
  exp_d30: number | null;
  exp_d90: number | null;
  exp_d120: number | null;
}
export interface YoungWhale {
  player_id: number;
  days_since_ftd: number;
  tier_provisional: boolean;
  early_tier: string;
  dep_d7: number | null;
  dep_to_date: number | null;
  pred_ltv_d90: number | null;
  ltv_headroom: number | null;
}
export interface LtvResponse {
  kpi: LtvKpi;
  curve: LtvCurvePoint[];
  tiers: LtvTier[];
  young_whales: YoungWhale[];
}

// ── /api/v1/actions ──────────────────────────────────────────────────────────
export interface VipScoreSet {
  vip_churn?: number | null;
  early_vip?: number | null;
  non_promising?: number | null;
}
export interface ActionRow {
  player_id: number;
  lifecycle: string;
  action: string;
  value_try: number | null;
  p_churn: number | null;
  p_2nd_deposit: number | null;
  when_to: string;
  dep_count: number;
  early_tier: string | null;
  pred_ltv_d90: number | null;
  net: number | null;
  offer_name: string;
  offer_terms: string;
  offer_reason: string;
  vip_scores: VipScoreSet;
}
export interface ActionsResponse {
  filter: string;
  filters: { key: string; label: string }[];
  cards: {
    save_n: number;
    save_v: number | null;
    wb_n: number;
    nudge_n: number;
    conv_n: number;
  };
  distribution: { action: string; players: number; value_try: number | null }[];
  distribution_total: number;
  rows: ActionRow[];
}

// ── /api/v1/bonus ────────────────────────────────────────────────────────────
export interface BonusResponse {
  uplift: {
    att_pp: number;
    ci_lo_pp: number;
    ci_hi_pp: number;
    retain_treated_pct: number;
    retain_control_pct: number;
    raw_pp: number;
    n_treated: number;
    n_control: number;
  };
  effectiveness: {
    bonus_type: string;
    players: number;
    bonus_events: number;
    dep_resp_14d_pct: number | null;
    retained_30d_pct: number | null;
  }[];
  recommendations: { rec_bonus: string; players: number; pct: number }[];
  rec_total: number;
}

// ── /api/v1/bonus/economics ──────────────────────────────────────────────────
// Статус доступности метрики: считается / частично / нужно событие казино /
// нет потока статусов / косвенная оценка.
export type EconStatus = "ok" | "partial" | "needs_event" | "missing" | "indirect";

export type BonusKpiKey =
  | "issued"
  | "cost"
  | "incr_deposits"
  | "ggr"
  | "ngr"
  | "roi"
  | "uplift";

export interface BonusKpiItem {
  key: BonusKpiKey;
  value: number | null;
  status: EconStatus;
  event?: string;
  // issued
  count?: number;
  uniq?: number;
  // uplift
  ci_lo?: number | null;
  ci_hi?: number | null;
  n_treated?: number;
  n_control?: number;
}

export type BonusFunnelKey =
  | "issued"
  | "activated"
  | "wagering_started"
  | "wagering_done"
  | "converted_or_expired"
  | "deposit_14d"
  | "retained_30d";

export interface BonusFunnelStage {
  stage: BonusFunnelKey;
  value: number | null;
  status: EconStatus;
  note_key?: string;
  unit?: "pct";
}

export interface BonusAbuse {
  personas: number;
  depositors: number;
  personas_depositors: number;
  share_pct: number;
  href: string;
}

export interface BonusEconomicsResponse {
  kpi: BonusKpiItem[];
  funnel: BonusFunnelStage[];
  abuse: BonusAbuse;
  filters: {
    applied: {
      from: string | null;
      to: string | null;
      type: string | null;
      campaign: string | null;
      aff: string | null;
      vip: number | null;
      windowed: boolean;
    };
    options: {
      types: string[];
      campaigns: string[];
      vip_levels: number[];
    };
  };
}

// ── /api/v1/bonuses ──────────────────────────────────────────────────────────
export interface CatalogBonus {
  id: string;
  name_ru: string;
  name_tr: string;
  kind: string;
  kind_label: string;
  icon: string;
  area: string;
  percent_label: string;
  limits: string[];
  days: string[];
  available_today: boolean;
  players: number;
  example_player: number | null;
  example_reason: string | null;
}
export interface BonusesResponse {
  kpi: {
    catalog_size: number;
    available_today: number;
    matched: number;
    total: number;
    most_common: string;
  };
  bonuses: CatalogBonus[];
}

// ── /api/v1/campaigns ────────────────────────────────────────────────────────
export interface CampaignSegment {
  key: string;
  icon: string;
  name: string;
  who: string;
  offer: string;
  count: number;
}
export interface CampaignsResponse {
  segments: CampaignSegment[];
}

// ── /api/v1/games ────────────────────────────────────────────────────────────
export interface GameSegment {
  name: string;
  game_uuid: string;
  players: number;
  provider: string | null;
  turnover: number | null;
  turnover_mn: number;
  avg_days: number | null;
}
export interface GamesResponse {
  games: GameSegment[];
}

// ── /api/v1/vip-scores ───────────────────────────────────────────────────────
export interface VipTopPlayer {
  player_id: number;
  score: number | null;
  lifecycle: string;
  vip_level: number;
  net: number | null;
  recency_days: number;
  turnover: number | null;
  dep_count: number;
  avg_bet: number | null;
}
export interface VipModel {
  available: boolean;
  label: string;
  hint: string;
  scored?: number;
  avg?: number | null;
  buckets?: { ge_50: number; ge_70: number; ge_90: number };
  top?: VipTopPlayer[];
  error?: string;
}
export interface VipScoresResponse {
  models: {
    vip_churn: VipModel;
    early_vip: VipModel;
    non_promising: VipModel;
  };
}
