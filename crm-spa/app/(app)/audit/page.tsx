import { requireRole, AUDIT_ROLES } from "@/components/money/guard";
import { AuditScreen } from "./AuditScreen";

/**
 * /audit — «Аудит ручных списаний» (agent C1). Role-gated (AUDIT_ROLES:
 * director/finance/risk_officer/head_retention/super_admin); data from
 * /api/v1/audit via flaskFetch.
 */
export const dynamic = "force-dynamic";

export default async function AuditPage() {
  await requireRole(AUDIT_ROLES);
  return <AuditScreen />;
}
