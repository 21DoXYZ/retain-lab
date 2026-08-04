import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import type { CurrentUser } from "@/lib/types";

/**
 * Server-side role gate for the «Анализ звонков» management pages. Mirrors
 * requireRole in components/money/guard.ts but takes a readonly string[] so it
 * can accept the temporary translation_reviewer role (§10.11), which is outside
 * the typed UserRole union. Import only from Server Components (uses lib/auth →
 * next/headers). The allow-lists live in ./roles.
 */
export async function requireCallRole(allowed: readonly string[]): Promise<CurrentUser> {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (!allowed.includes(me.role)) redirect("/");
  return me;
}
