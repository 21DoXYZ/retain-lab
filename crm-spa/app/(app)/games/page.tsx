import { requireRole, MARKETING_ROLES } from "@/components/marketing/guard";
import { GamesScreen } from "@/components/marketing/GamesScreen";

/**
 * /games — «Игры · сегменты для рассылок» (agent C4/F3). Role-gated
 * (MARKETING_ROLES); top games WITH names (not hashes) flow from /api/v1/games
 * via flaskFetch.
 */
export const dynamic = "force-dynamic";

export default async function GamesPage() {
  await requireRole(MARKETING_ROLES);
  return <GamesScreen />;
}
