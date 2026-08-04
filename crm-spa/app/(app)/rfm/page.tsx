import { requireSegmentationRole } from "@/components/segmentation/guard";
import { RfmView } from "@/components/segmentation/RfmView";

/**
 * /rfm — «RFM-сегменты» (Recency · Frequency · Monetary), agent C3 / finisher
 * F2. Role-gated (SEGMENTATION_ROLES); data from /api/v1/rfm via flaskFetch.
 *
 * NAV: {key:'rfm', href:'/rfm', emoji:'🎯', label:'RFM-сегменты', roles:ANALYSTS}
 * — already declared in components/ui/nav.ts (B1, not modified here).
 */
export const dynamic = "force-dynamic";

export default async function RfmPage() {
  await requireSegmentationRole();
  return <RfmView />;
}
