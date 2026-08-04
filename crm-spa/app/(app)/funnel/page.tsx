import { requireSegmentationRole } from "@/components/segmentation/guard";
import { FunnelView } from "@/components/segmentation/FunnelView";

/**
 * /funnel — «Воронка депозитов» (регистрация → играл → FTD → #2 … → #N),
 * agent C3 / finisher F2. Role-gated (SEGMENTATION_ROLES); data from
 * /api/v1/funnel via flaskFetch (deposit_ladder борда).
 *
 * NAV: {key:'funnel', href:'/funnel', emoji:'🫗', label:'Воронка депозитов', roles:ANALYSTS}
 * — already declared in components/ui/nav.ts (B1, not modified here).
 */
export const dynamic = "force-dynamic";

export default async function FunnelPage() {
  await requireSegmentationRole();
  return <FunnelView />;
}
