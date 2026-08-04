import { requireSegmentationRole } from "@/components/segmentation/guard";
import { ArchetypesView } from "@/components/segmentation/ArchetypesView";

/**
 * /archetypes — «Архетипы игроков» (поведенческие типажи), agent C3 / finisher
 * F2. Role-gated (SEGMENTATION_ROLES); data from /api/v1/archetypes via
 * flaskFetch (PERSONA_SQL классификация борда).
 *
 * NAV: {key:'archetypes', href:'/archetypes', emoji:'🧬', label:'Архетипы', roles:ANALYSTS}
 * — already declared in components/ui/nav.ts (B1, not modified here).
 */
export const dynamic = "force-dynamic";

export default async function ArchetypesPage() {
  await requireSegmentationRole();
  return <ArchetypesView />;
}
