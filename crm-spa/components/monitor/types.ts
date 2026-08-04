/**
 * Response types for the «Монитор и справочники» JSON domain (api/monitor.py,
 * agent C6). Each interface mirrors the inner `data` object of the {ok,data}
 * envelope, i.e. what flaskFetch<T>() resolves to. Kept 1:1 with the Python
 * payloads so the SPA renders the same numbers the board does.
 *
 * Endpoints: /desk /live /report /signals (+ /signals/online) /schema
 * /formulas /glossary /keys.
 */

// ── shared ───────────────────────────────────────────────────────────────────
/** Catalog offer under a player (pb.offer_for → name / terms / why). */
export interface Offer {
  name: string;
  terms: string;
  why: string;
}

/** Status of an already-issued offer (pb.OFFER_STATUS meta). */
export interface OfferStatus {
  code: string;
  label: string;
  bg: string;
  fg: string;
}

export interface FilterOption {
  key: string;
  label: string;
}

// ── /api/v1/desk ─────────────────────────────────────────────────────────────
export interface DeskRow {
  player_id: number;
  lifecycle: string | null;
  action: string | null;
  when_to: string | null;
  value_try: number;
  p_churn: number | null;
  p_2nd_deposit: number | null;
  pred_ltv_d90: number;
  dep_count: number;
  p_next_deposit: number | null;
  early_tier: string | null;
  net: number;
  recency_days: number | null;
  recent_net: number;
  recent_spins: number;
  offer_status: OfferStatus | null;
  offer: Offer;
}

export interface DeskData {
  meta: { asof: string; act: string; w: string; window_label: string };
  /** tier — активный VIP-пресет очереди: "cd" (киты C/D) либо "" (нет). */
  filters: { act: FilterOption[]; w: FilterOption[]; tier: string };
  kpi: { n_filter: number; value_filter: number; n_queue: number; n_total: number };
  rows: DeskRow[];
}

// ── /api/v1/live ─────────────────────────────────────────────────────────────
export interface LiveRow {
  alert: boolean;
  player_id: number;
  /** ISO datetime string (board serialises datetimes to ISO). */
  last_bet: string;
  ago_seconds: number;
  cur_net: number;
  cur_spins: number;
  cur_dur: number;
  cur_game: string | null;
  lifecycle: string | null;
  action: string | null;
  p_churn: number | null;
  pred_ltv_d90: number;
  dep_count: number;
  p_next_deposit: number | null;
  offer: Offer;
}

export interface LiveData {
  meta: { window_min: number; poll_seconds: number; asof: string };
  kpi: { n_alert: number; n_now: number; shown: number };
  rows: LiveRow[];
}

// ── /api/v1/report ───────────────────────────────────────────────────────────
export interface ReportTaskRow {
  action: string;
  players: number;
  value: number;
  avg_priority: number;
}

export interface ReportTopPriority {
  player_id: number;
  lifecycle: string | null;
  action: string | null;
  value_try: number;
  p_churn: number | null;
  offer: Offer;
}

export interface ReportBonusRow {
  bonus: string;
  players: number;
  value: number;
}

export interface ReportOfferLogRow {
  player_id: number;
  status: string;
  offer_text: string;
  operator: string;
  ts: string;
}

export interface ReportData {
  kpi: {
    in_work: number;
    value_at_risk: number;
    headroom: number;
    offers_total: number;
    offers_sent: number;
    offers_rejected: number;
  };
  task_dist: ReportTaskRow[];
  top_priorities: ReportTopPriority[];
  bonus_dist: ReportBonusRow[];
  offer_log: ReportOfferLogRow[];
}

// ── /api/v1/signals (+ /signals/online) ──────────────────────────────────────
export interface SignalRow {
  player_id: number;
  pred_ltv_d90: number;
  p_churn: number | null;
  p_2nd_deposit: number | null;
  early_tier: string | null;
  action: string | null;
  bonus: string | number | null;
  priority: number;
}

export interface SignalsData {
  kpi: { total: number; whales: number; avg_priority: number; top_action: string };
  rows: SignalRow[];
}

export interface SignalsOnline {
  online: number[];
}

// ── /api/v1/schema ───────────────────────────────────────────────────────────
export interface SchemaColumn {
  name: string;
  kind: "pk" | "fk" | "col";
}

export interface SchemaTable {
  name: string;
  role: string;
  rows: number;
  /** Количество колонок таблицы (подпись «{role} · N колонок», борд :3090). */
  cols_count: number;
  columns: SchemaColumn[];
}

export interface SchemaData {
  tables: SchemaTable[];
  relations: string;
}

// ── /api/v1/formulas ─────────────────────────────────────────────────────────
export interface FormulaCell {
  code: boolean;
  text: string;
}

export interface FormulaSection {
  title: string;
  cols: string[];
  rows: FormulaCell[][];
}

export interface FormulasData {
  lead: string;
  sections: FormulaSection[];
  note: string;
}

// ── /api/v1/glossary ─────────────────────────────────────────────────────────
export interface GlossaryRow {
  term: string;
  full: string;
  plain: string;
}

export interface GlossarySection {
  title: string;
  rows: GlossaryRow[];
  banner: string | null;
}

export interface GlossaryData {
  sections: GlossarySection[];
}

// ── /api/v1/keys ─────────────────────────────────────────────────────────────
export interface KeyToken {
  key: string;
  label: string;
  is_set: boolean;
  masked: string;
  length: number;
}

export interface KeysData {
  tokens: KeyToken[];
  ips: string[];
  ingest: { url: string; example_curl: string };
  kafka_note: string;
}

/** POST /keys/regenerate — the raw token is returned exactly once. */
export interface KeyRegenerated {
  key: string;
  label: string;
  token: string;
  masked: string;
}
