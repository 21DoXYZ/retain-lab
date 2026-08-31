import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { LaunchesView } from "@/components/saas/LaunchesView";

/** /launches - «Запуски и трафик»: когорты + сегменты застревания (JTBD). */
export const dynamic = "force-dynamic";

const OWNER_ROLES = new Set([
  "super_admin", "head_retention", "director", "analyst", "finance", "marketing_manager",
]);

export default async function LaunchesPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (!OWNER_ROLES.has(user.role)) redirect("/home");
  return <LaunchesView />;
}
