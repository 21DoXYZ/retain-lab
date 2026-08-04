import { requireCallRole } from "@/components/call-board/guard";
import { CB_MYCARDS } from "@/components/call-board/roles";
import { MyCallsScreen } from "@/components/call-board/MyCallsScreen";

/**
 * /call-analysis/my — Мои звонки (§10.10). Экран оператора (TR через словарь).
 * Role-gated (CB_MYCARDS ≡ R_MYCARDS: operator, vip_manager). Балл виден только
 * при разблок. вердикте — это решает сервер (в payload приходит score или нет).
 */
export const dynamic = "force-dynamic";

export default async function MyCallsPage() {
  await requireCallRole(CB_MYCARDS);
  return <MyCallsScreen />;
}
