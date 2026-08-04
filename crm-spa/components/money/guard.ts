/**
 * Server-side role gate for the money/revenue screens (agent C1).
 * Mirrors the require_auth(roles=...) matrices in api/money.py and the nav.ts
 * allow-lists. Menu hiding is cosmetic; this + the Flask JWT check are the real
 * boundary. Import only from Server Components (uses lib/auth → next/headers).
 */
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import type { CurrentUser, UserRole } from "@/lib/types";

/** analytics(#cash) — MONEY_ROLES in api/money.py (маркетингу нужна cashflow-аналитика). */
export const MONEY_ROLES: readonly UserRole[] = [
  "director",
  "finance",
  "analyst",
  "marketing_manager",
  "head_retention",
  "super_admin",
];

/**
 * overview / ggr — CASINO_MONEY_ROLES in api/money.py (БЕЗ marketing_manager:
 * казино-GGR/NGR ему не отдаётся). Гейт страницы держим 1-в-1 с Flask, иначе
 * marketing прошёл бы requireRole, но получил 403 от API (мёртвый URL).
 */
export const CASINO_MONEY_ROLES: readonly UserRole[] = [
  "director",
  "finance",
  "analyst",
  "head_retention",
  "super_admin",
];

/** audit — AUDIT_ROLES in api/money.py. */
export const AUDIT_ROLES: readonly UserRole[] = [
  "director",
  "finance",
  "risk_officer",
  "head_retention",
  "super_admin",
];

/**
 * Resolve the signed-in user and enforce a role allow-list. Redirects to /login
 * when unauthenticated and to / when the role is not permitted. Returns the user
 * on success so the page can pass it down if needed.
 */
export async function requireRole(allowed: readonly UserRole[]): Promise<CurrentUser> {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (!allowed.includes(me.role)) redirect("/");
  return me;
}
