import { requireSegmentationRole } from "@/components/segmentation/guard";
import { ChannelsView } from "@/components/saas/ChannelsView";

/** /channel-settings — провайдеры каналов и покрытие контактов. Роли = LEAK_ROLES. */
export const dynamic = "force-dynamic";

export default async function ChannelSettingsPage() {
  await requireSegmentationRole();
  return <ChannelsView />;
}
