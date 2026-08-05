import { requireSegmentationRole } from "@/components/segmentation/guard";
import { UsersView } from "@/components/saas/UsersView";

/** /users — юзеры SaaS-контура (стадии/действия/скоры). Роли = LEAK_ROLES. */
export const dynamic = "force-dynamic";

export default async function SaasUsersPage() {
  await requireSegmentationRole();
  return <UsersView />;
}
