import { requireRole, KEYS_ROLES } from "@/components/monitor/guard";
import { KeysScreen } from "@/components/monitor/KeysScreen";

/**
 * /keys — «Ключи интеграции» (agent C6). Role-gated (KEYS_ROLES: super_admin only
 * — mirrors api/monitor.py & nav.ts). Metadata only (masked token + length); the
 * raw secret is returned exactly once by /api/v1/keys/regenerate.
 *
 * NAV (declared by B1, do not edit nav.ts here):
 *   { key:'keys', href:'/keys', label:'Ключи интеграции', emoji:'🔑', roles:['super_admin'] }
 */
export const dynamic = "force-dynamic";

export default async function KeysPage() {
  await requireRole(KEYS_ROLES);
  return <KeysScreen />;
}
