import { requireRole, MARKETING_ROLES } from "@/components/marketing/guard";
import { BonusesScreen } from "@/components/marketing/BonusesScreen";

/**
 * /bonuses — «Бонусы: каталог» (agent C4/F3). Role-gated (MARKETING_ROLES); the
 * real BillionBahis promo catalog + per-player matching flow from /api/v1/bonuses
 * via flaskFetch.
 */
export const dynamic = "force-dynamic";

export default async function BonusesPage() {
  await requireRole(MARKETING_ROLES);
  return <BonusesScreen />;
}
