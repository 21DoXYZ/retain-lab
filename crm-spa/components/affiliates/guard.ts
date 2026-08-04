/**
 * Server-side role gate for the INTERNAL affiliates + exports screens (C5).
 * Mirrors the require_auth(roles=...) matrices in api/affiliates.py (AFF_ROLES /
 * EXPORT_ROLES) and the nav.ts allow-lists (keys "affiliates" and "exports").
 * Menu hiding is cosmetic; this + the Flask JWT check are the real boundary.
 * Import only from Server Components (uses lib/auth → next/headers).
 */
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import type { CurrentUser, UserRole } from "@/lib/types";

/** /affiliates, /affiliates/<code> — AFF_ROLES in api/affiliates.py. */
export const AFF_ROLES: readonly UserRole[] = [
  "affiliate_manager",
  "finance",
  "director",
  "head_retention",
  "analyst",
  "super_admin",
];

/** /exports — EXPORT_ROLES in api/affiliates.py. */
export const EXPORT_ROLES: readonly UserRole[] = [
  "super_admin",
  "head_retention",
  "head_department",
  "affiliate_manager",
];

/**
 * Resolve the signed-in user and enforce a role allow-list. Redirects to /login
 * when unauthenticated and to / when the role is not permitted. Returns the user
 * on success so the page can pass it down if needed.
 */
export async function requireRole(
  allowed: readonly UserRole[],
): Promise<CurrentUser> {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (!allowed.includes(me.role)) redirect("/");
  return me;
}
