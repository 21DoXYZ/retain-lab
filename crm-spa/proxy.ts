import { NextResponse, type NextRequest } from "next/server";
import {
  updateSession,
  redirectPreservingCookies,
} from "@/lib/supabase/proxy";

/**
 * Next.js 16 Proxy (formerly middleware.ts — renamed in v16, same purpose).
 * Two jobs on every matched request:
 *   1. Refresh the Supabase session cookies (updateSession) so tokens never go
 *      stale between the browser and the server client.
 *   2. Optimistic route guard: send signed-out users to /login (with ?next=),
 *      and bounce signed-in users away from /login. This is a fast first line;
 *      the real authorization happens in the (app) layout (getCurrentUser) and
 *      in each Route Handler — never trust the proxy alone (plan §0.4).
 *
 * /api/* is refreshed but never redirected: those handlers authorise callers
 * themselves and must be free to return 401/403 JSON.
 */

/** Path prefixes reachable without a session. */
const PUBLIC_PATHS = ["/login"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const { response, user } = await updateSession(request);
  const { pathname } = request.nextUrl;

  // API routes: refresh only, let the handler decide auth.
  if (pathname.startsWith("/api")) return response;

  if (!user && !isPublic(pathname)) {
    return redirectPreservingCookies(request, "/login", response, {
      next: pathname,
    });
  }

  if (user && pathname === "/login") {
    return redirectPreservingCookies(request, "/", response);
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Run on every route except static assets and image files, so both page
     * navigations and Server Actions keep a fresh session.
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
