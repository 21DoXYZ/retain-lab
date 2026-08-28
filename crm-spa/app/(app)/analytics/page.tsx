import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { requireRole, MONEY_ROLES } from "@/components/money/guard";
import { AnalyticsScreen } from "./AnalyticsScreen";
import { AnalyticsView } from "@/components/saas/AnalyticsView";

/**
 * /analytics
 *   • SaaS-пресет (владелец/аналитик) → профессиональный дашборд аналитики
 *     Revenue Autopilot (рост, гео, воронка, деньги) + внешний шаринг.
 *   • Casino-пресет (money-роли) → прежний экран cashflow-графиков.
 * Ветвление зеркалит app/(app)/page.tsx (home): OWNER_ROLES = LEAK_ROLES на
 * бэке (api/saas.py) - те же роли, что видят весь кабинет владельца.
 */
export const dynamic = "force-dynamic";

const OWNER_ROLES = new Set([
  "super_admin", "head_retention", "director", "analyst", "finance", "marketing_manager",
]);

export default async function AnalyticsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (OWNER_ROLES.has(user.role)) return <AnalyticsView />;

  await requireRole(MONEY_ROLES);
  return <AnalyticsScreen />;
}
