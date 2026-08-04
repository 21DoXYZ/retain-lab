import { requireSegmentationRole } from "@/components/segmentation/guard";
import { CohortsView } from "@/components/segmentation/CohortsView";

/**
 * /channels — «Каналы: срезы по трафику» (W2-T5, ТЗ §3.6). Reuses CohortsView
 * filtered to the "B · Канал" group (B4–B7: affiliate type, top sources, bonus
 * campaigns). Same data (/api/v1/cohorts) and same role gate as /cohorts
 * (SEGMENTATION_ROLES) — the traffic-module rebuild moved these slices here.
 *
 * NAV: {key:'channels', href:'/channels', emoji:'📡', roles:ANALYSTS}
 * — already declared in components/ui/nav.ts (not modified here).
 */
export const dynamic = "force-dynamic";

const CHANNEL_GROUPS = ["B · Канал"];

export default async function ChannelsPage() {
  await requireSegmentationRole();
  return (
    <CohortsView
      onlyGroups={CHANNEL_GROUPS}
      titleKey="segmentation.channels.title"
      subtitleKey="segmentation.channels.subtitle"
      leadKey="segmentation.channels.lead"
      emptyKey={{
        title: "segmentation.channels.empty.title",
        desc: "segmentation.channels.empty.desc",
      }}
    />
  );
}
