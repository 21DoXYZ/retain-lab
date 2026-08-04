/**
 * Verdict palette — 1:1 with the board's affiliate status markers
 * (player_board.affiliates() row badges + affiliate() risk banner).
 *
 *   loss (🔴)       — и игра, и касса в минусе (players_win && cash_drain)
 *   risk (⚠️)       — игроки обыгрывают игры (GGR реал<0), касса пока в плюсе
 *   cash_drain (💸) — вывели больше, чем внесли (Net Profit<0), по игре в плюсе
 *   profit (✅)     — касса и игра в плюсе
 */
import type { MessageKey } from "@/lib/i18n";
import type { AffiliateStatus } from "./types";

export interface VerdictStyle {
  emoji: string;
  /** i18n key for the short badge/banner label (monitor.verdict.*.label). */
  labelKey: MessageKey;
  /** i18n key for the full tooltip/banner sentence (monitor.verdict.*.title). */
  titleKey: MessageKey;
  /** Badge fill / text (board .badge.*). */
  badgeBg: string;
  badgeFg: string;
  /** Banner accent / fill / border (board risk_banner col/bg/bd). */
  bannerCol: string;
  bannerBg: string;
  bannerBd: string;
}

export const VERDICT: Record<AffiliateStatus, VerdictStyle> = {
  loss: {
    emoji: "🔴",
    labelKey: "monitor.verdict.loss.label",
    titleKey: "monitor.verdict.loss.title",
    badgeBg: "#fee2e2",
    badgeFg: "#dc2626",
    bannerCol: "#dc2626",
    bannerBg: "#fef2f2",
    bannerBd: "#fecaca",
  },
  risk: {
    emoji: "⚠️",
    labelKey: "monitor.verdict.risk.label",
    titleKey: "monitor.verdict.risk.title",
    badgeBg: "#fef3c7",
    badgeFg: "#92400e",
    bannerCol: "#d97706",
    bannerBg: "#fffbeb",
    bannerBd: "#fde68a",
  },
  cash_drain: {
    emoji: "💸",
    labelKey: "monitor.verdict.cashDrain.label",
    titleKey: "monitor.verdict.cashDrain.title",
    badgeBg: "#fef3c7",
    badgeFg: "#92400e",
    bannerCol: "#d97706",
    bannerBg: "#fffbeb",
    bannerBd: "#fde68a",
  },
  profit: {
    emoji: "✅",
    labelKey: "monitor.verdict.profit.label",
    titleKey: "monitor.verdict.profit.title",
    badgeBg: "#dcfce7",
    badgeFg: "#15803d",
    bannerCol: "#16a34a",
    bannerBg: "#f0fdf4",
    bannerBd: "#bbf7d0",
  },
};
