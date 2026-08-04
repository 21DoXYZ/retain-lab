import { requireRole, CASINO_MONEY_ROLES } from "@/components/money/guard";
import { GgrScreen } from "./GgrScreen";

/**
 * /ggr — «GGR и доход» (agent F1). Role-gated (MONEY_ROLES:
 * director/finance/analyst/marketing_manager/head_retention/super_admin);
 * data from /api/v1/ggr via flaskFetch, paritet с ggr_page() борда.
 *
 * NAV: declared in components/ui/nav.ts — group «Деньги и риск», key "ggr",
 * href "/ggr", roles MONEY. No nav edit needed here.
 */
export const dynamic = "force-dynamic";

export default async function GgrPage() {
  await requireRole(CASINO_MONEY_ROLES);
  return <GgrScreen />;
}
