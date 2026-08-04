import { requireRole, AUDIT_ROLES } from "@/components/money/guard";
import { FlagsScreen } from "@/components/money/FlagsScreen";

/**
 * /flags — «Лента флагов» (W2-T3). Role-gated (AUDIT_ROLES:
 * director/finance/risk_officer/head_retention/super_admin), 1-в-1 с
 * @require_auth(roles=AUDIT_ROLES) на /api/v1/risk/flags. Данные — через
 * flaskFetch из /api/v1/risk/flags (см. FlagsScreen).
 */
export const dynamic = "force-dynamic";

export default async function FlagsPage() {
  await requireRole(AUDIT_ROLES);
  return <FlagsScreen />;
}
