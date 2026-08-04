/**
 * Data access for the player card. Operational rows go straight to Supabase
 * crm.* (RLS is the hard boundary); the call originate + recording stream go
 * through the Flask adapter (A4) so Tegsoft secrets and the raw phone never
 * reach the browser.
 *
 * Every mutation also appends a crm.audit_log row (actor_id = self) — the
 * RevShare-transparency requirement (plan §0.5). Audit is best-effort: a failed
 * audit never rolls back the user's action, but the primary write must surface
 * its error (so the UI can show ErrorState / RLS-denied messages).
 */

import { createClient } from "@/lib/supabase/client";
import { flaskFetch } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";
import type {
  AssignmentRow,
  AssignStatus,
  CallOutcome,
  CallResult,
  CallRow,
  NoteRow,
  OfferStatusCode,
  ScheduledRow,
} from "./types";

/**
 * A human-readable error for the UI, mapping RLS denials to a plain message.
 * `message` is always the ru copy (source of truth / log text); `key` is set
 * whenever `message` is OUR OWN copy (not a raw Supabase/Postgres error,
 * which isn't translatable) so the client caller can render `t(key, vars)`
 * instead. Pure data-layer module — no useT() here (see lib/i18n/README.md).
 */
export class CardDataError extends Error {
  readonly key?: MessageKey;
  readonly vars?: Record<string, string | number>;
  constructor(message: string, key?: MessageKey, vars?: Record<string, string | number>) {
    super(message);
    this.name = "CardDataError";
    this.key = key;
    this.vars = vars;
  }
}

interface SupabaseError {
  message?: string;
  code?: string;
}

/**
 * Resolve a caught error (from any of this module's functions) to a
 * translated, display-ready message. Takes `t` as a parameter rather than
 * calling useT() itself — this file is not a hook, so the client component
 * (which does call useT()) passes it in at the catch site:
 *
 *   catch (e) { setError(cardErrorText(e, t, "card.common.error")); }
 */
export function cardErrorText(
  e: unknown,
  t: (key: MessageKey, vars?: Record<string, string | number>) => string,
  fallbackKey: MessageKey,
): string {
  if (e instanceof CardDataError) return e.key ? t(e.key, e.vars) : e.message;
  if (e instanceof Error) return e.message;
  return t(fallbackKey);
}

function toFriendly(err: SupabaseError | null, fallback: string, fallbackKey: MessageKey): CardDataError {
  const raw = err?.message ?? "";
  if (/row-level security|violates row-level/i.test(raw)) {
    return new CardDataError(
      "Недостаточно прав: этот игрок не в вашей зоне (не назначен вам). Действие отклонено политикой доступа.",
      "card.error.rlsDenied",
    );
  }
  // A raw backend message (Postgres/Supabase) isn't ours to translate.
  return new CardDataError(raw || fallback, raw ? undefined : fallbackKey);
}

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

export interface OperationalData {
  notes: NoteRow[];
  calls: CallRow[];
  scheduled: ScheduledRow[];
  assignments: AssignmentRow[];
}

/** Load all crm.* rows the caller may see for one player (RLS-scoped). */
export async function fetchOperational(playerId: number): Promise<OperationalData> {
  const supabase = createClient();
  const crm = supabase.schema("crm");

  const [notes, calls, scheduled, assignments] = await Promise.all([
    crm
      .from("notes")
      .select("*")
      .eq("casino_player_id", playerId)
      .order("created_at", { ascending: false }),
    crm
      .from("calls")
      .select("*")
      .eq("casino_player_id", playerId)
      .order("started_at", { ascending: false }),
    crm
      .from("scheduled_calls")
      .select("*")
      .eq("casino_player_id", playerId)
      .order("scheduled_at", { ascending: true }),
    crm
      .from("player_assignments")
      .select("id, casino_player_id, operator_id, status, last_touch_at")
      .eq("casino_player_id", playerId),
  ]);

  const firstError = notes.error ?? calls.error ?? scheduled.error ?? assignments.error;
  if (firstError)
    throw toFriendly(
      firstError,
      "Не удалось загрузить операционные данные.",
      "card.error.operationalLoadFailed",
    );

  return {
    notes: (notes.data as NoteRow[]) ?? [],
    calls: (calls.data as CallRow[]) ?? [],
    scheduled: (scheduled.data as ScheduledRow[]) ?? [],
    assignments: (assignments.data as AssignmentRow[]) ?? [],
  };
}

