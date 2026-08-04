import { requireRole, DESK_ROLES } from "@/components/monitor/guard";
import { ReportScreen } from "@/components/monitor/ReportScreen";

/**
 * /report — «Отчёт отдела» (agent C6). Role-gated (DESK_ROLES — mirrors
 * api/monitor.py & nav.ts). Data from /api/v1/report via flaskFetch.
 *
 * NAV (declared by B1, do not edit nav.ts here):
 *   { key:'report', href:'/report', label:'Отчёт отдела', emoji:'📑', roles: DESK }
 */
export const dynamic = "force-dynamic";

export default async function ReportPage() {
  await requireRole(DESK_ROLES);
  return <ReportScreen />;
}
