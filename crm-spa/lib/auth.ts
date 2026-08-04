import { createClient } from "./supabase/server";
import type { CurrentUser } from "./types";

/**
 * SERVER-ONLY auth helpers. Import from Server Components, Route Handlers and
 * Server Actions (this file transitively imports next/headers via the server
 * client, which makes it unusable — and un-bundleable — on the client).
 *
 * For B2/B3/B4/C agents:
 *   - Get the signed-in user + role in any server component:
 *       import { getCurrentUser } from "@/lib/auth";
 *       const me = await getCurrentUser();      // null if not signed in
 *   - On the client, read the same object from context instead:
 *       import { useRole } from "@/lib/role-context";
 *       const me = useRole();                   // throws if outside (app) layout
 */

/**
 * Resolve the current user's profile: verifies the Supabase session, then reads
 * the crm.crm_users row (role, department, affiliate_code, ...) under RLS.
 * Returns null when there is no valid session or no matching profile row.
 */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const { data, error } = await supabase
    .schema("crm")
    .from("crm_users")
    .select("id, full_name, role, department, affiliate_code, is_active")
    .eq("id", user.id)
    .single();

  if (error || !data) return null;
  return data as CurrentUser;
}

/**
 * Return the raw Supabase access token for the current request, or null.
 * Server components that need to call the Flask analytics API can pass this to
 * flaskFetchWithToken() from lib/api. (Client components should just use
 * flaskFetch(), which resolves the token itself.)
 */
export async function getAccessToken(): Promise<string | null> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}
