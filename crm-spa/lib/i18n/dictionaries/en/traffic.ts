// "Source verdicts" screen + Traffic module "Channels" tab (W2-T2/T5). Keys "traffic.*".
export const traffic = {
  // ── "Source verdicts" screen (W2-T2) ──
  "traffic.verdicts.title": "Source verdicts",
  "traffic.verdicts.lead":
    "Day-5 cohort quality forecast: which sources bring valuable players and which bring fraud. Per-source call — scale · watch · disable.",
  "traffic.verdicts.pill.asOf": "data as of {date}",
  "traffic.verdicts.pill.median": "median LTV D90: {v}",

  "traffic.verdicts.tab.source": "Sources",
  "traffic.verdicts.tab.affiliate": "Affiliates",

  "traffic.verdicts.days.label": "Cohort window",
  "traffic.verdicts.days.opt": "{n}d",

  // table columns (spec §3.1)
  "traffic.verdicts.col.source": "Source",
  "traffic.verdicts.col.affiliate": "Affiliate",
  "traffic.verdicts.col.players": "Players (7d)",
  "traffic.verdicts.col.playersTitle": "Registrations in the window (in brackets — last 7 days)",
  "traffic.verdicts.col.ftd": "FTD",
  "traffic.verdicts.col.ftdTitle": "Players with a first deposit",
  "traffic.verdicts.col.deposits": "Deposits",
  "traffic.verdicts.col.depositsTitle": "Cohort deposit sum (cash, casino spec)",
  "traffic.verdicts.col.predSum": "LTV D90 forecast, Σ",
  "traffic.verdicts.col.predSumTitle": "Total 90-day deposit forecast over scored players",
  "traffic.verdicts.col.predAvg": "per player",
  "traffic.verdicts.col.predAvgTitle": "Average LTV D90 forecast per scored player",
  "traffic.verdicts.col.confidence": "Confidence",
  "traffic.verdicts.col.verdict": "Verdict",

  // verdicts
  "traffic.verdicts.verdict.scale": "scale up",
  "traffic.verdicts.verdict.watch": "watch",
  "traffic.verdicts.verdict.disable": "disable",
  "traffic.verdicts.verdict.maturing": "maturing · verdict in {n}d",
  "traffic.verdicts.verdict.maturingSmall": "maturing · too little data",

  // confidence
  "traffic.verdicts.conf.high": "high",
  "traffic.verdicts.conf.mid": "medium",
  "traffic.verdicts.conf.low": "low",

  // legend / how to read
  "traffic.verdicts.legend.label": "How to read:",
  "traffic.verdicts.legend.scale": "forecast well above median and FTD rate not below baseline — pour more",
  "traffic.verdicts.legend.watch": "within norm — keep watching",
  "traffic.verdicts.legend.disable": "players beat the games (GGR < 0) or forecast half the median — disable",
  "traffic.verdicts.legend.maturing": "cohort younger than 5 days or fewer than 10 players — too early to judge",
  "traffic.verdicts.legend.draft": "Thresholds are drafts — to be agreed with Vasiliy.",

  // states
  "traffic.verdicts.empty.title": "No new registrations in the window",
  "traffic.verdicts.empty.desc": "No cohorts in the selected window — widen the range or wait for new registrations.",
  "traffic.verdicts.error.title": "Failed to load verdicts",
  "traffic.verdicts.error.desc": "Check the connection to the analytics backend and retry.",
} satisfies Record<string, string>;
