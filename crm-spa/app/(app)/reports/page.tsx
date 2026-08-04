import type { UserRole } from "@/lib/types";
import { requireRole } from "@/components/marketing/guard";
import { ReportBuilder } from "@/components/reports/ReportBuilder";

/**
 * /reports — конструктор отчётов (W5-T4). Role-gated по REPORT_ROLES, 1:1 с
 * api/reports.py (super_admin, head_retention, director, analyst, marketing_manager,
 * finance) и nav.ts (MONEY + marketing_manager). Скрытие пункта меню косметично —
 * реальная граница здесь (requireRole) + JWT-проверка ролей на Flask. Данные:
 * flaskFetch из /api/v1/reports/* в клиентском компоненте. Dynamic: цифры живые.
 */
export const REPORT_ROLES: readonly UserRole[] = [
  "super_admin",
  "head_retention",
  "director",
  "analyst",
  "marketing_manager",
  "finance",
];

export const dynamic = "force-dynamic";

export default async function ReportsPage() {
  await requireRole(REPORT_ROLES);
  return <ReportBuilder />;
}
