/**
 * SERVER-ONLY data loaders for the operator queue (/queue) and the assignment
 * pool (/pool). Imported only from the server page components in this folder.
 *
 * Reads operational state from crm.* through the RLS-bound server client, so
 * every query already only sees rows the caller may see (operator → own
 * assignments; head → own department). The single privileged read is
 * resolveOperatorNames(), a narrowly-scoped service-role lookup that turns
 * co-assignee operator ids into display names — RLS forbids an operator from
 * reading peers' crm_users rows, but the "также у: Мехмет, Айше" transparency
 * requirement (ТЗ КЦ п.2.2) needs exactly those names for players they share.
 *
 * Priorities (sort key + action/bonus hints) come from Flask
 * GET /api/v1/queue/priorities; if Flask is unreachable the queue still renders
 * from Supabase data and flags `prioritiesDegraded`.
 */

import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { getAccessToken } from "@/lib/auth";
import { flaskFetchWithToken } from "@/lib/api";
import { resolveLocale } from "@/lib/i18n/server";
import { getMessages } from "@/lib/i18n/messages";
import type { CurrentUser } from "@/lib/types";
import type {
  DirectoryInfo,
  OperatorOption,
  OperatorQueueData,
  PoolData,
  PoolRow,
  PriorityInfo,
  QueueRow,
  ScheduledInfo,
  TodayCall,
} from "./types";
import type { AssignStatus, CallOutcome, SchedStatus } from "./labels";

const TZ = "Europe/Istanbul";
const MAX_PRIORITY_IDS = 500;

/** yyyy-mm-dd for a date, in Europe/Istanbul (for "today" comparisons). */
function istanbulDayKey(value: Date | string): string {
  const d = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

const DIRECTORY_COLS =
  "casino_player_id, display_id, affiliate_code, country, vip_level, lifecycle, is_valid";

/**
 * Localized placeholder for a co-assignee/assignee name that RLS hid (server
 * component — no useT() here, so resolve the cookie locale directly).
 */
async function operatorFallbackName(): Promise<string> {
  const locale = await resolveLocale();
  return getMessages(locale)["players.queue.operatorFallbackName"];
}

/** Resolve operator ids → full names via the service-role client (names only). */
async function resolveOperatorNames(
  ids: string[],
): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  if (ids.length === 0) return map;
  const admin = createAdminClient();
  const { data } = await admin
    .schema("crm")
    .from("crm_users")
    .select("id, full_name")
    .in("id", ids);
  for (const u of data ?? []) map.set(u.id as string, u.full_name as string);
  return map;
}

/** Fetch Flask queue priorities for the given ids; [] + degraded on failure. */
async function loadPriorities(
  playerIds: number[],
): Promise<{ map: Map<number, PriorityInfo>; degraded: boolean }> {
  const map = new Map<number, PriorityInfo>();
  if (playerIds.length === 0) return { map, degraded: false };
  try {
    const token = await getAccessToken();
    const ids = playerIds.slice(0, MAX_PRIORITY_IDS).join(",");
    const res = await flaskFetchWithToken<{ items: PriorityInfo[] }>(
      `/api/v1/queue/priorities?ids=${ids}`,
      token,
    );
    for (const item of res.items ?? []) map.set(item.player_id, item);
    return { map, degraded: false };
  } catch {
    // Flask down / JWT mismatch — queue still works without priority hints.
    return { map, degraded: true };
  }
}

/**
 * Build the operator's enriched queue, sorted with the day plan on top
 * (overdue first, then today), then by Flask priority DESC.
 */
