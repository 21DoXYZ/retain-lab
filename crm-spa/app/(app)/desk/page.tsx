import { requireRole, DESK_ROLES } from "@/components/monitor/guard";
import { DeskScreen } from "@/components/monitor/DeskScreen";

/**
 * /desk — «Пульт (очередь)» (agent C6). Role-gated (DESK_ROLES:
 * super_admin/head_retention/head_department/director — mirrors api/monitor.py
 * & nav.ts). Data from /api/v1/desk via flaskFetch in the client screen.
 *
 * NAV (declared by B1, do not edit nav.ts here):
 *   { key:'desk', href:'/desk', label:'Пульт (очередь)', emoji:'🎛', roles: DESK }
 */
export const dynamic = "force-dynamic";

export default async function DeskPage() {
  await requireRole(DESK_ROLES);
  return <DeskScreen />;
}
