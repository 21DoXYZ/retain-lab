import { notFound } from "next/navigation";
import { requireRole, AFF_ROLES } from "@/components/affiliates/guard";
import { AffiliateDetailScreen } from "@/components/affiliates/AffiliateDetailScreen";

/**
 * /affiliates/<code> — full reconciliation card for one source (C5). Role-gated
 * (AFF_ROLES); data from /api/v1/affiliates/<code> via flaskFetch.
 *
 * NAV: this is a detail view of the "affiliates" section (reached by row click),
 * not a top-level menu item — no nav entry is declared. The external cabinet at
 * /affiliate (B4) is a different route and is not touched here.
 */
export const dynamic = "force-dynamic";

export default async function AffiliateDetailPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  await requireRole(AFF_ROLES);
  const { code } = await params;
  const clean = decodeURIComponent(code).trim();
  if (!clean) notFound();
  return <AffiliateDetailScreen code={clean} />;
}
