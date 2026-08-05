import { requireSegmentationRole } from "@/components/segmentation/guard";
import { CampaignsView } from "@/components/saas/CampaignsView";

/**
 * /campaigns — SaaS-кампании автопилота (K1-K5): шаги, тексты, каналы, цель,
 * статистика + рубильник. Казино-экран бонус-кампаний (CampaignsScreen)
 * заменён SaaS-пресетом.
 */
export const dynamic = "force-dynamic";

export default async function CampaignsPage() {
  await requireSegmentationRole();
  return <CampaignsView />;
}
