import { requireSegmentationRole } from "@/components/segmentation/guard";
import { UserCardView } from "@/components/saas/UserCardView";

/**
 * /users/[id] — карточка юзера SaaS-контура (detail-страница списка /users,
 * без своего пункта в навигации). id = identity_id либо client_user_id -
 * бэкенд резолвит оба, поэтому сюда ведут и таблица юзеров, и WA-инбокс.
 */
export const dynamic = "force-dynamic";

export default async function SaasUserCardPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await requireSegmentationRole();
  const { id } = await params;
  return <UserCardView identity={decodeURIComponent(id)} />;
}
