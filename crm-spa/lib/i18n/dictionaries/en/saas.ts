/**
 * en · домен «saas» - Revenue Autopilot screens (leak-audit onward).
 */
import type { Messages } from "../ru";

export const saas: Partial<Messages> = {
  "nav.leakAudit": "Leak audit",

  "saas.leak.title": "Leak audit",
  "saas.leak.lead":
    "Where your subscription revenue is leaking right now - failed payments, dead trials, silent cancellations, missed upgrades.",
  "saas.leak.headline": "You are leaking ~{amount}/mo",
  "saas.leak.dunning": "Failed payments (dunning)",
  "saas.leak.dunningSub": "{count} users - MRR at risk right now",
  "saas.leak.silent": "Silent cancellations (30d)",
  "saas.leak.silentSub": "{count} left without a save attempt",
  "saas.leak.upgrades": "Missed upgrades",
  "saas.leak.upgradesSub": "{count} power users at plan limit",
  "saas.leak.deadTrials": "Dead trials",
  "saas.leak.deadTrialsSub": "{count} expired without paying - pipeline",

  "nav.uplift": "Campaign uplift",

  "saas.uplift.title": "Uplift report",
  "saas.uplift.lead":
    "Honest measurement: target vs holdout conversion per campaign - in incremental dollars.",
  "saas.uplift.total": "Incremental this period: {amount}",
  "saas.uplift.col.campaign": "Campaign",
  "saas.uplift.col.target": "Target",
  "saas.uplift.col.holdout": "Holdout",
  "saas.uplift.col.check": "Avg check",
  "saas.uplift.col.incremental": "Incremental",
  "saas.uplift.col.goal": "Goal",
  "saas.uplift.na": "n/a - empty holdout",
  "saas.uplift.groupN": "n={n}",
  "saas.uplift.empty.title": "No reports yet",
  "saas.uplift.empty.desc": "The first uplift report lands after a weekly campaign run (Mon 08:00).",

  "saas.home.tagline":
    "Revenue Autopilot watches every user, sends the right touch itself and honestly measures the incremental revenue. Start with the three screens below.",
  "saas.home.kpi.mrr": "MRR",
  "saas.home.kpi.leak": "Leaking per month",
  "saas.home.kpi.users": "Users tracked",
  "saas.home.kpi.atRisk": "At risk right now",
  "saas.home.kpi.atRiskSub": "dunning + cooling",
  "saas.home.start": "Start here",
  "saas.home.start.leak.title": "Where money leaks",
  "saas.home.start.leak.desc": "Failed payments, silent cancellations, dead trials - in dollars per month.",
  "saas.home.start.users.title": "Users & stages",
  "saas.home.start.users.desc": "Every user with a lifecycle stage and a recommended next action.",
  "saas.home.start.uplift.title": "What campaigns earned",
  "saas.home.start.uplift.desc": "Conversion vs the holdout group - honest incremental dollars.",
  "saas.home.machine": "Autopilot right now",
  "saas.home.machine.body":
    "{active} users in campaigns · {holdout} in holdout · {touches} touches in 7 days · dry-run mode (no emails leave until you enable autopilot)",
  "saas.home.setup": "Setup",
  "saas.home.setup.stripe": "Client Stripe",
  "saas.home.setup.stripe.on": "connected",
  "saas.home.setup.stripe.off": "demo data - waiting for keys",
  "saas.home.setup.snippet": "Site snippet",
  "saas.home.setup.snippet.on": "events flowing",
  "saas.home.setup.snippet.off": "not installed",
  "saas.home.setup.autopilot": "Autopilot",
  "saas.home.setup.autopilot.off": "dry-run (safe)",
  "saas.home.allSections": "All sections",
};
