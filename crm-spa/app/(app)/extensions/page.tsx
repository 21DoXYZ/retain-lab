import { requireRole, EXT_ROLES } from "@/components/monitor/guard";
import { ExtensionsScreen } from "@/components/monitor/ExtensionsScreen";

/**
 * /extensions — «Внутренние номера» (оператор → Tegsoft extension). Гейт зеркалит
 * EXT_ADMIN_ROLES в api/calls.py. Без extension звонок оператора невозможен.
 */
export default async function ExtensionsPage() {
  await requireRole(EXT_ROLES);
  return <ExtensionsScreen />;
}
