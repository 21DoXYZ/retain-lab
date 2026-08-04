import { createClient } from "@/lib/supabase/client";

/**
 * Thrown by downloadSegment() on a non-OK response. `code` is a stable,
 * machine-readable reason (not a human string) so the caller can translate it
 * via useT() — this module has no React context of its own to call useT() in.
 */
export class DownloadError extends Error {
  constructor(
    public code: "forbidden" | "http_error",
    public status: number,
  ) {
    super(code);
    this.name = "DownloadError";
  }
}

/**
 * Download the current player segment as CSV/XLSX (agent F1). The Flask export
 * endpoints require the Supabase Bearer token, which a plain <a href> cannot
 * carry — so we fetch the file as a blob and trigger a client-side download,
 * preserving the server-provided filename (Content-Disposition).
 *
 * `query` is the segment filter string (same params as the list), WITHOUT sort
 * or page — the export always covers the whole segment, matching the board.
 */
export async function downloadSegment(fmt: "csv" | "xlsx", query: string): Promise<void> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const base = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";
  const res = await fetch(`${base}/api/v1/players/export.${fmt}?${query}`, {
    headers: session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : undefined,
  });
  if (!res.ok) {
    throw new DownloadError(res.status === 403 ? "forbidden" : "http_error", res.status);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const name = match?.[1] ?? `players.${fmt}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
