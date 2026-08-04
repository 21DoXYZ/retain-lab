/**
 * API response types for the «Анализ звонков» management screens (domain
 * "callsboard"). Mirrors api/call_analysis.py response shapes 1:1 — the single
 * TS source of truth for what flaskFetch returns for these endpoints. Data
 * shapes from call_analyzer_dev_spec.md §4 (words/dimensions/tips).
 */

export interface Period {
  from: string;
  to: string;
}

/** Weak criterion (worst per-period average) — §10.1 «Слабое место». */
export interface WeakSpot {
  criterion: string;
  avg: number;
}

// ── Overview (§10.1) ────────────────────────────────────────────────────────
export interface OverviewOperator {
  operator_id: string;
  operator_name: string | null;
  connected: number;
  analyzed: number;
  avg_score: number | null;
  trend: number | null;
  weak_spot: WeakSpot | null;
  never_called: number;
}

export interface ScoreDrop {
  operator_id: string;
  operator_name: string | null;
  from: number;
  to: number;
}

export interface OverviewData {
  period: Period;
  verdict_unlocked: boolean;
  reconciliation: { checked: number; agreement: number | null };
  totals: { connected: number; analyzed: number; never_called: number };
  needs_action: {
    never_called: number;
    queue_needs_review: number;
    cards_pending_approve: number;
    score_drops: ScoreDrop[];
    disputed_cards: number;
    manual_review: number;
    failed_records: number;
  };
  operators: OverviewOperator[];
}

// ── Operator report (§10.5) ─────────────────────────────────────────────────
export interface WeeklyPoint {
  week: string;
  avg_score: number | null;
  n: number;
}

export interface CriterionRow {
  criterion: string;
  avg: number;
  delta: number | null;
}

export interface WorstCall {
  call_id: string;
  score: number | null;
  offer_outcome: string | null;
  duration_s: number | null;
  at: string;
}

export interface ScriptChange {
  version: number;
  activated_at: string;
}

export interface OperatorReportData {
  operator_id: string;
  operator_name: string | null;
  period: Period;
  weekly: WeeklyPoint[];
  criteria: CriterionRow[];
  worst_calls: WorstCall[];
  script_changes: ScriptChange[];
}

// ── Coverage (§10.7) ────────────────────────────────────────────────────────
export interface CoverageOperator {
  operator_id: string;
  operator_name: string | null;
  assigned: number;
  attempts: number;
  connected: number;
  talks: number;
  never_called: number;
  in_review: number;
  scheduled: number;              // назначено перезвонов на будущее (pending)
}

/** Дриллдаун по оператору: строка на игрока — «кому дозвонился, кому нет,
 *  кому назначен следующий звонок». */
export interface CoveragePlayerRow {
  casino_player_id: number;
  attempts: number;
  answered: number;
  last_outcome: string | null;
  last_at: string | null;
  next_at: string | null;
}

export interface CoverageOperatorDetail {
  operator_id: string;
  operator_name: string | null;
  players: CoveragePlayerRow[];
}

export interface CoverageData {
  period: Period;
  totals: {
    assigned: number;
    attempts: number;
    connected: number;
    talks: number;
    never_called: number;
    in_review: number;
  };
  operators: CoverageOperator[];
}

// ── What works (§10.6) ──────────────────────────────────────────────────────
export interface RankingRow {
  operator_id: string;
  operator_name: string | null;
  presented: number;
  accepted: number;
  accept_rate: number | null;
}

export interface StepExample {
  call_id: string;
  score: number;
  evidence_ts: string | null;
  quote_tr: string;
  quote_translation: string | null;
}

export interface BestOperator {
  operator_id: string;
  operator_name: string | null;
  examples: StepExample[];
}

export interface Step {
  criterion: string;
  enough_data: boolean;
  talks: number;
  team_coverage?: number | null;
  best_operator?: BestOperator | null;
}

export interface WhatWorksData {
  period: Period;
  ranking: RankingRow[];
  steps: Step[];
}

// ── Summary (§10.12) ────────────────────────────────────────────────────────
export interface DialingFacts {
  assigned: number;
  attempts: number;
  connected: number;
  talks: number;
  never_called: number;
}

/** Неделя фактов обзвона (динамика в сводке — данные звонилки, не модели). */
export interface WeeklyFacts {
  week: string;
  attempts: number;
  connected: number;
  talks: number;
}

export interface SummaryData {
  period: Period;
  verdict_unlocked: boolean;
  facts: DialingFacts;
  prev_facts: DialingFacts;
  analyzed: number;
  compliance_pct: number | null;
  needs_review: number;
  weekly: WeeklyFacts[];
  scheduled_upcoming: number;
  avg_score?: number | null;
  avg_score_trend?: number | null;
}

// ── My calls (§10.10) ───────────────────────────────────────────────────────
export interface CoachingTip {
  ts: string;
  text: string;
}

export interface CoachingCard {
  card_id: string;
  call_id: string;
  tips: CoachingTip[];
  approved_at: string | null;
  op_response: string | null;
  responded_at: string | null;
  player_id: string | number | null;
  created_at: string;
}

export interface RecentCall {
  call_id: string;
  player_id: string | number | null;
  duration_s: number | null;
  at: string;
  score: number | null;
}

