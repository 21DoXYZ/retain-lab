import { requireRole, MARKETING_ROLES } from "@/components/marketing/guard";
import { ChainsList } from "@/components/automation/ChainsList";

/**
 * /chains — automation chain builder (W4-T5). Role-gated by MARKETING_ROLES,
 * which is 1:1 with READ_ROLES in api/chains.py (super_admin, director,
 * head_retention, marketing_manager, analyst, vip_manager). Write actions inside
 * the list/editor are further gated client-side to WRITE_ROLES. Data via
 * flaskFetch from /api/v1/chains (+ /chains/templates, /segments, /segments/fields).
 */
export const dynamic = "force-dynamic";

export default async function ChainsPage() {
  await requireRole(MARKETING_ROLES);
  return <ChainsList />;
}
