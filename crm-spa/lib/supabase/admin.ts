import { createClient as createSupabaseClient } from "@supabase/supabase-js";

/**
 * Service-role Supabase client — SERVER ONLY. Bypasses RLS and unlocks the
 * GoTrue admin API (auth.admin.createUser / updateUserById / deleteUser).
 *
 * NEVER import this from a client component: the service-role key must never
 * reach the browser. It is read from SUPABASE_SERVICE_ROLE_KEY (no
 * NEXT_PUBLIC_ prefix), so Next.js keeps it on the server. It is only used by
 * the admin route handlers under app/api/admin/*, which authorise the caller
 * (via their own RLS-bound session) BEFORE performing any privileged write.
 *
 * Because RLS is bypassed, always scope crm.* access explicitly and re-check
 * permissions in application code (see lib/permissions.ts).
 */
export function createAdminClient() {
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!serviceKey) {
    throw new Error(
      "SUPABASE_SERVICE_ROLE_KEY is not set — required for admin operations. " +
        "Add it to crm-spa/.env.local (get it from `supabase status -o env`).",
    );
  }

  return createSupabaseClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    serviceKey,
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
    },
  );
}
