import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { WorkspacesView } from "@/components/saas/WorkspacesView";

/** /admin/workspaces — создание пространств клиентов. Только платформа. */
export const dynamic = "force-dynamic";

export default async function WorkspacesPage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (me.role !== "super_admin") redirect("/home");
  return <WorkspacesView />;
}
