import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import type { UserRole } from "@/lib/types";
import { QueueScreen } from "@/components/call-analysis/QueueScreen";

/**
 * /call-analysis/queue — очередь проверки (§10.2). Гейт зеркалит R_QUEUE в
 * api/call_analysis.py: руководители отдела/ретеншена + админ. Аналитик сюда не
 * ходит (проверять не может), оператор — тем более (у него свой экран §10.10).
 * Меню — косметика; настоящая граница здесь + JWT-проверка Flask.
 */
export const dynamic = "force-dynamic";

const QUEUE_ROLES: readonly UserRole[] = ["head_department", "head_retention", "super_admin"];

export default async function CallQueuePage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (!QUEUE_ROLES.includes(me.role)) redirect("/");
  return <QueueScreen />;
}
