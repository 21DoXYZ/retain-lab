import { requireRole, MARKETING_ROLES } from "@/components/marketing/guard";
import { SegmentsList } from "@/components/automation/SegmentsList";

/**
 * /segments — segment builder (W4-T2). Role-gated by MARKETING_ROLES, which is
 * 1:1 with READ_ROLES in api/segments.py (super_admin, director, head_retention,
 * marketing_manager, analyst, vip_manager). Write actions inside the editor are
 * further gated client-side to WRITE_ROLES. Data via flaskFetch from
 * /api/v1/segments (+ /fields, /presets, /preview).
 */
export const dynamic = "force-dynamic";

export default async function SegmentsPage() {
  await requireRole(MARKETING_ROLES);
  return <SegmentsList />;
}
