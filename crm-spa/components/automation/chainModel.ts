"use client";

/**
 * Chain builder — shared types + the editor-model ↔ API-JSON bridge (W4-T5).
 *
 * Companion to catalog.ts (segment builder): the chains UI is a LINEAR editor
 * (vertical flow, no free canvas). This module holds everything shared by the
 * screens (ChainsList / ChainEditor / NodeCard / ChainStats / TemplatesPanel):
 *
 *   • Raw*  — exactly the JSON api/chains.py produces/consumes. `definition` =
 *             { trigger, control_pct, goal, nodes[] } — validated server-side by
 *             validate_definition(); a 422 returns the human-readable reason text.
 *   • Editor* — a client model carrying stable node ids so React keys stay put and
 *             edits stay immutable; serialized back to Raw on every save.
 *
 * The condition node reuses the segment builder wholesale: its `if` clause is a
 * CondRow rendered by the exported <ConditionRow>, serialized/deserialized via
 * catalog.ts's public serialize()/deserialize() (single-row wrapper) so we never
 * duplicate the field/operator/value logic.
 */

import {
  type FieldsCatalog,
  type CondRow,
  type RawNode,
  type Segment,
  newCondRow,
  serialize as serializeSegDef,
  deserialize as deserializeSegDef,
} from "./catalog";

export type { FieldsCatalog, Segment };

// ────────────────────────────── API: chains ─────────────────────────────────
export type ChainStatus = "draft" | "active" | "paused" | "archived";

/** Row of GET /api/v1/chains (list — no definition). */
export interface ChainListItem {
  chain_id: string;
  name: string;
  description: string;
  status: ChainStatus;
  created_at: string;
  updated_at: string;
  activated_at: string | null;
  versions_count: number;
  active_version_no: number | null;
  has_draft: boolean;
  active_enrollments: number;
}

export interface ChainVersion {
  version_id: string;
  version_no: number;
  definition: ChainDefinition;
  created_at: string;
  activated_at: string | null;
}

/** GET /api/v1/chains/<id> — full chain with its versions. */
export interface Chain {
  chain_id: string;
  name: string;
  description: string;
  status: ChainStatus;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  activated_at: string | null;
  archived_at: string | null;
  versions: ChainVersion[];
}

export interface Template {
  template_id: string;
  name: string;
  channel_kind: Channel;
  texts: Record<string, string>;
  created_at: string;
  updated_at: string;
}

// ────────────────────────────── API: stats ──────────────────────────────────
export interface StatNode {
  node_id: string;
  entered: number;
  passed: number;
  dropped: number;
  drop_reasons: Record<string, number>;
}

export interface ChainStatsData {
  available: boolean;
  nodes: StatNode[];
  goal?: {
    main: { n: number; conv: number };
    control: { n: number; conv: number };
  };
}

// ────────────────────────────── Raw definition ──────────────────────────────
export type TriggerKind = "segment" | "event" | "schedule";
export type ActionKind = "bonus_grant" | "send_message" | "desk_task" | "player_tag";
export type WaitMode = "fixed" | "event" | "ml";
export type NodeKind = "action" | "wait" | "condition";
export type Channel = "casino_webhook" | "email" | "telegram";

export interface RawTriggerSegment {
  kind: "segment";
  sys_name: string;
  reentry_days?: number;
}
export interface RawTriggerEvent {
  kind: "event";
  type: string;
}
export interface RawTriggerSchedule {
  kind: "schedule";
  cron: string;
}
export type RawTrigger = RawTriggerSegment | RawTriggerEvent | RawTriggerSchedule;

export interface RawGoal {
  event: string;
  attribution_days: number;
}

export interface RawActionNode {
  id: string;
  kind: "action";
  action: string;
  bonus?: string;
  channel?: string;
  template?: string;
  params?: Record<string, string>;
  reason?: string;
  tag?: string;
}
export interface RawWaitNode {
  id: string;
  kind: "wait";
  mode: string;
  fallback_hours: number;
  window?: { from?: string; to?: string };
}
export interface RawConditionNode {
  id: string;
  kind: "condition";
  if: Record<string, unknown>;
  then?: string | null;
  else?: string | null;
}
export type RawChainNode = RawActionNode | RawWaitNode | RawConditionNode;