/**
 * Resolve author/operator uuids → display names. RLS may hide co-operators from
 * an operator (crm_users select = self + admin/head scope), so unresolved ids
 * fall back to a stable placeholder — the note/call is still shown (ТЗ п.4:
 * прозрачность), only the name degrades.
 */
export async function resolveNames(ids: string[]): Promise<Map<string, string>> {
  const unique = Array.from(new Set(ids.filter(Boolean)));
  const out = new Map<string, string>();
  if (unique.length === 0) return out;

  const supabase = createClient();
  const { data } = await supabase
    .schema("crm")
    .from("crm_users")
    .select("id, full_name")
    .in("id", unique);

  for (const row of (data as { id: string; full_name: string }[]) ?? []) {
    out.set(row.id, row.full_name);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Audit (best-effort)
// ---------------------------------------------------------------------------

export async function writeAudit(
  actorId: string,
  action: string,
  entity: string | null,
  entityId: string | null,
  meta: Record<string, unknown> = {},
): Promise<void> {
  try {
    const supabase = createClient();
    await supabase
      .schema("crm")
      .from("audit_log")
      .insert({ actor_id: actorId, action, entity, entity_id: entityId, meta });
  } catch {
    // Audit is best-effort; never block the user's action on it.
  }
}

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

export async function addNote(input: {
  playerId: number;
  authorId: string;
  content: string;
  tags: string[];
  linkedOffer: string | null;
}): Promise<NoteRow> {
  const supabase = createClient();
  const { data, error } = await supabase
    .schema("crm")
    .from("notes")
    .insert({
      casino_player_id: input.playerId,
      author_id: input.authorId,
      content: input.content,
      tags: input.tags,
      linked_offer: input.linkedOffer,
    })
    .select("*")
    .single();

  if (error || !data) throw toFriendly(error, "Не удалось сохранить заметку.", "card.error.noteSaveFailed");
  await writeAudit(input.authorId, "note", "player", String(input.playerId), {
    note_id: (data as NoteRow).id,
    tags: input.tags,
    linked_offer: input.linkedOffer,
  });
  return data as NoteRow;
}

export async function updateNote(input: {
  id: string;
  authorId: string;
  playerId: number;
  content: string;
  tags: string[];
  linkedOffer: string | null;
}): Promise<NoteRow> {
  const supabase = createClient();
  const { data, error } = await supabase
    .schema("crm")
    .from("notes")
    .update({ content: input.content, tags: input.tags, linked_offer: input.linkedOffer })
    .eq("id", input.id)
    .select("*")
    .single();

  if (error || !data) throw toFriendly(error, "Не удалось изменить заметку.", "card.error.noteEditFailed");
  await writeAudit(input.authorId, "note_edit", "player", String(input.playerId), {
    note_id: input.id,
  });
  return data as NoteRow;
}

export async function deleteNote(input: {
  id: string;
  actorId: string;
  playerId: number;
}): Promise<void> {
  const supabase = createClient();
  const { error } = await supabase.schema("crm").from("notes").delete().eq("id", input.id);
  if (error) throw toFriendly(error, "Не удалось удалить заметку.", "card.error.noteDeleteFailed");
  await writeAudit(input.actorId, "note_delete", "player", String(input.playerId), {
    note_id: input.id,
  });
}

// ---------------------------------------------------------------------------
// Calls — originate (Flask) + manual outcome (Supabase upsert)
// ---------------------------------------------------------------------------

export interface OriginateResult {
  call_ref: string;
  player_phone_masked: string;
}

/**
 * Решение отдела по офферу → retention.player_offers (ClickHouse) через Flask.
 *
 * Пишем ТУДА ЖЕ, куда старый борд (POST /offer/<pid>), а не в crm.notes: иначе
 * бейдж статуса на /desk и в HTML-карточке не увидит решение, принятое в SPA.
 * Таблица живёт в ClickHouse, поэтому путь только через API — напрямую из
 * браузера туда нельзя.
 */
export async function saveOffer(input: {
  playerId: number;
  status: OfferStatusCode;
  offerText: string;
  note: string;
}): Promise<{ player_id: number; status: string }> {
  return flaskFetch<{ player_id: number; status: string }>(
    `/api/v1/players/${input.playerId}/offer`,
    {
      method: "POST",
      body: { status: input.status, offer_text: input.offerText, note: input.note },
    },
  );
}

/** Ask the Flask adapter to place the call. Returns the provider ref + masked phone. */
export async function originateCall(playerId: number): Promise<OriginateResult> {
  return flaskFetch<OriginateResult>("/api/v1/calls/originate", {
    method: "POST",
    body: { casino_player_id: playerId },
  });
}

/**
 * Record the manual call outcome (2-click result). The Tegsoft webhook (A4)
 * writes crm.calls via service_role; in dev (MockProvider, no webhook) it will
 * not have fired, so we upsert: update the row for this provider_ref if present,
 * else insert a fresh one (operator_id = self, enforced by RLS).
 */
export async function saveCallOutcome(input: {
  playerId: number;
  operatorId: string;
  outcome: CallOutcome;
  result: CallResult | null;
  providerRef: string | null;
}): Promise<CallRow> {
  const supabase = createClient();
  const crm = supabase.schema("crm");

  let existing: { id: string } | null = null;
  if (input.providerRef) {
    const { data } = await crm
      .from("calls")
      .select("id")
      .eq("provider_ref", input.providerRef)
      .eq("operator_id", input.operatorId)
      .limit(1)
      .maybeSingle();
    existing = (data as { id: string } | null) ?? null;
  }

  let row: CallRow;
  if (existing) {
    const { data, error } = await crm
      .from("calls")
      .update({ outcome: input.outcome, result: input.result })
      .eq("id", existing.id)
      .select("*")
      .single();
    if (error || !data)
      throw toFriendly(error, "Не удалось сохранить исход звонка.", "card.error.callOutcomeSaveFailed");
    row = data as CallRow;
  } else {
    const { data, error } = await crm
      .from("calls")
      .insert({
        casino_player_id: input.playerId,
        operator_id: input.operatorId,
        outcome: input.outcome,
        result: input.result,
        provider_ref: input.providerRef,
      })
      .select("*")
      .single();
    if (error || !data)
      throw toFriendly(error, "Не удалось сохранить исход звонка.", "card.error.callOutcomeSaveFailed");
    row = data as CallRow;
  }

  await writeAudit(input.operatorId, "call_outcome", "player", String(input.playerId), {
    call_id: row.id,
    outcome: input.outcome,
    result: input.result,
    provider_ref: input.providerRef,
  });

  // Reflect the touch on the assignment (best-effort; operator may edit own row).
  await touchAssignment({
    playerId: input.playerId,
    operatorId: input.operatorId,
    status: input.outcome === "answered" ? "answered" : "no_answer",
  });

  return row;
}

/** Update assign status + last_touch_at after a call (best-effort; ignores RLS denial). */
export async function touchAssignment(input: {
  playerId: number;
  operatorId: string;
  status: AssignStatus;
}): Promise<void> {
  try {
    const supabase = createClient();
    await supabase
      .schema("crm")
      .from("player_assignments")
      .update({ status: input.status, last_touch_at: new Date().toISOString() })
      .eq("casino_player_id", input.playerId)
      .eq("operator_id", input.operatorId);
  } catch {
    // Not fatal — the call itself is already recorded.
  }
}

// ---------------------------------------------------------------------------
// Scheduled calls
// ---------------------------------------------------------------------------

export async function addSchedule(input: {
  playerId: number;
  operatorId: string;
  scheduledAt: string;
  comment: string | null;
  bySystem?: boolean;
}): Promise<ScheduledRow> {
  const supabase = createClient();
  const { data, error } = await supabase
    .schema("crm")
    .from("scheduled_calls")
    .insert({
      casino_player_id: input.playerId,
      operator_id: input.operatorId,
      scheduled_at: input.scheduledAt,
      comment: input.comment,
      by_system: input.bySystem ?? false,
    })
    .select("*")
    .single();

  if (error || !data)
    throw toFriendly(error, "Не удалось запланировать звонок.", "card.error.scheduleSaveFailed");
  await writeAudit(input.operatorId, "schedule", "player", String(input.playerId), {
    scheduled_call_id: (data as ScheduledRow).id,
    scheduled_at: input.scheduledAt,
  });
  return data as ScheduledRow;
}

// ---------------------------------------------------------------------------
// Recording stream (Flask, RECORDING_ROLES) → object URL for <audio>
// ---------------------------------------------------------------------------

/** Fetch the recording as a blob URL (auth header can't ride a plain <audio src>). */
export async function fetchRecordingUrl(callId: string): Promise<string> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const base = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";
  const res = await fetch(`${base}/api/v1/calls/${callId}/recording`, {
    headers: session?.access_token
      ? { Authorization: `Bearer ${session.access_token}` }
      : undefined,
  });
  if (!res.ok) {
    throw res.status === 404
      ? new CardDataError("У звонка нет записи.", "card.error.recordingNotFound")
      : new CardDataError(`Запись недоступна (${res.status}).`, "card.error.recordingUnavailable", {
          status: res.status,
        });
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}
