import { requireRole } from "@/components/money/guard";
import type { UserRole } from "@/lib/types";
import { PlayersScreen } from "./PlayersScreen";

/**
 * /players — «Игроки», список всей базы (agent F1). Role-gated with LIST_ROLES,
 * mirroring api/players_analytics.py (management / analytics / service roles;
 * NOT operator or affiliate — they have isolated slices). Data from
 * /api/v1/players via flaskFetch; row click → the card at /players/[id] (B3).
 *
 * NAV: the sidebar item "players" (components/ui/nav.ts) currently points at "/".
 * This is the dedicated list route (the card lives at /players/[id]); nav.ts is
 * owned by A2/B1 and left untouched — a nav href update to "/players" is a
 * separate, out-of-scope change.
 */
const LIST_ROLES: readonly UserRole[] = [
  "super_admin",
  "head_retention",
  "director",
  "head_department",
  "analyst",
  "finance",
  "marketing_manager",
  "affiliate_manager",
  "risk_officer",
  "support",
  "vip_manager",
  "viewer",
];

export const dynamic = "force-dynamic";

export default async function PlayersListPage() {
  await requireRole(LIST_ROLES);
  return <PlayersScreen />;
}