export interface ChainDefinition {
  trigger: RawTrigger;
  control_pct: number;
  goal: RawGoal;
  nodes: RawChainNode[];
}

// ────────────────────────────── Editor model ────────────────────────────────
export interface EditorParam {
  pid: string;
  key: string;
  value: string;
}

export interface EditorActionNode {
  id: string;
  kind: "action";
  action: ActionKind;
  bonus: string; // bonus_grant
  channel: Channel; // send_message
  template: string; // send_message → template_id
  params: EditorParam[]; // send_message
  reason: string; // desk_task
  tag: string; // player_tag
}
export interface EditorWaitNode {
  id: string;
  kind: "wait";
  mode: WaitMode;
  fallbackHours: string;
  hasWindow: boolean;
  windowFrom: string;
  windowTo: string;
}
export interface EditorConditionNode {
  id: string;
  kind: "condition";
  cond: CondRow;
  /** "" = next node (null) · node id · "exit_converted" · "exit" */
  then: string;
  els: string;
}
export type EditorNode = EditorActionNode | EditorWaitNode | EditorConditionNode;

export interface ChainEditorModel {
  triggerKind: TriggerKind;
  triggerSegment: string;
  triggerReentryDays: string;
  triggerEventType: string;
  triggerCron: string;
  controlPct: string;
  goalEvent: string;
  goalAttributionDays: string;
  nodes: EditorNode[];
}

// ────────────────────────────── Constants (whitelist mirrors api/chains.py) ──
export const ACTION_KINDS: readonly ActionKind[] = [
  "bonus_grant",
  "send_message",
  "desk_task",
  "player_tag",
];
export const WAIT_MODES: readonly WaitMode[] = ["fixed", "event", "ml"];
export const CHANNELS: readonly Channel[] = ["casino_webhook", "email", "telegram"];
/** trigger.type whitelist — EVENT_TYPES in api/chains.py. */
export const TRIGGER_EVENT_TYPES: readonly string[] = [
  "deposit",
  "deposit_failed",
  "bet",
  "login",
  "session_start",
  "session_end",
  "cashier_opened",
];
/** goal.event whitelist — GOAL_EVENTS in api/chains.py. */
export const GOAL_EVENTS: readonly string[] = ["deposit", "bet", "login"];
/** bonus codes for bonus_grant (BONUS_MAP in signals/pusher.py + ml_recommended). */
export const BONUS_CODES: readonly string[] = [
  "ml_recommended",
  "first_deposit_bonus",
  "second_deposit_reload",
  "vip_offer",
  "freespins",
  "reload_cashback",
];
/** Template placeholders shown as a hint in the message editor. */
export const TEMPLATE_VARS: readonly string[] = ["bonus_amount", "game", "link", "name"];
/** condition then/else terminal targets. */
export const EXIT_TARGETS: readonly string[] = ["exit_converted", "exit"];

// ────────────────────────────── id factories ────────────────────────────────
let _pid = 0;
function nextPid(): string {
  _pid += 1;
  return `p${_pid}`;
}

/** First `n{k}` id not already used — collision-free across load + adds. */
export function freshNodeId(existing: readonly string[]): string {
  const used = new Set(existing);
  let i = 1;
  while (used.has(`n${i}`)) i += 1;
  return `n${i}`;
}

// ────────────────────────────── Node factories ──────────────────────────────
export function newActionNode(existing: readonly string[]): EditorActionNode {
  return {
    id: freshNodeId(existing),
    kind: "action",
    action: "bonus_grant",
    bonus: "ml_recommended",
    channel: "casino_webhook",
    template: "",
    params: [],
    reason: "",
    tag: "",
  };
}

export function newWaitNode(existing: readonly string[]): EditorWaitNode {
  return {
    id: freshNodeId(existing),
    kind: "wait",
    mode: "fixed",
    fallbackHours: "24",
    hasWindow: false,
    windowFrom: "11:00",
    windowTo: "22:00",
  };
}

