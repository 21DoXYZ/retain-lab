/**
 * Pure role-gating + display labels for the player card. No React / Supabase
 * imports so it is safe in "use client" and unit-testable. Menu/UI gating is a
 * convenience only — the hard boundary is RLS (crm.*) and the Flask JWT checks
 * (plan §0.4). Mirrors the call/recording matrices in api/calls.py.
 */

import type { UserRole } from "@/lib/types";
import type { MessageKey } from "@/lib/i18n";
import type { CallOutcome, CallResult } from "./types";

// ---- who may do what (kept 1:1 with api/calls.py CALL_ROLES / RECORDING_ROLES) ----
const CALL_ROLES: ReadonlySet<UserRole> = new Set([
  "operator",
  "head_department",
  "head_retention",
  "vip_manager",
  "affiliate",
  "super_admin",
  "director", // руководство может звонить/утверждать оффер (зеркало api/calls.py)
]);

const RECORDING_ROLES: ReadonlySet<UserRole> = new Set([
  "risk_officer",
  "head_department",
  "head_retention",
  "director",
  "super_admin",
]);

/** Roles that plan/schedule touches (own queue, dept, or affiliate players). */
const SCHEDULE_ROLES: ReadonlySet<UserRole> = new Set([
  "operator",
  "vip_manager",
  "head_department",
  "head_retention",
  "affiliate",
  "super_admin",
  "director",
]);

/** Roles that may write a note (RLS still scopes WHICH player). */
const NOTE_WRITE_ROLES: ReadonlySet<UserRole> = new Set([
  "operator",
  "vip_manager",
  "head_department",
  "head_retention",
  "super_admin",
  "support",
  "affiliate",
  "director", // может править/утверждать оффер (кнопки пишут заметку)
]);

export interface CardSections {
  /** Show the "Позвонить" block. */
  call: boolean;
  /** Show recording playback controls. */
  recording: boolean;
  /** Show the "запланировать следующий" block. */
  schedule: boolean;
  /** Show the notes block (list is always RLS-scoped; write gated separately). */
  notes: boolean;
  /** May add a note (subject to RLS on the specific player). */
  writeNote: boolean;
  /** Show the recommendation/offer strip (what to pitch — not casino money). */
  recommendation: boolean;
  /**
   * Mount C2's analytics sections slot. Pure operators get an ops-only card
   * (plan §1: operator "без аналитики/денег"); everyone else sees C2's
   * role-scoped analytics (support/affiliate reduced by C2 itself).
   */
  analytics: boolean;
  /**
   * Показать ТОЛЬКО блок «Бонусы» (реакция на бонусы) отдельно от полного
   * аналитического слота — для оператора (у него analytics=false, но клиент
   * попросил открыть именно бонус-реакцию по своим игрокам). Остальные роли
   * видят бонусы внутри analytics-слота, поэтому здесь false.
   */
  bonusSection: boolean;
}

/** Resolve which card blocks a role sees (short cards for support/affiliate). */
export function cardSections(role: UserRole): CardSections {
  return {
    call: CALL_ROLES.has(role),
    recording: RECORDING_ROLES.has(role),
    schedule: SCHEDULE_ROLES.has(role),
    notes: true,
    writeNote: NOTE_WRITE_ROLES.has(role),
    // «🎯 Рекомендованное действие» + «✍️ Оффер игроку» — часть карточки для всех.
    recommendation: true,
    // Аналитические секции — операторам НЕ показываем (решение клиента 2026-07-29:
    // полную карточку операторам откатили — у них ops-card без денег/аналитики;
    // «бонус эффект» открыт отдельно пунктом меню «Бонусы: эффект»). support/
    // affiliate — тоже без аналитики; остальным C2 сам режет по ролям.
    analytics: role !== "operator",
    // Оператору — отдельный блок «Бонусы» (реакция на бонусы), без остального
    // аналитического слота. Бэкенд открыл operator в BONUS_BLOCK_ROLES (по своим
    // игрокам, anti-IDOR); деньги/скоры/депозиты в карточке ему по-прежнему закрыты.
    bonusSection: role === "operator",
  };
}

export function canDeleteNote(role: UserRole): boolean {
  return role === "head_retention" || role === "super_admin";
}

/** Window (ms) during which an author may edit their own note (ТЗ п.4.1). */
export const NOTE_EDIT_WINDOW_MS = 15 * 60 * 1000;

export function isWithinEditWindow(createdAtIso: string, now: number = Date.now()): boolean {
  const created = new Date(createdAtIso).getTime();
  if (Number.isNaN(created)) return false;
  return now - created < NOTE_EDIT_WINDOW_MS;
}

// ---- display labels (i18n keys — translated at the render point: CallBlock,
// OutcomeModal, NotesBlock) ------------------------------------------------

export const OUTCOME_LABELS: Record<CallOutcome, MessageKey> = {
  answered: "card.outcome.answered",
  no_answer: "card.outcome.noAnswer",
  busy: "card.outcome.busy",
  wrong_number: "card.outcome.wrongNumber",
};

export const RESULT_LABELS: Record<CallResult, MessageKey> = {
  interested: "card.result.interested",
  offer_declined: "card.result.offerDeclined",
  callback_requested: "card.result.callbackRequested",
  refused: "card.result.refused",
};

/** Note tag chips (ТЗ п.4.2). `offer_declined` binds to the active offer. */
export const NOTE_TAGS = [
  "offer_declined",
  "other_offer",
  "callback",
  "negative",
  "returned",
] as const;

export type NoteTag = (typeof NOTE_TAGS)[number];

export const TAG_LABELS: Record<NoteTag, MessageKey> = {
  offer_declined: "card.tag.offerDeclined",
  other_offer: "card.tag.otherOffer",
  callback: "card.tag.callback",
  negative: "card.tag.negative",
  returned: "card.tag.returned",
};

/** Colour hints for tag chips (board palette; blue-scale accents). */
export const TAG_TONE: Record<NoteTag, { bg: string; fg: string }> = {
  offer_declined: { bg: "#fef2f2", fg: "#b91c1c" },
  other_offer: { bg: "#eff6ff", fg: "#1d4ed8" },
  callback: { bg: "#fffbeb", fg: "#b45309" },
  negative: { bg: "#fef2f2", fg: "#dc2626" },
  returned: { bg: "#ecfdf5", fg: "#047857" },
};
