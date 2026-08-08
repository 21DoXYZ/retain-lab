import { requireClientWorkRole } from "@/components/segmentation/guard";
import { WaInboxView } from "@/components/saas/WaInboxView";

/** /wa-inbox — переписка личного WhatsApp (трек C). Роли = LEAK_ROLES. */
export const dynamic = "force-dynamic";

export default async function WaInboxPage() {
  await requireClientWorkRole();
  return <WaInboxView />;
}
