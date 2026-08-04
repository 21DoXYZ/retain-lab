import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Session refresh for the Next.js 16 Proxy (proxy.ts — the renamed Middleware).
 * Follows the canonical @supabase/ssr pattern: create a request-bound client,
 * call getUser() to refresh the token, and carefully copy any rotated auth
 * cookies onto the response so the browser and server stay in sync.
 *
 * Returns both the response (with refreshed cookies) and the user so the proxy
 * can make its redirect decision. Do NOT run other code between createServerClient
 * and getUser() — it can cause hard-to-debug random logouts.
 */
export async function updateSession(
  request: NextRequest,
): Promise<{ response: NextResponse; user: unknown }> {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  return { response, user };
}

/**
 * Build a redirect response that preserves the auth cookies from `source`
 * (needed after updateSession rotated them — otherwise the user can be logged
 * out on the very redirect that was meant to protect the route).
 */
export function redirectPreservingCookies(
  request: NextRequest,
  pathname: string,
  source: NextResponse,
  searchParams?: Record<string, string>,
): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = pathname;
  url.search = "";
  if (searchParams) {
    for (const [key, value] of Object.entries(searchParams)) {
      url.searchParams.set(key, value);
    }
  }
  const redirect = NextResponse.redirect(url);
  source.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
  return redirect;
}