export async function loadOperatorQueue(
  me: CurrentUser,
): Promise<OperatorQueueData> {
  const supabase = await createClient();

  const { data: assigns } = await supabase
    .schema("crm")
    .from("player_assignments")
    .select("id, casino_player_id, status, last_touch_at")
    .eq("operator_id", me.id);

  const base = assigns ?? [];
  if (base.length === 0) {
    return { rows: [], plannedToday: 0, overdue: 0, prioritiesDegraded: false };
  }

  const playerIds = [...new Set(base.map((a) => a.casino_player_id as number))];
  const nowMs = Date.now();
  const todayKey = istanbulDayKey(new Date());

  const [
    { data: dir },
    { data: notes },
    { data: calls },
    { data: sched },
    { data: coRows },
    { map: priorityMap, degraded },
  ] = await Promise.all([
    supabase
      .schema("crm")
      .from("player_directory")
      .select(DIRECTORY_COLS)
      .in("casino_player_id", playerIds),
    supabase
      .schema("crm")
      .from("notes")
      .select("casino_player_id, created_at")
      .in("casino_player_id", playerIds),
    supabase
      .schema("crm")
      .from("calls")
      .select("casino_player_id, operator_id, started_at, outcome")
      .in("casino_player_id", playerIds)
      .order("started_at", { ascending: false }),
    supabase
      .schema("crm")
      .from("scheduled_calls")
      .select("id, casino_player_id, scheduled_at, comment, status, by_system")
      .eq("operator_id", me.id)
      .neq("status", "done"),
    supabase
      .schema("crm")
      .from("player_assignments")
      .select("casino_player_id, operator_id")
      .in("casino_player_id", playerIds),
    loadPriorities(playerIds),
  ]);

  const dirMap = new Map<number, DirectoryInfo>(
    (dir ?? []).map((d) => [d.casino_player_id as number, d as DirectoryInfo]),
  );

  // Notes: count + latest per player.
  const noteCount = new Map<number, number>();
  const noteLatest = new Map<number, string>();
  for (const n of notes ?? []) {
    const pid = n.casino_player_id as number;
    noteCount.set(pid, (noteCount.get(pid) ?? 0) + 1);
    const at = n.created_at as string;
    if (!noteLatest.has(pid) || at > noteLatest.get(pid)!) noteLatest.set(pid, at);
  }

  // Calls: latest per player + today-by-others (needs names).
  const callLatest = new Map<number, string>();
  const todayByOthers = new Map<number, TodayCall[]>();
  const otherOpIds = new Set<string>();
  for (const c of calls ?? []) {
    const pid = c.casino_player_id as number;
    const at = c.started_at as string;
    if (!callLatest.has(pid)) callLatest.set(pid, at); // calls already DESC
    const opId = c.operator_id as string;
    if (opId !== me.id && istanbulDayKey(at) === todayKey) {
      const entry: TodayCall = {
        casino_player_id: pid,
        operator_id: opId,
        operatorName: null,
        started_at: at,
        outcome: c.outcome as CallOutcome,
      };
      const arr = todayByOthers.get(pid) ?? [];
      arr.push(entry);
      todayByOthers.set(pid, arr);
      otherOpIds.add(opId);
    }
  }

  // Co-assignees: other operators sharing each player.
  const coByPlayer = new Map<number, Set<string>>();
  for (const r of coRows ?? []) {
    const opId = r.operator_id as string;
    if (opId === me.id) continue;
    const pid = r.casino_player_id as number;
    const set = coByPlayer.get(pid) ?? new Set<string>();
    set.add(opId);
    coByPlayer.set(pid, set);
    otherOpIds.add(opId);
  }

  const [names, opFallback] = await Promise.all([
    resolveOperatorNames([...otherOpIds]),
    operatorFallbackName(),
  ]);

  // Nearest overdue/today plan per player.
  const schedByPlayer = new Map<number, ScheduledInfo>();
  for (const s of sched ?? []) {
    const pid = s.casino_player_id as number;
    const at = s.scheduled_at as string;
    const info: ScheduledInfo = {
      id: s.id as string,
      scheduled_at: at,
      comment: (s.comment as string) ?? null,
      status: s.status as SchedStatus,
      by_system: Boolean(s.by_system),
      overdue: new Date(at).getTime() < nowMs,
      today: istanbulDayKey(at) === todayKey,
    };
    const existing = schedByPlayer.get(pid);
    if (!existing || at < existing.scheduled_at) schedByPlayer.set(pid, info);
  }

  const rows: QueueRow[] = base.map((a) => {
    const pid = a.casino_player_id as number;
    const lastTouch =
      (a.last_touch_at as string | null) ??
      maxDate(callLatest.get(pid) ?? null, noteLatest.get(pid) ?? null);
    const coIds = coByPlayer.get(pid);
    const coAssignees = coIds
      ? [...coIds].map((id) => names.get(id) ?? opFallback).sort()
      : [];
    const touches = (todayByOthers.get(pid) ?? []).map((t) => ({
      ...t,
      operatorName: names.get(t.operator_id) ?? opFallback,
    }));
    return {
      assignmentId: a.id as string,
      playerId: pid,
      status: a.status as AssignStatus,
      directory: dirMap.get(pid) ?? null,
      priority: priorityMap.get(pid) ?? null,
      lastTouchAt: lastTouch,
      hasNotes: (noteCount.get(pid) ?? 0) > 0,
      notesCount: noteCount.get(pid) ?? 0,
      beatsCasino: false, // reserved — see PriorityInfo note.
      coAssignees,
      scheduled: schedByPlayer.get(pid) ?? null,
      todayTouchesByOthers: touches,
    };
  });

  rows.sort(compareQueueRows);

  const plannedToday = rows.filter((r) => r.scheduled?.today).length;
  const overdue = rows.filter((r) => r.scheduled?.overdue).length;

  return { rows, plannedToday, overdue, prioritiesDegraded: degraded };
}

