import { requireSegmentationRole } from "@/components/segmentation/guard";
import { PipelineView } from "@/components/saas/PipelineView";

/**
 * /pipeline — здоровье конвейера (дирижёр сверху). Роли = LEAK_ROLES.
 */
export const dynamic = "force-dynamic";

export default async function PipelinePage() {
  await requireSegmentationRole();
  return <PipelineView />;
}
