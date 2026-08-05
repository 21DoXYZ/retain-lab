// TODO: тексты согласовать с Василием (оригинал - Retivo_модули_демо.html, недоступен)
/**
 * en · домен «modules». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const modules: Partial<Messages> = {
  // ── column labels ─────────────────────────────────────────────────────
  "modules.header.about": "Who this screen is for and why",
  "modules.header.chair": "Whose pain",
  "modules.header.pain": "Pain",
  "modules.header.action": "Action from this screen",

  // ── 1. Traffic & affiliates ───────────────────────────────────────────
  "modules.traffic.chair": "Head of affiliates / media buyer",
  "modules.traffic.pain": "Where the budget goes: which sources bring users and which bring fraud and losses",
  "modules.traffic.action": "Verdict per source: scale · watch · switch off",

  // ── 2. VIP radar ──────────────────────────────────────────────────────
  "modules.vip.chair": "Power user manager / head of retention",
  "modules.vip.pain": "Whales bring the lion's share of the cash, yet they are lost silently",
  "modules.vip.action": "Find an at-risk whale and take them into work before they leave",

  // ── 3. Bonus economics ────────────────────────────────────────────────
  "modules.bonuseco.chair": "CMO / offer manager",
  "modules.bonuseco.pain": "Offers are handed out blindly: nobody knows what came back as money",
  "modules.bonuseco.action": "See the offer P&L and switch off what doesn't pay back",

  // ── 4. Risk & fraud ───────────────────────────────────────────────────
  "modules.risk.chair": "Risk officer / finance",
  "modules.risk.pain": "Manual write-offs, refunds without payments and abuse surface after the fact",
  "modules.risk.action": "Work through the flag feed and close the holes before the losses",

  // ── 5. Retention automation (core) ────────────────────────────────────
  "modules.core.chair": "Retention manager / call centre",
  "modules.core.pain": "Users slip away between touches: no one and nothing to retain them in time",
  "modules.core.action": "Take the task queue and reach the right user with a precise touch now",

  // ── 6. Analytics ──────────────────────────────────────────────────────
  "modules.analytics.chair": "Product / management",
  "modules.analytics.pain": "The numbers are scattered across screens, there is no full picture",
  "modules.analytics.action": "Check the trends and find where the funnel is sagging",

  // ── 7. Data / API ─────────────────────────────────────────────────────
  "modules.data.chair": "Integrator / tech lead",
  "modules.data.pain": "Unclear what data the system receives and what it is missing",
  "modules.data.action": "Check the schema, the keys and the integration status",
} satisfies Partial<Messages>;
