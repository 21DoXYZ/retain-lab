// «Flags feed» screen of the Risk & fraud module (W2-T3). Keys "risk.*". en — translations of ru.
export const risk = {
  "risk.flags.title": "Flags feed",
  "risk.flags.lead": "A single «needs review» queue — signals from audit, affiliates and bonuses in one list.",

  // Header pills
  "risk.flags.pill.total": "{n} to review",
  "risk.flags.pill.checked": "checked {mins} min ago",
  "risk.flags.pill.checkedNow": "checked just now",

  // Per-kind tiles (click = filter the feed)
  "risk.flags.tile.hint": "Click — filter the feed by this kind",
  "risk.flags.tile.active": "filter active",
  "risk.flags.kind.no_deposit_withdrawal.label": "Withdrawal without deposit",
  "risk.flags.kind.no_deposit_withdrawal.sub": "manual debits > 50k ₺ with deposit < 10% of withdrawal",
  "risk.flags.kind.suspicious_operator.label": "Operator in question",
  "risk.flags.kind.suspicious_operator.sub": "≥ 40% of debits without a clear note",
  "risk.flags.kind.affiliate_players_win.label": "Players beat the games",
  "risk.flags.kind.affiliate_cash_drain.label": "Cash in the red",
  "risk.flags.kind.affiliate_players_win.sub": "source's real GGR is negative",
  "risk.flags.kind.affiliate_cash_drain.sub": "withdrawals exceed deposits",
  "risk.flags.kind.bonus_abuse.label": "Bonus abuse",
  "risk.flags.kind.bonus_abuse.sub": "«🎁 Bonus hunter» archetype in profit on freespins",

  // Table columns
  "risk.flags.col.kind": "Kind",
  "risk.flags.col.entity": "Entity",
  "risk.flags.col.amount": "Amount ₺",
  "risk.flags.col.severity": "Severity",
  "risk.flags.col.details": "Details",

  // Entities (links to cards)
  "risk.flags.entity.player": "Player #{id}",
  "risk.flags.entity.operator": "Operator {id}",
  "risk.flags.entity.affiliate": "Source {id}",

  // Row details per kind
  "risk.flags.details.no_deposit_withdrawal": "deposited {deposited} ₺ · {ops} ops",
  "risk.flags.details.suspicious_operator": "unclear {unclear}% · {ops} ops",
  "risk.flags.details.adminBadge": "admin/service",
  "risk.flags.details.affiliate": "{players} players · FTD {ftd}",
  "risk.flags.details.bonus_abuse": "freespins {freespin}%",

  // Severity
  "risk.flags.sev.3": "large (≥ 100k ₺)",
  "risk.flags.sev.2": "notable (≥ 20k ₺)",
  "risk.flags.sev.1": "minor",

  // Filter
  "risk.flags.filter.reset": "Reset filter",

  // Explainer banner
  "risk.flags.banner.severity": "Severity: 🔴 large (≥ 100k ₺) · 🟡 notable (≥ 20k ₺) · ⚪ minor.",
  "risk.flags.banner.sources": "Sources: debit audit, affiliate verdicts, «Bonus hunter» archetype. Click a tile to filter the feed.",

  // Empty «all clear» (spec §4.1) + empty by filter
  "risk.flags.empty.clear.title": "No flags — all clear",
  "risk.flags.empty.clear.desc": "Nothing to review. Last check {mins} min ago.",
  "risk.flags.empty.clear.descNow": "Nothing to review. Last check just now.",
  "risk.flags.empty.kind.title": "No flags of this kind",
  "risk.flags.empty.kind.desc": "Nothing for the selected kind right now. Reset the filter to see the rest.",

  // Route states (loading / error)
  "risk.flags.loading.lead": "Collecting signals to review…",
  "risk.flags.error.title": "Failed to load the flags feed",
  "risk.flags.error.desc": "Check the connection and try again.",
} satisfies Record<string, string>;
