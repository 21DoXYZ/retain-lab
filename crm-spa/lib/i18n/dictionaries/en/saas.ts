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
};
