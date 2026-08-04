import { requireCallRole } from "@/components/call-board/guard";
import { CB_SCRIPT } from "@/components/call-board/roles";
import { ScriptScreen } from "@/components/call-board/ScriptScreen";

/**
 * /call-analysis/script — Скрипт: разметка (§10.8) для руководителя/админа и
 * просмотр read-only (§10.9) для оператора. Role-gated (CB_SCRIPT ≡ R_SCRIPT_GET:
 * head_retention, super_admin, operator, vip_manager). Право записи — на клиенте
 * (canWriteScript) и на сервере (POST-ручки только MANAGE_ALL|ADMIN).
 */
export const dynamic = "force-dynamic";

export default async function ScriptPage() {
  await requireCallRole(CB_SCRIPT);
  return <ScriptScreen />;
}
