import { requireRole, AFF_ROLES } from "@/components/affiliates/guard";
import { VerdictsScreen } from "@/components/affiliates/VerdictsScreen";

/**
 * /verdicts — Traffic module screen "Source verdicts" (W2-T2). Role-gated by
 * AFF_ROLES (mirrors api/traffic.py TRAFFIC_ROLES and the nav "verdicts" allow
 * list: super_admin, head_retention, director, affiliate_manager, finance,
 * analyst). Data from /api/v1/traffic/verdicts via flaskFetch.
 */
export const dynamic = "force-dynamic";

export default async function VerdictsPage() {
  await requireRole(AFF_ROLES);
  return <VerdictsScreen />;
}
