import { requireSegmentationRole } from "@/components/segmentation/guard";
import { CohortsView } from "@/components/segmentation/CohortsView";

/**
 * /cohorts — «Все когорты» (36 срезов), agent C3 / finisher F2. Role-gated
 * (SEGMENTATION_ROLES: analyst/director/marketing_manager/head_retention/
 * finance/super_admin); data from /api/v1/cohorts via flaskFetch.
 *
 * NAV: {key:'cohorts', href:'/cohorts', emoji:'🧩', label:'Все когорты', roles:ANALYSTS}
 * — already declared in components/ui/nav.ts (B1, not modified here).
 */
export const dynamic = "force-dynamic";

/** Срезы каналов (B4–B7) переехали в модуль Трафик → /channels (W2-T5, ТЗ §3.6). */
const CHANNEL_GROUPS = ["B · Канал"];

export default async function CohortsPage() {
  await requireSegmentationRole();
  return (
    <CohortsView
      excludeGroups={CHANNEL_GROUPS}
      movedLink={{ href: "/channels", labelKey: "segmentation.cohorts.channelsMoved" }}
    />
  );
}
