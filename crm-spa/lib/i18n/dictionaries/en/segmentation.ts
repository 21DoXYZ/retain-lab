/**
 * en · домен «segmentation». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const segmentation: Partial<Messages> = {
  // ── /rfm ──────────────────────────────────────────────────────────────
  "segmentation.rfm.title": "RFM segments",
  "segmentation.rfm.accent": "· Recency · Frequency · Monetary",
  "segmentation.rfm.lead":
    "classic segmentation on 3 value axes · quintiles 1-5 (Recency is inverted: recent = 5) → named segments · a rule based on the past, not ML",
  "segmentation.rfm.card.coverage.label": "RFM coverage",
  "segmentation.rfm.card.coverage.sub": "of {base} normal · {never} never active (no usage)",
  "segmentation.rfm.card.r.label": "R - Recency",
  "segmentation.rfm.card.r.sub": "how long ago they were active · lower = higher score",
  "segmentation.rfm.card.f.label": "F - Frequency",
  "segmentation.rfm.card.f.sub": "active days",
  "segmentation.rfm.card.m.label": "M - Monetary",
  "segmentation.rfm.card.m.sub": "usage volume",
  "segmentation.rfm.chart.title": "Segment sizes",
  "segmentation.rfm.chart.caption": "number of users per RFM segment",
  "segmentation.rfm.col.segment": "Segment",
  "segmentation.rfm.col.players": "Users",
  "segmentation.rfm.col.pctBase": "% of base",
  "segmentation.rfm.col.avgTurn": "Avg usage",
  "segmentation.rfm.col.avgRecency": "Avg recency",
  "segmentation.rfm.col.avgRecencyTitle": "days since last activity",
  "segmentation.rfm.col.avgDays": "Avg days",
  "segmentation.rfm.col.avgDaysTitle": "active days",
  "segmentation.rfm.col.meaning": "What it means",
  "segmentation.rfm.col.action": "Action",
  "segmentation.rfm.daySuffix": "d",
  "segmentation.rfm.banner.pre": "RFM needs the Monetary axis (usage volume), so it is only computed for",
  "segmentation.rfm.banner.playedWord": "users who were active",
  "segmentation.rfm.banner.mid": "; those who never used the product are a separate row below",
  "segmentation.rfm.banner.convergeTo": " (adds up to {base})",
  "segmentation.rfm.banner.post":
    ". RFM is for the big picture and campaigns; for precise prioritisation of who gets what - see the offer engine on ",
  "segmentation.rfm.banner.deskLink": "Desk",
  "segmentation.rfm.banner.deskTail": ".",

  // ── /dist ─────────────────────────────────────────────────────────────
  "segmentation.dist.title": "Distributions",
  "segmentation.dist.accent": "· percentiles and concentration",
  "segmentation.dist.lead":
    "value and risk distribution by deciles/percentiles - see the concentration (whales hold most of it), not a misleading average",
  "segmentation.dist.card.top10.label": "Top 10% hold",
  "segmentation.dist.card.top10.sub": "of all projected LTV value",
  "segmentation.dist.card.median.label": "Median payment",
  "segmentation.dist.card.median.sub": "P90 {p90} · P99 {p99}",
  "segmentation.dist.card.max.label": "Max payment",
  "segmentation.dist.card.max.sub": "the spread is huge",
  "segmentation.dist.ltvDeciles.title": "LTV forecast deciles",
  "segmentation.dist.ltvDeciles.note": "over {n} users with an LTV forecast (paying users) · D1 = top 10%, D10 = bottom",
  "segmentation.dist.col.decile": "Decile",
  "segmentation.dist.col.players": "Users",
  "segmentation.dist.col.avgLtv": "Avg LTV",
  "segmentation.dist.col.sum": "Sum",
  "segmentation.dist.col.pctValue": "% of all value",
  "segmentation.dist.chart.title": "Value concentration",
  "segmentation.dist.chart.caption": "% of all projected LTV value by decile (D1 = top 10%)",
  "segmentation.dist.ltvDeciles.help.pre": "📖 ",
  "segmentation.dist.ltvDeciles.help.b1": "Decile",
  "segmentation.dist.ltvDeciles.help.mid": " = the base is split into 10 equal 10% groups. ",
  "segmentation.dist.ltvDeciles.help.b2": "D1 = top 10%",
  "segmentation.dist.ltvDeciles.help.post":
    " most valuable, D10 = the smallest. The \"% of all value\" column shows how much money each group holds - you can see the top holds almost everything (concentration on whales).",
  "segmentation.dist.churnDeciles.title": "Churn risk deciles",
  "segmentation.dist.churnDeciles.note": "among {n} active users with a churn score (not the whole base)",
  "segmentation.dist.col.avgRisk": "Avg risk",
  "segmentation.dist.col.range": "Range",
  "segmentation.dist.churnDeciles.help.pre": "📖 ",
  "segmentation.dist.churnDeciles.help.b1": "How to read:",
  "segmentation.dist.churnDeciles.help.mid": " active users are split into 10 groups by churn risk. ",
  "segmentation.dist.churnDeciles.help.b2": "D1 = lowest risk",
  "segmentation.dist.churnDeciles.help.post":
    " (likely to stay), D10 = highest (likely to leave). \"Avg risk\" is the average churn probability in the group.",
  "segmentation.dist.churnWhy.title": "Why churn isn't computed for the whole base - where the rest went",
  "segmentation.dist.col.group": "Group",
  "segmentation.dist.col.whyWhat": "Why / what to do about them",
  "segmentation.dist.total": "Total",
  "segmentation.dist.wholeBaseNormal": "whole normal base",
  "segmentation.dist.churnWhy.help.pre":
    "churn risk only makes sense for the living: bring back those who left, convert those who never activated, onboard the one-timers. That's exactly what the engine on ",
  "segmentation.dist.churnWhy.help.link": "Desk",
  "segmentation.dist.churnWhy.help.post": " does.",
  "segmentation.dist.depositPercentiles.title": "Payment amount percentiles",
  "segmentation.dist.depositPercentiles.note": "over {n} paying users (dep_count>0)",
  "segmentation.dist.col.percentile": "Percentile",
  "segmentation.dist.col.sumTry": "Amount ₺",
  "segmentation.dist.banner.pre": "\"P90 = 11,000\" means",
  "segmentation.dist.banner.bold1": "90% of paying users paid less than 11,000 ₺",
  "segmentation.dist.banner.mid": ", and only 10% paid more.",
  "segmentation.dist.banner.bold2": "P50 = median",
  "segmentation.dist.banner.post":
    "(the typical user). The very top (P99) holds a disproportionate share - which is why the \"average\" is misleading: whales pull it up.",

  // ── /funnel ───────────────────────────────────────────────────────────
  "segmentation.funnel.title": "Payment funnel",
  "segmentation.funnel.accent": "· where we lose users",
  "segmentation.funnel.lead":
    "the user's path: registration → activated → 1st payment → #2 → … → #10 · the \"step conversion\" column shows where the drop-off is biggest",
  "segmentation.funnel.col.stage": "Stage",
  "segmentation.funnel.col.players": "Users",
  "segmentation.funnel.col.pctReg": "% of reg.",
  "segmentation.funnel.col.stepConv": "Step conversion",
  "segmentation.funnel.col.funnelBar": "Funnel",
  "segmentation.funnel.chart.title": "Funnel",
  "segmentation.funnel.chart.caption": "share of users at each stage",
  "segmentation.funnel.emptyTitle": "No funnel data",

  // ── /cohorts ──────────────────────────────────────────────────────────
  "segmentation.cohorts.title": "All cohorts",
  "segmentation.cohorts.defaultSubtitle": "36 slices",
  "segmentation.cohorts.lead":
    "a catalogue of every way to slice the base into groups - for campaigns and analysis · clicking a segment on the board opens its user list",
  "segmentation.cohorts.loading": "Loading slices…",
  "segmentation.cohorts.noData": "no data",
  "segmentation.cohorts.banner.asOf": "Data as of {date}.",
  "segmentation.cohorts.channelsMoved": "Channel slices moved → Channels",

  // ── /channels (W2-T5) - "B · Канал" group slices, moved to the Traffic module ─
  "segmentation.channels.title": "Channels: traffic slices",
  "segmentation.channels.subtitle": "affiliate type, top sources, offer campaigns",
  "segmentation.channels.lead":
    "Where users come from: affiliates, registration sources, offer campaigns.",
  "segmentation.channels.empty.title": "No channel slices",
  "segmentation.channels.empty.desc": "The “Channel” group is empty for the current data snapshot.",
  "segmentation.channels.error.desc": "Couldn’t load the channel slices.",

  // ── /archetypes ───────────────────────────────────────────────────────
  "segmentation.archetypes.title": "User archetypes",
  "segmentation.archetypes.accent": "· similar by behaviour",
  "segmentation.archetypes.lead.withCount": "{n} real users grouped into archetypes by how and what they use",
  "segmentation.archetypes.lead.fallback": "real users grouped into archetypes by how and what they use",
  "segmentation.archetypes.stat.avgBet": "avg usage",
  "segmentation.archetypes.stat.activeDays": "active days",
  "segmentation.archetypes.stat.games": "templates",
  "segmentation.archetypes.stat.depositors": "paying users",
  "segmentation.archetypes.stat.turnover": "usage volume",
};