/** Larger (later) of two ISO date strings, or whichever is non-null. */
function maxDate(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return a > b ? a : b;
}

/**
 * Queue order: overdue plan first (oldest first), then today's plan (by time),
 * then everything else by priority DESC, value DESC, id ASC.
 */
function compareQueueRows(a: QueueRow, b: QueueRow): number {
  const rank = (r: QueueRow): number => {
    if (r.scheduled?.overdue) return 0;
    if (r.scheduled?.today) return 1;
    return 2;
  };
  const ra = rank(a);
  const rb = rank(b);
  if (ra !== rb) return ra - rb;

  if (ra < 2) {
    // both in a plan group — earliest scheduled first
    return (a.scheduled!.scheduled_at < b.scheduled!.scheduled_at ? -1 : 1);
  }
  const pa = a.priority?.priority ?? -1;
  const pb = b.priority?.priority ?? -1;
  if (pa !== pb) return pb - pa;
  const va = a.priority?.value_try ?? 0;
  const vb = b.priority?.value_try ?? 0;
  if (va !== vb) return vb - va;
  return a.playerId - b.playerId;
}

/**
 * Load the assignment pool for a head. Players visible under RLS
 * (head_retention/super_admin → all; head_department → own department), their
 * current assignees, priority hints, and the operators that can receive them.
 */
export async function loadPool(me: CurrentUser): Promise<PoolData> {
  const supabase = await createClient();

  const [{ data: dir }, { data: assigns }, { data: ops }] = await Promise.all([
    supabase
      .schema("crm")
      .from("player_directory")
      .select(DIRECTORY_COLS)
      .order("casino_player_id", { ascending: true })
      .limit(MAX_PRIORITY_IDS),
    supabase
      .schema("crm")
      .from("player_assignments")
      .select("casino_player_id, operator_id"),
    supabase
      .schema("crm")
      .from("crm_users")
      .select("id, full_name, department, role")
      .eq("role", "operator")
      .eq("is_active", true),
  ]);

  const players = (dir ?? []) as DirectoryInfo[];
  const playerIds = players.map((p) => p.casino_player_id);

  const operators: OperatorOption[] = (ops ?? []).map((o) => ({
    id: o.id as string,
    full_name: o.full_name as string,
    department: (o.department as string) ?? null,
  }));
  const opName = new Map(operators.map((o) => [o.id, o.full_name]));
  const opFallback = await operatorFallbackName();

  // Current assignees per player (RLS already scoped these rows to the head).
  const assigneesByPlayer = new Map<number, { id: string; name: string }[]>();
  for (const a of assigns ?? []) {
    const pid = a.casino_player_id as number;
    const opId = a.operator_id as string;
    const arr = assigneesByPlayer.get(pid) ?? [];
    arr.push({ id: opId, name: opName.get(opId) ?? opFallback });
    assigneesByPlayer.set(pid, arr);
  }

  const { map: priorityMap, degraded } = await loadPriorities(playerIds);

  const rows: PoolRow[] = players.map((p) => ({
    playerId: p.casino_player_id,
    directory: p,
    priority: priorityMap.get(p.casino_player_id) ?? null,
    assignees: assigneesByPlayer.get(p.casino_player_id) ?? [],
  }));

  return { rows, operators, prioritiesDegraded: degraded };
}
