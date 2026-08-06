import { requireSegmentationRole } from "@/components/segmentation/guard";
import { InsightsView } from "@/components/saas/InsightsView";

/** /insights — рекомендации ИИ-аналитика + причины отмен. */
export const dynamic = "force-dynamic";

export default async function InsightsPage() {
  await requireSegmentationRole();
  return <InsightsView />;
}
