import { requireCallRole } from "@/components/call-board/guard";
import { CB_COVERAGE } from "@/components/call-board/roles";
import { CoverageScreen } from "@/components/call-board/CoverageScreen";

/**
 * /call-analysis/coverage — Покрытие обзвона (§10.7). Role-gated (CB_COVERAGE ≡
 * R_COVERAGE). Переназначение выполняется вручную в CRM (нет ручки в бэкенде).
 */
export const dynamic = "force-dynamic";

export default async function CoveragePage() {
  await requireCallRole(CB_COVERAGE);
  return <CoverageScreen />;
}
