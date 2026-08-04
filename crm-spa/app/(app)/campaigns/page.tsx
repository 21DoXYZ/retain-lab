import { requireRole, MARKETING_ROLES } from "@/components/marketing/guard";
import { CampaignsScreen } from "@/components/marketing/CampaignsScreen";

/**
 * /campaigns — «Бонус-кампании» (agent C4/F3). Role-gated (MARKETING_ROLES);
 * the 8 look-alike segments for bonus blasts flow from /api/v1/campaigns via
 * flaskFetch.
 */
export const dynamic = "force-dynamic";

export default async function CampaignsPage() {
  await requireRole(MARKETING_ROLES);
  return <CampaignsScreen />;
}
