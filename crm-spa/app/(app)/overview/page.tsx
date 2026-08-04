import { requireRole, CASINO_MONEY_ROLES } from "@/components/money/guard";
import { OverviewScreen } from "./OverviewScreen";

/**
 * /overview — «Обзор» (agent C1). Role-gated (MONEY_ROLES); data flows from
 * /api/v1/money/overview via flaskFetch in the client screen. Dynamic: KPIs are
 * always live from ClickHouse.
 */
export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  await requireRole(CASINO_MONEY_ROLES);
  return <OverviewScreen />;
}
