import { requireSegmentationRole } from "@/components/segmentation/guard";
import { UpliftView } from "@/components/saas/UpliftView";

/**
 * /uplift — Revenue Autopilot: недельный инкремент кампаний против holdout
 * (REBUILD §Phase 6, экран — §2 "uplift"). Роли — как /leak-audit.
 */
export const dynamic = "force-dynamic";

export default async function UpliftPage() {
  await requireSegmentationRole();
  return <UpliftView />;
}