export function newConditionNode(existing: readonly string[]): EditorConditionNode {
  return {
    id: freshNodeId(existing),
    kind: "condition",
    cond: newCondRow(),
    then: "exit_converted",
    els: "",
  };
}

export function newParam(): EditorParam {
  return { pid: nextPid(), key: "", value: "" };
}

export function emptyModel(): ChainEditorModel {
  return {
    triggerKind: "segment",
    triggerSegment: "",
    triggerReentryDays: "30",
    triggerEventType: "deposit",
    triggerCron: "0 10 * * *",
    controlPct: "16",
    goalEvent: "deposit",
    goalAttributionDays: "14",
    nodes: [],
  };
}

// ────────────────────────────── condition `if` bridge ───────────────────────
/**
 * Serialize a single CondRow to the raw {field, op, value} the runner compiles.
 * Reuses catalog.serialize() by wrapping the row in a one-row definition; a
 * complete row yields the full clause, an incomplete one keeps field/op so a
 * saved draft round-trips (the server validator only requires `if` to be a dict).
 */
export function serializeCondIf(cond: CondRow, catalog: FieldsCatalog): Record<string, unknown> {
  const def = serializeSegDef({ rows: [cond] }, catalog);
  const first = def.all[0];
  if (first && "field" in first) return { ...first };
  const partial: Record<string, unknown> = {};
  if (cond.field) partial.field = cond.field;
  if (cond.op) partial.op = cond.op;
  return partial;
}

/** Raw {field, op, value} → editor CondRow (reuses catalog.deserialize()). */
export function condIfFromRaw(raw: unknown, catalog: FieldsCatalog): CondRow {
  if (raw && typeof raw === "object" && "field" in raw) {
    const model = deserializeSegDef({ all: [raw as RawNode] }, catalog);
    const first = model.rows[0];
    if (first && first.kind === "cond") return first;
  }
  return newCondRow();
}

// ────────────────────────────── Serialize (model → Raw) ─────────────────────
function toNumOr(s: string, fallback: number): number {
  const trimmed = s.trim();
  if (trimmed === "") return fallback;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : fallback;
}

function serializeNode(node: EditorNode, catalog: FieldsCatalog): RawChainNode {
  if (node.kind === "action") {
    if (node.action === "bonus_grant") {
      return { id: node.id, kind: "action", action: "bonus_grant", bonus: node.bonus };
    }
    if (node.action === "send_message") {
      const params: Record<string, string> = {};
      for (const p of node.params) {
        const k = p.key.trim();
        if (k) params[k] = p.value;
      }
      const out: RawActionNode = {
        id: node.id,
        kind: "action",
        action: "send_message",
        channel: node.channel,
        template: node.template,
      };
      if (Object.keys(params).length > 0) out.params = params;
      return out;
    }
    if (node.action === "desk_task") {
      return { id: node.id, kind: "action", action: "desk_task", reason: node.reason };
    }
    return { id: node.id, kind: "action", action: "player_tag", tag: node.tag };
  }

  if (node.kind === "wait") {
    const out: RawWaitNode = {
      id: node.id,
      kind: "wait",
      mode: node.mode,
      fallback_hours: toNumOr(node.fallbackHours, 0),
    };
    if (node.hasWindow) out.window = { from: node.windowFrom, to: node.windowTo };
    return out;
  }

  // condition
  return {
    id: node.id,
    kind: "condition",
    if: serializeCondIf(node.cond, catalog),
    then: node.then === "" ? null : node.then,
    else: node.els === "" ? null : node.els,
  };
}

