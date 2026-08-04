/**
 * Словарь терминов модуля (§11) + гейты ролей карточки/очереди. Чистый модуль,
 * без React/Supabase — только маппинг «код бэкенда → ключ i18n». Слова строго
 * человеческие (§2 принцип 5): никаких ASR/LLM/needs_human в подписях.
 */
import type { MessageKey } from "@/lib/i18n";
import type { UserRole } from "@/lib/types";

/** 9 канонических критериев в порядке рубрики (§8). */
export const CRITERIA_ORDER = [
  "open_identify",
  "rapport",
  "discovery",
  "offer_presented",
  "offer_value",
  "objection_handling",
  "alt_offer",
  "next_step",
  "tone",
] as const;

export type CriterionKey = (typeof CRITERIA_ORDER)[number];

const CRITERION_LABELS: Record<string, MessageKey> = {
  open_identify: "calls.criteria.open_identify",
  rapport: "calls.criteria.rapport",
  discovery: "calls.criteria.discovery",
  offer_presented: "calls.criteria.offer_presented",
  offer_value: "calls.criteria.offer_value",
  objection_handling: "calls.criteria.objection_handling",
  alt_offer: "calls.criteria.alt_offer",
  next_step: "calls.criteria.next_step",
  tone: "calls.criteria.tone",
};

/** Ключ подписи критерия (или null для незнакомого — покажем сырой код). */
export function criterionLabelKey(name: string): MessageKey | null {
  return CRITERION_LABELS[name] ?? null;
}

/** Состояние звонка → человеческое слово (§11.1). */
const STATUS_LABELS: Record<string, MessageKey> = {
  received: "calls.status.inQueue",
  audio_checked: "calls.status.inQueue",
  transcribed: "calls.status.transcribing",
  diarized: "calls.status.transcribing",
  redacted: "calls.status.transcribing",
  scored: "calls.status.scoring",
  completed: "calls.status.completed",
  needs_review: "calls.status.needsReview",
  manual_review: "calls.status.manualReview",
  asr_failed: "calls.status.asrFailed",
  llm_failed: "calls.status.llmFailed",
  error: "calls.status.error",
};

export function statusLabelKey(status: string | null | undefined): MessageKey | null {
  return status ? (STATUS_LABELS[status] ?? null) : null;
}

/** Флаги подлинности → слово (§11.4). too_short/repeated_pattern берут vars. */
const FLAG_LABELS: Record<string, MessageKey> = {
  too_short: "calls.flag.too_short",
  no_player_speech: "calls.flag.no_player_speech",
  mark_mismatch_no_answer: "calls.flag.mark_mismatch_no_answer",
  mark_mismatch_claimed: "calls.flag.mark_mismatch_claimed",
  repeated_pattern: "calls.flag.repeated_pattern",
  random_review: "calls.flag.random_review",
};

export function flagLabelKey(flag: string): MessageKey | null {
  return FLAG_LABELS[flag] ?? null;
}

/** Возражения (§11.3). */
const OBJECTION_LABELS: Record<string, MessageKey> = {
  no_money: "calls.objection.no_money",
  no_time: "calls.objection.no_time",
  lost_before: "calls.objection.lost_before",
  distrust: "calls.objection.distrust",
  other: "calls.objection.other",
};

export function objectionLabelKey(code: string): MessageKey | null {
  return OBJECTION_LABELS[code] ?? null;
}

/** Исход оффера (§11.3). */
const OUTCOME_LABELS: Record<string, MessageKey> = {
  accepted: "calls.outcome.accepted",
  refused: "calls.outcome.refused",
  countered: "calls.outcome.countered",
  no_offer: "calls.outcome.no_offer",
  unclear: "calls.outcome.unclear",
};

export function outcomeLabelKey(code: string | null | undefined): MessageKey | null {
  return code ? (OUTCOME_LABELS[code] ?? null) : null;
}

/** Обязательные фразы: известные ключи → подпись; иначе сырой ключ (§10.3). */
const COMPLIANCE_LABELS: Record<string, MessageKey> = {
  recording: "calls.phrase.recording",
  recording_warning: "calls.phrase.recording",
  age: "calls.phrase.age",
  age_18: "calls.phrase.age",
  responsible: "calls.phrase.responsible",
  responsible_gaming: "calls.phrase.responsible",
  responsible_gambling: "calls.phrase.responsible",
};

export function complianceLabelKey(key: string): MessageKey | null {
  return COMPLIANCE_LABELS[key] ?? null;
}

/** Вердикт (§11.2) → подпись + семантический тон (цвет + слово, §13). */
export interface VerdictTone {
  labelKey: MessageKey;
  /** hex bg/fg — как data-driven тон в проекте (Badge/OutcomeBadge). */
  bg: string;
  fg: string;
}

const VERDICT_TONES: Record<string, VerdictTone> = {
  PASS: { labelKey: "calls.verdict.pass", bg: "#dcfce7", fg: "#15803d" },
  NEEDS_REVIEW: { labelKey: "calls.verdict.needsReview", bg: "#fef3c7", fg: "#b45309" },
  FAIL: { labelKey: "calls.verdict.fail", bg: "#fee2e2", fg: "#dc2626" },
};

export function verdictTone(passFail: string | null | undefined): VerdictTone | null {
  return passFail ? (VERDICT_TONES[passFail] ?? null) : null;
}

/**
 * Иконка + тон балла критерия 1..5 (мокап §10.3: 5 ✓, 3/2 ⚠, 1 ✗). Цвет
 * НИКОГДА не единственный носитель статуса — рядом всегда значок/число (§13).
 */
export interface CriterionMark {
  icon: "check" | "warn" | "cross";
  fg: string;
}

export function criterionMark(score: number): CriterionMark {
  if (score >= 4) return { icon: "check", fg: "#15803d" };
  if (score <= 1) return { icon: "cross", fg: "#dc2626" };
  return { icon: "warn", fg: "#b45309" };
}

// ── Роли (зеркалят require_auth в api/call_analysis.py) ─────────────────────
/** Кто может подтверждать/править (R_REVIEW): руководители + админ. */
const REVIEW_ROLES: ReadonlySet<UserRole> = new Set([
  "head_department",
  "head_retention",
  "super_admin",
]);

/** Кто видит карточку/очередь как проверяющий (запись/правки). */
export function canReview(role: UserRole): boolean {
  return REVIEW_ROLES.has(role);
}

/** Кто видит вкладку анализа в карточке игрока (руководители + аналитик). */
const PLAYER_TAB_ROLES: ReadonlySet<UserRole> = new Set([
  "head_department",
  "head_retention",
  "super_admin",
  "analyst",
]);

export function canSeePlayerAnalysis(role: UserRole): boolean {
  return PLAYER_TAB_ROLES.has(role);
}
