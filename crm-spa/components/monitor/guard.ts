/**
 * Server-side role gate for the «Монитор и справочники» screens (agent C6).
 * These lists mirror the require_auth([...]) matrices in api/monitor.py (the real
 * JWT boundary) and the nav.ts allow-lists (menu visibility) so the triple stays
 * consistent: menu shows it → page loads → API returns data. Import only from
 * Server Components (uses lib/auth → next/headers). Menu hiding is cosmetic; the
 * Flask JWT check + RLS are the hard boundary (plan §0.4).
 *
 * NOTE (deviation from the F5 brief text): the brief summarised gating with
 * narrower sets (e.g. live = head_retention/head_department/director). We instead
 * mirror api/monitor.py exactly — a page gate stricter than the Flask boundary
 * and the menu would redirect users who legitimately see the item and are
 * authorised by the API. super_admin is always included (platform owner).
 */
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import type { CurrentUser, UserRole } from "@/lib/types";

/** /desk + /report — DESK_ROLES in api/monitor.py (== nav.ts DESK). */
export const DESK_ROLES: readonly UserRole[] = [
  "super_admin",
  "head_retention",
  "head_department",
  "director",
];

/** /live — LIVE_ROLES in api/monitor.py (== nav.ts live). */
export const LIVE_ROLES: readonly UserRole[] = [
  "super_admin",
  "head_retention",
  "director",
  "analyst",
  "marketing_manager",
];

/** /signals — SIGNALS_ROLES in api/monitor.py (== nav.ts signals). */
export const SIGNALS_ROLES: readonly UserRole[] = [
  "super_admin",
  "head_retention",
  "director",
  "risk_officer",
  "marketing_manager",
  "analyst",
];

/** /keys — KEYS_ROLES in api/monitor.py (super_admin only). */
export const KEYS_ROLES: readonly UserRole[] = ["super_admin"];

/** «Внутренние номера» — EXT_ADMIN_ROLES в api/calls.py (super_admin + главы). */
export const EXT_ROLES: readonly UserRole[] = [
  "super_admin",
  "head_retention",
  "head_department",
];

/**
 * Resolve the signed-in user and enforce a role allow-list. Redirects to /login
 * when unauthenticated and to / when the role is not permitted. Returns the user
 * on success. (schema/formulas/glossary need no gate — require_auth() = any
 * authenticated; the (app) layout already guarantees a signed-in user.)
 */
export async function requireRole(allowed: readonly UserRole[]): Promise<CurrentUser> {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (!allowed.includes(me.role)) redirect("/");
  return me;
}