export function serializeDefinition(m: ChainEditorModel, catalog: FieldsCatalog): ChainDefinition {
  let trigger: RawTrigger;
  if (m.triggerKind === "segment") {
    const seg: RawTriggerSegment = { kind: "segment", sys_name: m.triggerSegment };
    if (m.triggerReentryDays.trim() !== "") seg.reentry_days = toNumOr(m.triggerReentryDays, 0);
    trigger = seg;
  } else if (m.triggerKind === "event") {
    trigger = { kind: "event", type: m.triggerEventType };
  } else {
    trigger = { kind: "schedule", cron: m.triggerCron };
  }
  return {
    trigger,
    control_pct: toNumOr(m.controlPct, 16),
    goal: { event: m.goalEvent, attribution_days: toNumOr(m.goalAttributionDays, 14) },
    nodes: m.nodes.map((n) => serializeNode(n, catalog)),
  };
}

// ────────────────────────────── Deserialize (Raw → model) ───────────────────
function nodeFromRaw(n: RawChainNode, catalog: FieldsCatalog): EditorNode {
  if (n.kind === "wait") {
    return {
      id: n.id,
      kind: "wait",
      mode: (WAIT_MODES.includes(n.mode as WaitMode) ? (n.mode as WaitMode) : "fixed"),
      fallbackHours: n.fallback_hours != null ? String(n.fallback_hours) : "",
      hasWindow: !!n.window,
      windowFrom: n.window?.from ?? "11:00",
      windowTo: n.window?.to ?? "22:00",
    };
  }
  if (n.kind === "condition") {
    return {
      id: n.id,
      kind: "condition",
      cond: condIfFromRaw(n.if, catalog),
      then: n.then == null ? "" : String(n.then),
      els: n.else == null ? "" : String(n.else),
    };
  }
  const a = n as RawActionNode;
  return {
    id: a.id,
    kind: "action",
    action: (ACTION_KINDS.includes(a.action as ActionKind) ? (a.action as ActionKind) : "bonus_grant"),
    bonus: a.bonus ?? "ml_recommended",
    channel: (CHANNELS.includes(a.channel as Channel) ? (a.channel as Channel) : "casino_webhook"),
    template: a.template ?? "",
    params: Object.entries(a.params ?? {}).map(([k, v]) => ({ pid: nextPid(), key: k, value: String(v) })),
    reason: a.reason ?? "",
    tag: a.tag ?? "",
  };
}

export function modelFromDefinition(
  def: ChainDefinition | null | undefined,
  catalog: FieldsCatalog,
): ChainEditorModel {
  if (!def) return emptyModel();
  const base = emptyModel();
  const trig = def.trigger;
  const kind: TriggerKind =
    trig && (trig.kind === "segment" || trig.kind === "event" || trig.kind === "schedule")
      ? trig.kind
      : "segment";
  return {
    triggerKind: kind,
    triggerSegment: trig && trig.kind === "segment" ? (trig.sys_name ?? "") : "",
    triggerReentryDays:
      trig && trig.kind === "segment" && trig.reentry_days != null ? String(trig.reentry_days) : "",
    triggerEventType: trig && trig.kind === "event" ? (trig.type ?? "deposit") : "deposit",
    triggerCron: trig && trig.kind === "schedule" ? (trig.cron ?? "") : base.triggerCron,
    controlPct: def.control_pct != null ? String(def.control_pct) : "16",
    goalEvent: def.goal?.event ?? "deposit",
    goalAttributionDays: def.goal?.attribution_days != null ? String(def.goal.attribution_days) : "14",
    nodes: (def.nodes ?? []).map((n) => nodeFromRaw(n, catalog)),
  };
}

/** Latest version of a chain (draft if present, else the last activated one). */
export function latestDefinition(chain: Chain): ChainDefinition | null {
  const vs = chain.versions ?? [];
  if (vs.length === 0) return null;
  const latest = vs.reduce((a, b) => (b.version_no > a.version_no ? b : a));
  return latest.definition ?? null;
}

/**
 * Version number the next activation will stamp: the outstanding draft's number,
 * or (max activated + 1) when there is no draft yet. Used by the "creates
 * version N" confirmation.
 */
export function pendingVersionNo(chain: Chain): number {
  const vs = chain.versions ?? [];
  const draft = vs.find((v) => v.activated_at == null);
  if (draft) return draft.version_no;
  const maxNo = vs.reduce((m, v) => Math.max(m, v.version_no), 0);
  return maxNo + 1;
}
