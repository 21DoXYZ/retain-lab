import { requireCallRole } from "@/components/call-board/guard";
import { CB_VERDICT } from "@/components/call-board/roles";
import { VerdictScreen } from "@/components/call-board/VerdictScreen";

/**
 * /call-analysis/verdict — Вердикт и веса (§10.13). Admin-only гейт (CB_VERDICT ≡
 * R_ADMIN: super_admin). Разблокировка вердикта + настройка случайной выборки и
 * порога времени на разборе.
 */
export const dynamic = "force-dynamic";

export default async function VerdictPage() {
  await requireCallRole(CB_VERDICT);
  return <VerdictScreen />;
}
