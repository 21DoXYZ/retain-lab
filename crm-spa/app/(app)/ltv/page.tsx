import { requireRole, MARKETING_ROLES } from "@/components/marketing/guard";
import { LtvScreen } from "@/components/marketing/LtvScreen";

/**
 * /ltv — «LTV-прогноз» (agent C4/F3). Role-gated (MARKETING_ROLES); the curve,
 * tiers and young-whales flow from /api/v1/ltv via flaskFetch in the client
 * screen. Dynamic: KPIs are always live from ClickHouse.
 */
export const dynamic = "force-dynamic";

export default async function LtvPage() {
  await requireRole(MARKETING_ROLES);
  return <LtvScreen />;
}
