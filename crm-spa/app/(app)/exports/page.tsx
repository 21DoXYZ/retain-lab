import { requireRole, EXPORT_ROLES } from "@/components/affiliates/guard";
import { ExportsScreen } from "@/components/affiliates/ExportsScreen";

/**
 * /exports — «Проверка выгрузок» (C5). Role-gated (EXPORT_ROLES, mirrors
 * api/affiliates.py); data from /api/v1/exports (+ /exports/detail) via flaskFetch.
 *
 * NAV: nav key "exports" (href "/exports") already exists in components/ui/nav.ts
 * with roles = EXPORT_ROLES — no nav change is declared here.
 */
export const dynamic = "force-dynamic";

export default async function ExportsPage() {
  await requireRole(EXPORT_ROLES);
  return <ExportsScreen />;
}
