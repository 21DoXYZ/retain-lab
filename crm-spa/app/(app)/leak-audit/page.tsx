import { requireSegmentationRole } from "@/components/segmentation/guard";
import { LeakAuditView } from "@/components/saas/LeakAuditView";

/**
 * /leak-audit — Revenue Autopilot: «где утекает выручка» (REBUILD §Phase 5).
 * Роли — те же 6, что у API (LEAK_ROLES в api/saas.py = SEGMENTATION_ROLES).
 */
export const dynamic = "force-dynamic";

export default async function LeakAuditPage() {
  await requireSegmentationRole();
  return <LeakAuditView />;
}
