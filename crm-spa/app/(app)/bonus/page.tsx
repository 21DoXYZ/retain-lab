import { requireRole, MARKETING_ROLES } from "@/components/marketing/guard";
import { BonusScreen } from "@/components/marketing/BonusScreen";

/**
 * /bonus — «Бонусы: эффект» (agent C4/F3). Role-gated (MARKETING_ROLES); the
 * causal uplift (ATT), per-type effectiveness and recommendations flow from
 * /api/v1/bonus via flaskFetch.
 */
export const dynamic = "force-dynamic";

export default async function BonusPage() {
  // «Бонусы: эффект» открыт руководителю КЦ (запрос клиента). Операторам меню
  // убрано (2026-07-29): им нужна реакция на бонусы в КАРТОЧКЕ, а не агрегат.
  await requireRole([...MARKETING_ROLES, "head_department"]);
  return <BonusScreen />;
}
