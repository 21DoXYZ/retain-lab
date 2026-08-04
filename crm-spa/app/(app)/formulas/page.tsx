import { FormulasScreen } from "@/components/monitor/FormulasScreen";

/**
 * /formulas — «Формулы расчётов» (agent C6). Reference screen: any authenticated
 * user (api/monitor.py formulas() is require_auth()); the (app) layout already
 * guards auth, so no extra role gate. Static content served from /api/v1/formulas.
 *
 * NAV (declared by B1, do not edit nav.ts here):
 *   { key:'formulas', href:'/formulas', label:'Формулы расчётов', emoji:'📐', roles:[…] }
 */
export const dynamic = "force-dynamic";

export default function FormulasPage() {
  return <FormulasScreen />;
}
