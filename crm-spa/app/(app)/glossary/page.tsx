import { GlossaryScreen } from "@/components/monitor/GlossaryScreen";

/**
 * /glossary — «Обозначения (словарь)» (agent C6). Reference screen: any
 * authenticated user (api/monitor.py glossary() is require_auth(); nav shows it to
 * every internal seat). The (app) layout guards auth, so no extra role gate.
 * Static content served from /api/v1/glossary.
 *
 * NAV (declared by B1, do not edit nav.ts here):
 *   { key:'glossary', href:'/glossary', label:'Обозначения (словарь)', emoji:'📖', roles: INTERNAL }
 */
export const dynamic = "force-dynamic";

export default function GlossaryPage() {
  return <GlossaryScreen />;
}
