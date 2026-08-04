import { requireRole, MARKETING_ROLES } from "@/components/marketing/guard";
import { ActionsScreen } from "@/components/marketing/ActionsScreen";

/**
 * /actions — «Действия / Офферы» (agent C4/F3). Role-gated (MARKETING_ROLES);
 * priority list + offer engine + three in-house VIP scores from /api/v1/actions
 * and /api/v1/vip-scores via flaskFetch.
 */
export const dynamic = "force-dynamic";

export default async function ActionsPage() {
  await requireRole(MARKETING_ROLES);
  return <ActionsScreen />;
}
