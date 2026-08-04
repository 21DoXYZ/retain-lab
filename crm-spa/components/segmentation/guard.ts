/**
 * Server-side role gate for the segmentation screens (agent C3 / finisher F2).
 *
 * Mirrors the require_auth(roles=ANALYST_ROLES) guard on api/segmentation.py:
 *   analyst / director / marketing_manager / head_retention / finance / super_admin
 * (SPA_BUILD_PLAN.md §1). The single source of the role list is access.ts
 * (SEGMENTATION_ROLES) so page gate and client helper never drift.
 *
 * Menu hiding (nav.ts ANALYSTS) is cosmetic; this + the Flask JWT check are the
 * real boundary. Import only from Server Components (uses lib/auth → next/headers).
 *
 * NOTE: nav.ts (owned by B1) gates these items to ANALYSTS, which omits
 * `finance`. The API and this guard intentionally include `finance` (money /
 * analytics reader) so a direct URL visit still works. nav.ts is out of this
 * agent's zone — flagged for the orchestrator to reconcile.
 */
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import type { CurrentUser } from "@/lib/types";
import { SEGMENTATION_ROLES } from "./access";

/**
 * Resolve the signed-in user and enforce the segmentation allow-list.
 * Redirects to /login when unauthenticated and to / when the role is not
 * permitted. Returns the user on success.
 */
export async function requireSegmentationRole(): Promise<CurrentUser> {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (!SEGMENTATION_ROLES.includes(me.role)) redirect("/");
  return me;
}
