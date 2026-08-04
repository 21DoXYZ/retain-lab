import { requireRole, LIVE_ROLES } from "@/components/monitor/guard";
import { LiveScreen } from "@/components/monitor/LiveScreen";

/**
 * /live — «Играют сейчас» (agent C6). Role-gated (LIVE_ROLES:
 * super_admin/head_retention/director/analyst/marketing_manager — mirrors
 * api/monitor.py & nav.ts). Realtime via POLLING of /api/v1/live every 20s in the
 * client screen (not SSE), per api/monitor.py meta.poll_seconds.
 *
 * NAV (declared by B1, do not edit nav.ts here):
 *   { key:'live', href:'/live', label:'Играют сейчас', emoji:'🔴',
 *     roles:['super_admin','head_retention','director','analyst','marketing_manager'] }
 */
export const dynamic = "force-dynamic";

export default async function LivePage() {
  await requireRole(LIVE_ROLES);
  return <LiveScreen />;
}
