import { requireCallRole } from "@/components/call-board/guard";
import { CB_OVERVIEW } from "@/components/call-board/roles";
import { OverviewScreen } from "@/components/call-board/OverviewScreen";

/**
 * /call-analysis — Обзор (§10.1). Точка входа руководителя в модуль. Role-gated
 * (CB_OVERVIEW ≡ R_OVERVIEW в api/call_analysis.py); данные из /overview.
 */
export const dynamic = "force-dynamic";

export default async function CallAnalysisOverviewPage() {
  await requireCallRole(CB_OVERVIEW);
  return <OverviewScreen />;
}
