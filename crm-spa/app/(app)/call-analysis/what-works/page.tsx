import { requireCallRole } from "@/components/call-board/guard";
import { CB_WHATWORKS } from "@/components/call-board/roles";
import { WhatWorksScreen } from "@/components/call-board/WhatWorksScreen";

/**
 * /call-analysis/what-works — Что работает (§10.6). Role-gated (CB_WHATWORKS ≡
 * R_WHATWORKS: head_retention, super_admin). Ранжирование по принятым офферам.
 */
export const dynamic = "force-dynamic";

export default async function WhatWorksPage() {
  await requireCallRole(CB_WHATWORKS);
  return <WhatWorksScreen />;
}
