import { requireSegmentationRole } from "@/components/segmentation/guard";
import { DistView } from "@/components/segmentation/DistView";

/**
 * /dist — «Распределения» (LTV-децили, churn-децили, перцентили депозитов),
 * agent C3 / finisher F2. Role-gated (SEGMENTATION_ROLES); data from
 * /api/v1/dist via flaskFetch.
 *
 * NAV: {key:'dist', href:'/dist', emoji:'📐', label:'Распределения', roles:ANALYSTS}
 * — already declared in components/ui/nav.ts (B1, not modified here).
 */
export const dynamic = "force-dynamic";

export default async function DistPage() {
  await requireSegmentationRole();
  return <DistView />;
}
