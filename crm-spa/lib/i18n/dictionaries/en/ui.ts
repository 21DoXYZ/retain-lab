/**
 * en · домен «ui». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const ui: Partial<Messages> = {
  "ui.empty.title": "Nothing found",
  "ui.error.title": "Failed to load",
  "ui.error.description": "Try refreshing. If it keeps happening, contact your administrator.",
  "ui.error.retry": "Retry",

  "ui.collapsible.expand": "click to expand ▾",
  "ui.collapsible.collapse": "collapse ▴",

  "ui.modal.close": "Close",

  "ui.cancel": "Cancel",
  "ui.save": "Save",

  "ui.badge.lifecycle.active": "active",
  "ui.badge.lifecycle.cooling": "cooling",
  "ui.badge.lifecycle.atRisk": "at risk",
  "ui.badge.lifecycle.dormant": "dormant",
  "ui.badge.lifecycle.churned": "churned",
  "ui.badge.lifecycle.never": "never played",
  "ui.badge.lifecycleTip.active": "Placed a bet within the last 7 days",
  "ui.badge.lifecycleTip.cooling": "Last bet 8–30 days ago",
  "ui.badge.lifecycleTip.atRisk": "Last bet 31–60 days ago",
  "ui.badge.lifecycleTip.dormant": "Last bet 61–90 days ago",
  "ui.badge.lifecycleTip.churned": "Last bet more than 90 days ago",
  "ui.badge.lifecycleTip.never": "No bets at all",

  "ui.badge.accountType.service": "🛡 service/admin",
  "ui.badge.accountType.testOrService": "🧪 test",
  "ui.badge.accountType.blocked": "⛔ blocked",

  "ui.badge.tier.a": "A · <1k/wk",
  "ui.badge.tier.b": "B · 1–3k",
  "ui.badge.tier.c": "C · 3–10k",
  "ui.badge.tier.d": "D · 10k+ 🐋",

  "ui.badge.beatsCasino.tooltip":
    "beats the casino: positive on cash and on play — bonuses are not recommended",
  "ui.badge.beatsCasino.ariaLabel": "beats the casino",

  // app header (UserMenu)
  "ui.signOut": "Sign out",

  // next-best-action badge (offer engine). Code stays, the hint is localized.
  "ui.badge.action.SAVE": "SAVE · retain",
  "ui.badge.action.WINBACK": "WINBACK · win back",
  "ui.badge.action.NUDGE": "NUDGE · 2nd deposit",
  "ui.badge.action.CONVERT": "CONVERT · first deposit",
  "ui.badge.action.NURTURE": "NURTURE · grow",
  "ui.badge.action.MONITOR": "MONITOR · player in profit (review)",
  "ui.badge.action.observe": "observe",
  "ui.freshness.badge": "data up to {ts}",
  "ui.freshness.hint": "Data is loaded up to: money — {money}, game — {game}. Beyond that it is the data boundary, not player silence.",

};
