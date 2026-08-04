import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AccessDenied } from "@/components/ui";
import { QueueBoard } from "@/components/queue/QueueBoard";
import { loadOperatorQueue } from "@/components/queue/data";

/**
 * /queue — operator's personal work queue (ТЗ КЦ п.2.5, п.5.2).
 *
 * NAV: {key:'queue', href:'/queue', label:'Моя очередь', emoji:'📞', roles:['operator','vip_manager','head_department','head_retention','super_admin']}
 *
 * RLS already scopes crm.player_assignments to the caller, so an operator only
 * ever loads their own players (defense-in-depth with the role check below).
 * The (app) layout guards auth; this page adds the role gate + data load and
 * hands off to the live client board. loading.tsx / error.tsx cover the other
 * two required screen states.
 */

const ALLOWED = new Set([
  "operator",
  "vip_manager",
  "head_department",
  "head_retention",
  "super_admin",
]);

export const dynamic = "force-dynamic";

export default async function QueuePage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");

  if (!ALLOWED.has(me.role)) {
    return <AccessDenied titleKey="access.queue.title" descKey="access.queue.desc" />;
  }

  const data = await loadOperatorQueue(me);
  return <QueueBoard me={me} data={data} />;
}
