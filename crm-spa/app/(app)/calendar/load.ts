import type { SupabaseClient } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/server";
import type {
  AutoPlanCandidate,
  DayPlanRow,
  OperatorSummary,
  PlayerLite,
} from "@/components/calendar/types";

/**
 * Server-side loaders for /calendar. All reads go through the request-bound
 * Supabase client, so RLS (0002) already scopes rows: an operator only sees
 * their own scheduled_calls / assignments; a head sees their department; admins
 * see all. We never widen that here — we only shape the rows for the views.
 */

const TZ = "Europe/Istanbul";

/** Istanbul calendar day as "YYYY-MM-DD" (lexicographically comparable). */
function istanbulDay(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

interface SchedRow {
  id: string;
  casino_player_id: number;
  scheduled_at: string;
  comment: string | null;
  by_system: boolean;
  status: string;
}

async function loadDirectory(
  supabase: SupabaseClient,
  ids: number[],
): Promise<Map<number, PlayerLite>> {
  if (ids.length === 0) return new Map();
  const { data } = await supabase
    .schema("crm")
    .from("player_directory")
    .select("casino_player_id, display_id, lifecycle, vip_level, country")
    .in("casino_player_id", ids);
  return new Map((data ?? []).map((d) => [d.casino_player_id as number, d as PlayerLite]));
}

export interface OperatorCalendar {
  error: boolean;
  dayPlan: DayPlanRow[];
  autoPlan: AutoPlanCandidate[];
}

/** Operator/VIP day plan (today + overdue) + auto-plan candidates. */
export async function loadOperatorCalendar(meId: string): Promise<OperatorCalendar> {
  const supabase = await createClient();

  const [schedRes, assignRes] = await Promise.all([
    supabase
      .schema("crm")
      .from("scheduled_calls")
      .select("id, casino_player_id, scheduled_at, comment, by_system, status")
      .eq("operator_id", meId)
      .neq("status", "done")
      .order("scheduled_at", { ascending: true }),
    supabase
      .schema("crm")
      .from("player_assignments")
      .select("casino_player_id")
      .eq("operator_id", meId),
  ]);

  if (schedRes.error || assignRes.error) {
    return { error: true, dayPlan: [], autoPlan: [] };
  }

  const schedRows = (schedRes.data ?? []) as SchedRow[];
  const assignIds = [
    ...new Set((assignRes.data ?? []).map((a) => a.casino_player_id as number)),
  ];
  const scheduledIds = new Set(schedRows.map((s) => s.casino_player_id));
  const candidateIds = assignIds.filter((id) => !scheduledIds.has(id));

  const today = istanbulDay(new Date());
  const buckets = schedRows
    .map((s) => ({ s, day: istanbulDay(new Date(s.scheduled_at)) }))
    .filter((x) => x.day <= today); // overdue (past) + today; future is hidden

  const dirMap = await loadDirectory(supabase, [
    ...new Set([...buckets.map((b) => b.s.casino_player_id), ...candidateIds]),
  ]);

  const dayPlan: DayPlanRow[] = buckets.map(({ s, day }) => ({
    id: s.id,
    casino_player_id: s.casino_player_id,
    scheduled_at: s.scheduled_at,
    comment: s.comment,
    by_system: s.by_system,
    overdue: day < today || s.status === "overdue" || s.status === "missed",
    player: dirMap.get(s.casino_player_id) ?? null,
  }));

  const autoPlan: AutoPlanCandidate[] = candidateIds.map((id) => ({
    casino_player_id: id,
    player: dirMap.get(id) ?? null,
  }));

  return { error: false, dayPlan, autoPlan };
}

interface OpsRow {
  id: string;
  full_name: string;
  department: string | null;
  role: string;
}

export interface HeadSummaryResult {
  error: boolean;
  rows: OperatorSummary[];
}

/** Head-of-department discipline summary: per-operator planned/done/overdue. */
export async function loadHeadSummary(): Promise<HeadSummaryResult> {
  const supabase = await createClient();

  const [schedRes, opsRes] = await Promise.all([
    supabase
      .schema("crm")
      .from("scheduled_calls")
      .select("operator_id, scheduled_at, status"),
    supabase.schema("crm").from("crm_users").select("id, full_name, department, role"),
  ]);

  if (schedRes.error || opsRes.error) return { error: true, rows: [] };

  const now = Date.now();
  const operators = ((opsRes.data ?? []) as OpsRow[]).filter((o) => o.role === "operator");

  const agg = new Map<string, { planned: number; done: number; overdue: number; total: number }>();
  for (const o of operators) agg.set(o.id, { planned: 0, done: 0, overdue: 0, total: 0 });

  for (const s of (schedRes.data ?? []) as { operator_id: string; scheduled_at: string; status: string }[]) {
    const a = agg.get(s.operator_id);
    if (!a) continue;
    a.total += 1;
    const overdue =
      s.status === "overdue" ||
      s.status === "missed" ||
      (s.status === "planned" && new Date(s.scheduled_at).getTime() < now);
    if (s.status === "done") a.done += 1;
    else if (overdue) a.overdue += 1;
    else a.planned += 1;
  }

  const rows: OperatorSummary[] = operators.map((o) => {
    const a = agg.get(o.id)!;
    return { operator_id: o.id, name: o.full_name, department: o.department, ...a };
  });
  rows.sort((x, y) => y.total - x.total || x.name.localeCompare(y.name));

  return { error: false, rows };
}
