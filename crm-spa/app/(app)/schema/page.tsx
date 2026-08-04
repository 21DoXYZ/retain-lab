import { SchemaScreen } from "@/components/monitor/SchemaScreen";

/**
 * /schema — «Схема данных» (agent C6). Reference screen: any authenticated user
 * (api/monitor.py schema() is require_auth() — no role list); the (app) layout
 * already guarantees a signed-in user, so no extra role gate here. Live row
 * counts come from /api/v1/schema via flaskFetch.
 *
 * NAV (declared by B1, do not edit nav.ts here):
 *   { key:'schema', href:'/schema', label:'Схема данных', emoji:'🗺', roles:[…analysts/finance/marketing/affiliate_manager] }
 */
export const dynamic = "force-dynamic";

export default function SchemaPage() {
  return <SchemaScreen />;
}
