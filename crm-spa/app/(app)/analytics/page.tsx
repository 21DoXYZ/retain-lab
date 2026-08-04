import { requireRole, MONEY_ROLES } from "@/components/money/guard";
import { AnalyticsScreen } from "./AnalyticsScreen";

/**
 * /analytics — «Аналитика · графики» + секция #cash (agent C1). Role-gated
 * (MONEY_ROLES); charts from /api/v1/money/cash via flaskFetch.
 */
export const dynamic = "force-dynamic";

export default async function AnalyticsPage() {
  await requireRole(MONEY_ROLES);
  return <AnalyticsScreen />;
}
