import { NextResponse } from "next/server";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { CurrentUser } from "./types";

/**
 * Server-only helpers shared by the admin route handlers (app/api/admin/*).
 * These endpoints use the service-role client for privileged GoTrue + crm.*
 * writes, so they MUST authorise the caller themselves (via their RLS-bound
 * session) and MUST record every action in crm.audit_log (RevShare transparency).
 */

/**
 * Standard JSON error with the given HTTP status (matches route success shape).
 *
 * `code` is an optional MACHINE-readable identifier (e.g. "user_not_found")
 * for the small set of fixed, non-interpolated failure messages — the client
 * (UsersAdmin.tsx) maps it through admin.error.* to show the message in the
 * caller's locale, falling back to `message` (today's Russian server text)
 * when no code is set or the code is unmapped. Dynamic messages that embed a
 * raw Supabase/GoTrue error string are intentionally left without a code —
 * there is no fixed set of those to translate, so they keep rendering as-is.
 */
export function fail(message: string, status: number, code?: string): NextResponse {
  return NextResponse.json({ ok: false, error: message, code }, { status });
}

/** Standard JSON success. */
export function ok<T>(data?: T): NextResponse {
  return NextResponse.json({ ok: true, data });
}

/**
 * Write one audit row as the acting user. Uses the service-role client (RLS
 * bypassed) but always stamps actor_id = the authenticated caller. Never throws
 * — a failed audit write is logged but must not break the primary action's
 * response (best-effort; DB is append-only and the primary op already succeeded).
 */
export async function auditLog(
  admin: SupabaseClient,
  actorId: string,
  action: string,
  entity: string | null,
  entityId: string | null,
  meta: Record<string, unknown>,
): Promise<void> {
  const { error } = await admin
    .schema("crm")
    .from("audit_log")
    .insert({ actor_id: actorId, action, entity, entity_id: entityId, meta });
  if (error) {
    // eslint-disable-next-line no-console
    console.error("audit_log insert failed:", action, error.message);
  }
}

/** Minimal target profile needed to authorise management actions. */
export interface TargetProfile {
  id: string;
  role: CurrentUser["role"];
  department: CurrentUser["department"];
}

/** Load a target user's role/department via the service-role client (or null). */
export async function loadTarget(
  admin: SupabaseClient,
  id: string,
): Promise<TargetProfile | null> {
  const { data } = await admin
    .schema("crm")
    .from("crm_users")
    .select("id, role, department")
    .eq("id", id)
    .single();
  return (data as TargetProfile) ?? null;
}
