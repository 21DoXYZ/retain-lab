import { createBrowserClient } from "@supabase/ssr";

/**
 * Browser (client component) Supabase client — reads/writes the auth session
 * from document.cookie so it stays in sync with the server client and the
 * proxy session refresh. Verified against @supabase/ssr 0.12 for Next.js 16.
 *
 * Usage (any "use client" component):
 *   import { createClient } from "@/lib/supabase/client";
 *   const supabase = createClient();
 *   const { data: { session } } = await supabase.auth.getSession();
 *   // crm.* tables are exposed via PostgREST — use .schema("crm"):
 *   const { data } = await supabase.schema("crm").from("notes").select("*");
 *
 * The instance is memoised so repeated calls share one GoTrue client.
 */
import type { SupabaseClient } from "@supabase/supabase-js";

let browserClient: SupabaseClient | undefined;

export function createClient(): SupabaseClient {
  if (browserClient) return browserClient;
  browserClient = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
  return browserClient;
}
