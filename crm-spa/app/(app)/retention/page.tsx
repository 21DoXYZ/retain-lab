import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { RetentionView } from "@/components/saas/RetentionView";

export const dynamic = "force-dynamic";

const OWNER_ROLES = new Set([
  "super_admin", "head_retention", "director", "analyst", "finance", "marketing_manager",
]);

export default async function Page() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (!OWNER_ROLES.has(user.role)) redirect("/home");
  return <RetentionView />;
}
