/**
 * Server-side role gate for the marketing / model screens (agent C4, F3).
 * Mirrors MARKETING_ROLES in api/marketing.py (ltv / actions / bonus / bonuses /
 * campaigns / games) and the nav.ts allow-lists. Menu hiding is cosmetic; this
 * plus the Flask JWT check are the real boundary. Import only from Server
 * Components (uses lib/auth → next/headers).
 */
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import type { CurrentUser, UserRole } from "@/lib/types";

/** ltv / actions / bonus / bonuses / campaigns / games — MARKETING_ROLES in api/marketing.py. */
export const MARKETING_ROLES: readonly UserRole[] = [
  "super_admin",
  "director",
  "head_retention",
  "marketing_manager",
  "analyst",
  "vip_manager",
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
