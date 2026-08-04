import { requireRole, DESK_ROLES } from "@/components/monitor/guard";
import { VipRiskScreen } from "@/components/monitor/VipRiskScreen";

/**
 * /vip-risk — очередь «риск × перспективность» по VIP (инхаус vip-intelligence).
 * Тот же гейт, что у Пульта: руководящие роли ретеншена (DESK_ROLES).
 */
export const dynamic = "force-dynamic";

export default async function VipRiskPage() {
  await requireRole(DESK_ROLES);
  return <VipRiskScreen />;
}
