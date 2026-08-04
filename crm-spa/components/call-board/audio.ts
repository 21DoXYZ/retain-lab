import { createClient } from "@/lib/supabase/client";

/**
 * Thrown by fetchCallAudio() on a non-OK response. `code` is a stable, machine-
 * readable reason (not a human string) so the caller translates it via useT()
 * (this module holds no React context). Same contract as players/download.ts.
 */
export class AudioError extends Error {
  constructor(
    public code: "forbidden" | "not_found" | "http_error",
    public status: number,
  ) {
    super(code);
    this.name = "AudioError";
  }
}

/**
 * Stream a call recording as a blob object-URL (§10.3 / §10.11). A plain
 * <audio src> cannot carry the Supabase Bearer token the Flask audio endpoint
 * requires, so we fetch the WAV as a blob and hand back an object URL the caller
 * pins to <audio>. The caller MUST URL.revokeObjectURL() it on cleanup.
 *
 * Note: the endpoint is gated to MANAGE|ADMIN in api/call_analysis.py — operators
 * and translation_reviewer will get 403 (surfaced as AudioError "forbidden").
 */
export async function fetchCallAudio(callId: string): Promise<string> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const base = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";
  const res = await fetch(`${base}/api/v1/call-analysis/calls/${callId}/audio`, {
    headers: session?.access_token
      ? { Authorization: `Bearer ${session.access_token}` }
      : undefined,
  });
  if (!res.ok) {
    const code =
      res.status === 403 ? "forbidden" : res.status === 404 ? "not_found" : "http_error";
    throw new AudioError(code, res.status);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}
