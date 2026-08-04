import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AccessDenied } from "@/components/ui";
import { PoolBoard } from "@/components/queue/PoolBoard";
import { loadPool } from "@/components/queue/data";

/**
 * /pool — player pool + batch assignment for heads (ТЗ КЦ п.2.1–2.4).
 *
 * NAV: {key:'pool', href:'/pool', label:'Пул игроков', emoji:'🗃', roles:['super_admin','head_retention','head_department']}
 *
 * RLS scopes the visible pool (head_retention/super_admin → all players;
 * head_department → own department) and gates every assign/transfer/remove.
 * The role check here is the app-level first line; the DB is the backstop.
 */

const ALLOWED = new Set(["super_admin", "head_retention", "head_department"]);

export const dynamic = "force-dynamic";

export default async function PoolPage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");

  if (!ALLOWED.has(me.role)) {
    return <AccessDenied titleKey="access.pool.title" descKey="access.pool.desc" />;
  }

  const data = await loadPool(me);
  return <PoolBoard me={me} data={data} />;
}
