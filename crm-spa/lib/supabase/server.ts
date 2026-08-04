import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * Server (Server Component / Route Handler / Server Action) Supabase client,
 * bound to the request cookie jar. In Next.js 16 `cookies()` is async, so this
 * factory is async — always `await createClient()`.
 *
 * Verified against @supabase/ssr 0.12 + Next.js 16 App Router (Context7).
 *
 * Usage (server component or route handler):
 *   import { createClient } from "@/lib/supabase/server";
 *   const supabase = await createClient();
 *   const { data: { user } } = await supabase.auth.getUser();
 *
 * RLS applies as the signed-in user, so this client only ever sees rows the
 * caller is allowed to see (defense-in-depth with the app-level checks).
 * Writing cookies from a Server Component throws; that write is a no-op here
 * because the proxy (proxy.ts) already refreshes the session on every request.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from a Server Component — cookie writes are not allowed
            // here. Safe to ignore: proxy.ts keeps the session fresh.
          }
        },
      },
    },
  );
}
