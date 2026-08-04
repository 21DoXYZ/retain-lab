import { requireCallRole } from "@/components/call-board/guard";
import { CB_TRANSLATION } from "@/components/call-board/roles";
import { TranslationCheckScreen } from "@/components/call-board/TranslationCheckScreen";

/**
 * /call-analysis/translation-check — Проверка перевода (§10.11). TR-экран.
 * Role-gated (CB_TRANSLATION ≡ R_TRANSLATION: translation_reviewer, super_admin).
 * translation_reviewer — временный доступ, роли вне типизированного UserRole.
 */
export const dynamic = "force-dynamic";

export default async function TranslationCheckPage() {
  await requireCallRole(CB_TRANSLATION);
  return <TranslationCheckScreen />;
}
