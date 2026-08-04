/**
 * Client-side assignment mutations for the pool + queue (B2). Run through the
 * RLS-bound browser Supabase client, so the database is the hard authority:
 *   - assign / transfer / remove / clear are gated by the assign_* policies
 *     (0002) — is_admin between departments, head_department within its own.
 *   - every mutation writes one crm.audit_log row (RevShare transparency,
 *     ТЗ КЦ п.1.3) via audit_insert (actor_id = auth.uid()).
 *
 * History (notes/calls) is keyed by casino_player_id and is deliberately never
 * touched here, so moving/removing an assignment keeps the full player history
 * (ТЗ КЦ п.2.3).
 */

import { createClient } from "@/lib/supabase/client";
import type { MessageKey } from "@/lib/i18n";

export type AssignMode = "split" | "all";

export interface MutationResult {
  ok: boolean;
  /** Human-readable (ru) error — a raw backend message, or one of our own
   * copy strings mirrored below in `errorKey`. */
  error?: string;
  /**
   * i18n key for `error`, set only when `error` is OUR OWN copy (not a raw
   * Supabase/Postgres message, which isn't translatable — see
   * lib/i18n/README.md). Pure data-layer module — no useT() here; the
   * client caller (PoolBoard/QueueBoard) resolves the key at render time,
   * falling back to `error` when absent.
   */
  errorKey?: MessageKey;
  affected?: number;
}

/** Error from an unexpected (non-Supabase) throw inside a mutation. */
function errInfo(e: unknown): { error: string; errorKey?: MessageKey } {
  if (e instanceof Error) return { error: e.message };
  return { error: "Не удалось выполнить операцию", errorKey: "players.pool.error.opFailed" };
}

const ASSIGN_CONFLICT = "casino_player_id,operator_id";

/** Append one audit row as the acting user (best-effort; never throws). */
async function writeAudit(
  actorId: string,
  action: string,
  entity: string | null,
  entityId: string | null,
  meta: Record<string, unknown>,
): Promise<void> {
  try {
    const supabase = createClient();
    await supabase
      .schema("crm")
      .from("audit_log")
      .insert({ actor_id: actorId, action, entity, entity_id: entityId, meta });
  } catch {
    // Audit is append-only best-effort; the primary op already succeeded.
  }
}

/** Round-robin players across operators (300 / 3 → ~100 each). */
function splitAssignments(
  playerIds: number[],
  operatorIds: string[],
  actorId: string,
): { casino_player_id: number; operator_id: string; assigned_by: string }[] {
  return playerIds.map((pid, i) => ({
    casino_player_id: pid,
    operator_id: operatorIds[i % operatorIds.length],
    assigned_by: actorId,
  }));
}

/** Cartesian: give every selected player to every selected operator. */
function fanOutAssignments(
  playerIds: number[],
  operatorIds: string[],
  actorId: string,
): { casino_player_id: number; operator_id: string; assigned_by: string }[] {
  const rows: { casino_player_id: number; operator_id: string; assigned_by: string }[] = [];
  for (const opId of operatorIds) {
    for (const pid of playerIds) {
      rows.push({ casino_player_id: pid, operator_id: opId, assigned_by: actorId });
    }
  }
  return rows;
}

/**
 * Assign selected players to operators. `split` distributes them round-robin;
 * `all` gives the whole batch to each operator (ТЗ КЦ п.2.1). Duplicates
 * (player already on that operator) are ignored, not errored.
 */
export async function assignPlayers(args: {
  actorId: string;
  playerIds: number[];
  operatorIds: string[];
  mode: AssignMode;
}): Promise<MutationResult> {
  const { actorId, playerIds, operatorIds, mode } = args;
  if (playerIds.length === 0)
    return { ok: false, error: "Не выбраны игроки", errorKey: "players.pool.error.noPlayersSelected" };
  if (operatorIds.length === 0)
    return { ok: false, error: "Не выбраны операторы", errorKey: "players.pool.error.noOperatorsSelected" };

  const rows =
    mode === "split"
      ? splitAssignments(playerIds, operatorIds, actorId)
      : fanOutAssignments(playerIds, operatorIds, actorId);

  try {
    const supabase = createClient();
    const { error } = await supabase
      .schema("crm")
      .from("player_assignments")
      .upsert(rows, { onConflict: ASSIGN_CONFLICT, ignoreDuplicates: true });
    if (error) return { ok: false, error: error.message };
  } catch (e) {
    return { ok: false, ...errInfo(e) };
  }

  await writeAudit(actorId, "assign", "assignment", null, {
    mode,
    operator_ids: operatorIds,
    player_count: playerIds.length,
    player_ids: playerIds,
  });
  return { ok: true, affected: rows.length };
}