export interface MyScore {
  avg: number | null;
  trend: number | null;
  weak_spot: WeakSpot | null;
}

export interface MyCardsData {
  verdict_unlocked: boolean;
  cards: CoachingCard[];
  recent_calls: RecentCall[];
  score?: MyScore;
}

// ── Script (§10.8 / §10.9) ──────────────────────────────────────────────────
export type CheckLevel = "verbatim" | "meaning" | "none";
export type Importance = "critical" | "normal" | "minor";

export interface ScriptBlock {
  text?: string | null;
  title?: string | null;
  criterion?: string | null;
  check_level?: CheckLevel | null;
  importance?: Importance | null;
  word_forms?: string[] | null;
  within_words?: number | null;
  legal_proposed?: boolean | null;
  weight_pct?: number | null;
}

export interface ScriptVersion {
  script_id: string;
  version: number | null;
  status: string;
  blocks: ScriptBlock[];
  activated_at: string | null;
  created_at: string;
}

/** Бизнес-исходы по версии скрипта: сравнивать версии по результату (принятые
 *  офферы, деп ≤7д после звонка), НЕ по баллу — линейки версий разные (§10.5).
 *  group_name=null → вариант «скрипт казино по умолчанию»; иначе — имя группы.
 *  Колонка «Вариант» = A/B-сравнение исходов между группами (§8/§10.8). */
export interface ScriptVersionStats {
  /** Имя именованного скрипта версии (0011); null у легаси-версий. */
  script_name?: string | null;
  version: number;
  status: string;
  group_id: string | null;
  group_name: string | null;
  activated_at: string | null;
  analyzed: number;
  presented: number;
  accepted: number;
  accept_rate: number | null;
  dep7d: number | null;
  play7d: number | null;
  dep_median_min: number | null;
  avg_score: number | null;
}

export interface ScriptData {
  active: ScriptVersion | null;
  draft?: ScriptVersion | null;
  versions_stats?: ScriptVersionStats[];
  /** Какой именованный скрипт открыт (0011): ref + имя. */
  script_ref?: string | null;
  script_name?: string | null;
  /** Легаси (§8, до 0011): id группы из query. */
  group_id?: string | null;
}

// ── Именованные скрипты (0011) ───────────────────────────────────────────────
/** Строка реестра скриптов: имя, версия в бою, черновик, назначения. */
export interface ScriptInfo {
  script_ref: string;
  name: string;
  active_version: number | null;
  has_draft: boolean;
  is_default: boolean;
  groups: string[];
  created_at: string | null;
}

export interface ScriptsData {
  scripts: ScriptInfo[];
  default_ref: string | null;
}

// ── A/B-группы скрипта (§8 / §10.8) ─────────────────────────────────────────
/** Оператор в контексте групп: назначаемый/назначенный участник. */
export interface ScriptGroupOperator {
  operator_id: string;
  name: string | null;
  department: string | null;
}

/** Группа операторов со своим активным скриптом (вариант A/B/C…). */
export interface ScriptGroup {
  group_id: string;
  /** Назначенный группе скрипт (0011): null → наследует дефолт казино. */
  script_ref?: string | null;
  script_name?: string | null;
  name: string;
  created_at: string;
  members: number;
  active_version: number | null;
  members_list: ScriptGroupOperator[];
}

/** Ответ GET /script/groups: группы + операторы вне групп (казино-дефолт). */
export interface ScriptGroupsData {
  groups: ScriptGroup[];
  ungrouped: ScriptGroupOperator[];
}

export interface DryRunCall {
  call_id: string;
  current: number | null;
  draft: number | null;
  delta: number | null;
}

export interface DryRunData {
  avg_current: number | null;
  avg_draft: number | null;
  sample_size: number;
  calls: DryRunCall[];
  persisted: boolean;
}

// ── Verdict & weights (§10.13) ──────────────────────────────────────────────
/** Неделя сверки: сколько проверено (counted) и % согласия — сходится ли модель. */
export interface AgreementWeek {
  week: string;
  checked: number;
  agreement: number | null;
}

/** Последняя правка руководителя с причиной — где модель ошиблась и почему. */
export interface Disagreement {
  at: string;
  reason: string | null;
  counted: boolean;
  call_id: string;
  model_score: number | null;
  human_score: number | null;
  reviewer: string | null;
}

export interface VerdictStatsData {
  verdict_unlocked: boolean;
  checked: number;
  random: number;
  agreement: number | null;
  avg_delta: number | null;
  per_criterion_delta: Record<string, number>;
  translation_verified: number;
  random_sample_per_day: number;
  min_review_time_s: number;
  hints: { agreement: number; delta: number };
  agreement_weekly: AgreementWeek[];
  recent_disagreements: Disagreement[];
}

// ── Translation check (§10.11) ──────────────────────────────────────────────
export interface TranscriptWord {
  w: string;
  start?: number | null;
  end?: number | null;
  role?: string | null;
  conf?: number | null;
}

export interface TranslationCall {
  call_id: string;
  player_id: string | number | null;
  duration_s: number | null;
  has_audio: boolean;
  language: string | null;
  text: string | null;
  words: TranscriptWord[] | null;
}

export interface TranslationNextData {
  call: TranslationCall | null;
  remaining: number;
}
