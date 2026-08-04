import { requireRole, AFF_ROLES } from "@/components/affiliates/guard";
import { AffiliatesScreen } from "@/components/affiliates/AffiliatesScreen";

/**
 * /affiliates — INTERNAL traffic overview (C5). Role-gated (AFF_ROLES, mirrors
 * api/affiliates.py); data from /api/v1/affiliates via flaskFetch.
 *
 * NAV: nav key "affiliates" (href "/affiliates") already exists in
 * components/ui/nav.ts with roles = AFF_ROLES — no nav change is declared here.
 * Not to be confused with nav key "affiliate_cabinet" (href "/affiliate", B4),
 * the external affiliate's own cabinet.
 */
export const dynamic = "force-dynamic";

export default async function AffiliatesPage() {
  await requireRole(AFF_ROLES);
  return <AffiliatesScreen />;
}
