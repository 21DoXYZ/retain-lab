import { requireRole, SIGNALS_ROLES } from "@/components/monitor/guard";
import { SignalsScreen } from "@/components/monitor/SignalsScreen";

/**
 * /signals — «Сигналы модели» (agent C6). Role-gated (SIGNALS_ROLES:
 * super_admin/head_retention/director/risk_officer/marketing_manager/analyst —
 * mirrors api/monitor.py & nav.ts). Data from /api/v1/signals; online overlay
 * from /api/v1/signals/online by POLLING (polling replaces the SSE board).
 *
 * NAV (declared by B1, do not edit nav.ts here):
 *   { key:'signals', href:'/signals', label:'Сигналы модели', emoji:'🧠',
 *     roles:['super_admin','head_retention','director','risk_officer','marketing_manager','analyst'] }
 */
export const dynamic = "force-dynamic";

export default async function SignalsPage() {
  await requireRole(SIGNALS_ROLES);
  return <SignalsScreen />;
}
