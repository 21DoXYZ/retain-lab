import type { UserRole } from "@/lib/types";

/**
 * Segmentation domain (C3) — analytical read-only layer.
 *
 * Role allow-list mirrors the Flask guard on api/segmentation.py
 * (require_auth roles): analyst / director / marketing_manager /
 * head_retention / finance / super_admin (SPA_BUILD_PLAN.md §1).
 *
 * The Flask JWT check is the hard boundary; this guard is the server-page
 * first line so a direct URL visit by a disallowed role is redirected instead
 * of rendering a shell that then 403s on fetch.
 *
 * NOTE: the sidebar (components/ui/nav.ts, owned by B1) gates these items to
 * its ANALYSTS set, which omits `finance`. The API and this guard intentionally
 * include `finance` (money/analytics reader) — direct navigation still works.
 * nav.ts is out of C3's zone; flagged for the orchestrator to reconcile.
 */
export const SEGMENTATION_ROLES: UserRole[] = [
  "super_admin",
  "director",
  "head_retention",
  "analyst",
  "marketing_manager",
  "finance",
];

export function canSeeSegmentation(role: UserRole): boolean {
  return SEGMENTATION_ROLES.includes(role);
}
