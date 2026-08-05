import { requireSegmentationRole } from "@/components/segmentation/guard";
import { OffersView } from "@/components/saas/OffersView";

/** /offers — каталог офферов + статистика выдач. Роли = LEAK_ROLES. */
export const dynamic = "force-dynamic";

export default async function SaasOffersPage() {
  await requireSegmentationRole();
  return <OffersView />;
}
