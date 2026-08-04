/**
 * Badge colour maps — ported verbatim from player_board.py so stage / account
 * / action / tier / VIP badges are pixel-identical to the live dashboard.
 * Colours are applied as inline background/foreground (as the board does),
 * because they are data-driven and outside the Tailwind token palette.
 */

import type { MessageKey } from "@/lib/i18n";

export interface BadgeTone {
  bg: string;
  fg: string;
  /** Raw display text (dash / passthrough of unmapped API data) — NOT translated. */
  label: string;
}

/**
 * bg/fg + an i18n key ("ui.badge.*") resolved at the render point
 * (components/ui/Badge.tsx and PoolBoard's stage chips, both via useT()).
 * No plain-text `label` field: every consumer of LIFECYCLE/ACCOUNT_TYPE/TIER
 * has been migrated to `labelKey` (PoolBoard's stage filter chips included),
 * so keeping a redundant ru literal alongside it would just be dead weight.
 */
export interface TranslatedBadgeTone {
  bg: string;
  fg: string;
  labelKey: MessageKey;
}

/** lifecycle stage → colours + label key (board LIFE). */
export const LIFECYCLE: Record<string, TranslatedBadgeTone> = {
  active: { bg: "#dcfce7", fg: "#166534", labelKey: "ui.badge.lifecycle.active" },
  cooling: { bg: "#dbeafe", fg: "#1e40af", labelKey: "ui.badge.lifecycle.cooling" },
  at_risk: { bg: "#fef9c3", fg: "#854d0e", labelKey: "ui.badge.lifecycle.atRisk" },
  dormant: { bg: "#f1f5f9", fg: "#475569", labelKey: "ui.badge.lifecycle.dormant" },
  churned: { bg: "#fee2e2", fg: "#991b1b", labelKey: "ui.badge.lifecycle.churned" },
  never: { bg: "#f1f5f9", fg: "#94a3b8", labelKey: "ui.badge.lifecycle.never" },
};

export const LIFECYCLE_FALLBACK: BadgeTone = { bg: "#ededed", fg: "#8a8a8a", label: "—" };

/** account_type → colours + label key. 'normal' renders no badge (board at_badge). */
export const ACCOUNT_TYPE: Record<string, TranslatedBadgeTone> = {
  service: { bg: "#e0e7ff", fg: "#4338ca", labelKey: "ui.badge.accountType.service" },
  test_or_service: { bg: "#fef9c3", fg: "#854d0e", labelKey: "ui.badge.accountType.testOrService" },
  blocked: { bg: "#fee2e2", fg: "#991b1b", labelKey: "ui.badge.accountType.blocked" },
};

export const ACCOUNT_TYPE_FALLBACK: BadgeTone = { bg: "#f1f5f9", fg: "#64748b", label: "" };

/**
 * next-best-action code → colours (board ACT_COLORS) + подпись-ключ.
 *
 * API (retention.player_actions.action) отдаёт «КОД · пояснение по-русски»
 * (напр. "NURTURE · растить"), а особый случай «наблюдать» — вовсе без кода.
 * Ключи здесь — по КОДУ (первое слово), поэтому подпись локализуется: иначе
 * турецкий оператор читал бы русское пояснение из витрины. Незнакомый код →
 * ACTION_FALLBACK, и ActionBadge печатает сырое значение API как есть.
 */
export const ACTION: Record<string, { bg: string; fg: string; labelKey: MessageKey }> = {
  SAVE: { bg: "#fee2e2", fg: "#991b1b", labelKey: "ui.badge.action.SAVE" },
  WINBACK: { bg: "#fef9c3", fg: "#854d0e", labelKey: "ui.badge.action.WINBACK" },
  NUDGE: { bg: "#dbeafe", fg: "#1e40af", labelKey: "ui.badge.action.NUDGE" },
  CONVERT: { bg: "#e0e7ff", fg: "#4338ca", labelKey: "ui.badge.action.CONVERT" },
  NURTURE: { bg: "#dcfce7", fg: "#166534", labelKey: "ui.badge.action.NURTURE" },
  MONITOR: { bg: "#e0e7ff", fg: "#4338ca", labelKey: "ui.badge.action.MONITOR" },
  // сырое значение API без кода — ключ лукапа, не копия интерфейса
  наблюдать: { bg: "#f1f5f9", fg: "#475569", labelKey: "ui.badge.action.observe" },
};

export const ACTION_FALLBACK = { bg: "#ededed", fg: "#8a8a8a" };

/** LTV early tier → colours + label key (board TIER_BG / TIER_LBL). */
export const TIER: Record<string, TranslatedBadgeTone> = {
  A: { bg: "#f1f5f9", fg: "#475569", labelKey: "ui.badge.tier.a" },
  B: { bg: "#dbeafe", fg: "#1e40af", labelKey: "ui.badge.tier.b" },
  C: { bg: "#fef9c3", fg: "#854d0e", labelKey: "ui.badge.tier.c" },
  D: { bg: "#dcfce7", fg: "#166534", labelKey: "ui.badge.tier.d" },
};

export const TIER_FALLBACK: BadgeTone = { bg: "#ededed", fg: "#8a8a8a", label: "" };

/** VIP level (0–5) → label (board VIPLBL). */
export const VIP_LABEL: Record<number, string> = {
  0: "⚪ Regular",
  1: "🥈 Silver",
  2: "🥇 Gold",
  3: "💠 Platinum",
  4: "💎 Diamond",
  5: "👑 Royal",
};

/** VIP badge tint per level (Silver+ uses the beige/cream accent). */
export const VIP_TONE: Record<number, BadgeTone> = {
  0: { bg: "#f1f5f9", fg: "#64748b", label: VIP_LABEL[0] },
  1: { bg: "#f1f5f9", fg: "#475569", label: VIP_LABEL[1] },
  2: { bg: "#fef9c3", fg: "#854d0e", label: VIP_LABEL[2] },
  3: { bg: "#dbeafe", fg: "#1e40af", label: VIP_LABEL[3] },
  4: { bg: "#e0e7ff", fg: "#4338ca", label: VIP_LABEL[4] },
  5: { bg: "#dcfce7", fg: "#166534", label: VIP_LABEL[5] },
};