/** Remove specific players from ONE operator's queue (по одному и пачкой). */
export async function removeFromOperator(args: {
  actorId: string;
  operatorId: string;
  playerIds: number[];
}): Promise<MutationResult> {
  const { actorId, operatorId, playerIds } = args;
  if (playerIds.length === 0)
    return { ok: false, error: "Не выбраны игроки", errorKey: "players.pool.error.noPlayersSelected" };
  try {
    const supabase = createClient();
    const { error } = await supabase
      .schema("crm")
      .from("player_assignments")
      .delete()
      .eq("operator_id", operatorId)
      .in("casino_player_id", playerIds);
    if (error) return { ok: false, error: error.message };
  } catch (e) {
    return { ok: false, ...errInfo(e) };
  }
  await writeAudit(actorId, "unassign", "assignment", operatorId, {
    operator_id: operatorId,
    player_count: playerIds.length,
    player_ids: playerIds,
  });
  return { ok: true, affected: playerIds.length };
}

/**
 * Отвязать ВСЕХ операторов от выбранных игроков (массовая отвязка — запрос
 * клиента). Удаляет все их привязки в crm.player_assignments; RLS (assign_delete)
 * сам ограничивает, что реально удалится (super_admin/глава ретеншена — любые;
 * руковод КЦ — только по своему отделу). Заметки/звонки игрока остаются.
 */
export async function unassignAll(args: {
  actorId: string;
  playerIds: number[];
}): Promise<MutationResult> {
  const { actorId, playerIds } = args;
  if (playerIds.length === 0)
    return { ok: false, error: "Не выбраны игроки", errorKey: "players.pool.error.noPlayersSelected" };
  try {
    const supabase = createClient();
    const { error } = await supabase
      .schema("crm")
      .from("player_assignments")
      .delete()
      .in("casino_player_id", playerIds);
    if (error) return { ok: false, error: error.message };
  } catch (e) {
    return { ok: false, ...errInfo(e) };
  }
  await writeAudit(actorId, "unassign_all", "assignment", null, {
    player_count: playerIds.length,
    player_ids: playerIds,
  });
  return { ok: true, affected: playerIds.length };
}

/**
 * Move players from one operator to another (or to another department's
 * operator). Notes/calls stay with the player. Delete-then-insert so the
 * (player, operator) unique constraint never blocks the move.
 */
export async function transferPlayers(args: {
  actorId: string;
  playerIds: number[];
  fromOperatorId: string;
  toOperatorId: string;
}): Promise<MutationResult> {
  const { actorId, playerIds, fromOperatorId, toOperatorId } = args;
  if (playerIds.length === 0)
    return { ok: false, error: "Не выбраны игроки", errorKey: "players.pool.error.noPlayersSelected" };
  if (fromOperatorId === toOperatorId)
    return {
      ok: false,
      error: "Оператор-источник и получатель совпадают",
      errorKey: "players.pool.error.sameOperator",
    };
  try {
    const supabase = createClient();
    const rows = playerIds.map((pid) => ({
      casino_player_id: pid,
      operator_id: toOperatorId,
      assigned_by: actorId,
    }));
    const { error: insErr } = await supabase
      .schema("crm")
      .from("player_assignments")
      .upsert(rows, { onConflict: ASSIGN_CONFLICT, ignoreDuplicates: true });
    if (insErr) return { ok: false, error: insErr.message };

    const { error: delErr } = await supabase
      .schema("crm")
      .from("player_assignments")
      .delete()
      .eq("operator_id", fromOperatorId)
      .in("casino_player_id", playerIds);
    if (delErr) return { ok: false, error: delErr.message };
  } catch (e) {
    return { ok: false, ...errInfo(e) };
  }
  await writeAudit(actorId, "reassign", "assignment", null, {
    from_operator: fromOperatorId,
    to_operator: toOperatorId,
    player_count: playerIds.length,
    player_ids: playerIds,
  });
  return { ok: true, affected: playerIds.length };
}

/** Clear an operator's whole queue (ТЗ КЦ п.2.3 «очистить очередь целиком»). */
export async function clearQueue(args: {
  actorId: string;
  operatorId: string;
}): Promise<MutationResult> {
  const { actorId, operatorId } = args;
  try {
    const supabase = createClient();
    const { error, count } = await supabase
      .schema("crm")
      .from("player_assignments")
      .delete({ count: "exact" })
      .eq("operator_id", operatorId);
    if (error) return { ok: false, error: error.message };
    await writeAudit(actorId, "clear_queue", "operator", operatorId, {
      operator_id: operatorId,
      removed: count ?? null,
    });
    return { ok: true, affected: count ?? 0 };
  } catch (e) {
    return { ok: false, ...errInfo(e) };
  }
}

/**
 * Operator КЦ requests a hand-off to WhatsApp (ТЗ КЦ п.2.4 — «передать в
 * WhatsApp» уходит на подтверждение главе WA). Recorded as an audit request;
 * the head-of-WA confirmation UI is a follow-up (no pending-transfer table yet).
 */
export async function requestWaTransfer(args: {
  actorId: string;
  playerId: number;
}): Promise<MutationResult> {
  const { actorId, playerId } = args;
  await writeAudit(actorId, "wa_transfer_request", "player", String(playerId), {
    player_id: playerId,
    status: "pending",
  });
  return { ok: true };
}
