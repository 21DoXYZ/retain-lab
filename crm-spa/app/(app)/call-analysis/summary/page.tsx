import { requireCallRole } from "@/components/call-board/guard";
import { CB_SUMMARY } from "@/components/call-board/roles";
import { SummaryScreen } from "@/components/call-board/SummaryScreen";

/**
 * /call-analysis/summary — Сводка (§10.12). Единственный экран директора в
 * модуле. Role-gated (CB_SUMMARY ≡ R_SUMMARY: director, head_retention,
 * super_admin). Средний балл приходит только при разблок. вердикте.
 */
export const dynamic = "force-dynamic";

export default async function SummaryPage() {
  await requireCallRole(CB_SUMMARY);
  return <SummaryScreen />;
}
