"use client";

/**
 * Segment builder — shared types + the editor-model ↔ API-JSON bridge (W4-T2).
 *
 * The screen is GENERIC over the backend field catalog (GET /segments/fields):
 * it never hard-codes fields/operators. Everything the UI needs about a field
 * (type, operators, allowed values, availability) comes from the catalog, so
 * when the registry grows to 158 filters the UI keeps working unchanged.
 *
 * Two shapes live here:
 *   • Raw*   — exactly the JSON the Flask API produces/consumes (api/segments.py,
 *              api/segment_compiler.py). `definition` = { all: [...] } with ≤2
 *              nesting levels, {field,op,value} leaves, plus not_segment / event.
 *   • Editor* — a client-side model carrying stable row ids (rid) so React keys
 *              are stable and edits stay immutable; serialized back to Raw on
 *              every preview / save.
 */

// ────────────────────────────── Catalog (from API) ──────────────────────────
export type FieldType = "num" | "date" | "enum" | "flag" | "str";

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  section: number;
  section_label: string;
  available: boolean;
  needs: string | null;
  operators: string[];
  values: string[] | null;
}

export interface EventDef {
  key: string;
  label: string;
  table: string;
}

export interface FieldsCatalog {
  fields: FieldDef[];
  sections: Record<string, string>;
  events: EventDef[];
  event_ops: string[];
}

// ────────────────────────────── Segment (from API) ──────────────────────────
export type RawScalar = number | string | boolean;
export type RawValue = RawScalar | Array<number | string>;

export interface RawCond {
  field: string;
  op: string;
  value?: RawValue;
}
export interface RawNotSegment {
  not_segment: string;
}
export interface RawEvent {
  event: {
    type: string;
    within_days: number;
    op: string;
    count: number;
    status?: string;
  };
}
export interface RawAny {
  any: RawLeaf[];
}
export type RawLeaf = RawCond | RawNotSegment | RawEvent;
export type RawNode = RawLeaf | RawAny;
export interface RawDefinition {
  all: RawNode[];
}

export interface Segment {
  segment_id: string;
  name: string;
  sys_name: string;
  description: string;
  definition: RawDefinition;
  is_trigger: boolean;
  schedule_at: string;
  created_by: string | null;
  created_by_name?: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  member_count: number | null;
  computed_at: string | null;
}

export interface SegmentPreset {
  key: string;
  kind: string;
  icon: string;
  name: string;
  description: string;
  offer: string;
  definition: RawDefinition;
  note: string | null;
}

// ────────────────────────────── Editor model ────────────────────────────────
export interface CondRow {
  rid: string;
  kind: "cond";
  field: string;
  op: string;
  /** numeric / days inputs (kept as strings for controlled inputs) */
  n1: string;
  n2: string;
  /** date inputs (YYYY-MM-DD) */
  d1: string;
  d2: string;
  /** free-text (str eq/ne/contains) or comma-list (str in/not_in) */
  txt: string;
  /** enum multiselect */
  sel: string[];
  /** flag `is` value */
  flag: boolean;
}

export interface NotSegRow {
  rid: string;
  kind: "not_segment";
  sys: string;
}

export interface EventRow {
  rid: string;
  kind: "event";
  etype: string;
  within: string;
  op: string;
  count: string;
}

export type LeafRow = CondRow | NotSegRow | EventRow;

export interface AnyGroup {
  rid: string;
  kind: "any";
  rows: LeafRow[];
}

export type RootRow = LeafRow | AnyGroup;

export interface EditorDef {
  rows: RootRow[];
}

// ────────────────────────────── Constants ───────────────────────────────────
export const SYS_NAME_RE = /^[a-z][a-z0-9_]{2,63}$/;

/** Date operators whose value is a plain day-count (not a calendar date). */
const DATE_DAYS_OPS = new Set(["days_ago_gt", "days_ago_lt"]);
/** str/enum operators whose value is a list. */
const STR_LIST_OPS = new Set(["in", "not_in"]);

// ────────────────────────────── rid factory ─────────────────────────────────
let _rid = 0;
export function nextRid(): string {
  _rid += 1;
  return `r${_rid}`;
}

// ────────────────────────────── Row factories ───────────────────────────────
export function newCondRow(): CondRow {
  return {
    rid: nextRid(),
    kind: "cond",
    field: "",
    op: "",
    n1: "",
    n2: "",
    d1: "",
    d2: "",
    txt: "",
    sel: [],
    flag: true,
  };
}

export function newNotSegRow(): NotSegRow {
  return { rid: nextRid(), kind: "not_segment", sys: "" };
}

export function newEventRow(catalog: FieldsCatalog): EventRow {
  return {
    rid: nextRid(),
    kind: "event",
    etype: catalog.events[0]?.key ?? "deposit",
    within: "30",
    op: catalog.event_ops[0] ?? "gte",
    count: "1",
  };
}

export function newAnyGroup(): AnyGroup {
  return { rid: nextRid(), kind: "any", rows: [newCondRow()] };
}

// ────────────────────────────── Field lookup ────────────────────────────────
export function fieldByKey(catalog: FieldsCatalog, key: string): FieldDef | undefined {
  return catalog.fields.find((f) => f.key === key);
}

/** Reset the value slots of a cond row after its field changes (types differ). */
export function resetCondForField(row: CondRow, field: FieldDef): CondRow {
  return {
    ...row,
    field: field.key,
    op: field.operators[0] ?? "",
    n1: "",
    n2: "",
    d1: "",
    d2: "",
    txt: "",
    sel: [],
    flag: true,
  };
}

// ────────────────────────────── Completeness ────────────────────────────────
/** A leaf is "complete" when it contributes a valid clause to the definition. */
export function isLeafComplete(row: LeafRow, catalog: FieldsCatalog): boolean {
  if (row.kind === "not_segment") return row.sys !== "";
  if (row.kind === "event") {
    return (
      row.etype !== "" && row.op !== "" && row.within.trim() !== "" && row.count.trim() !== ""
    );
  }
  const f = fieldByKey(catalog, row.field);
  if (!f || !row.op) return false;
  const { type, op } = { type: f.type, op: row.op };
  if (type === "flag") return true; // is / is_null both self-contained
  if (type === "enum") return row.sel.length > 0;
  if (type === "str") return STR_LIST_OPS.has(op) ? row.txt.trim() !== "" : row.txt.trim() !== "";
  if (type === "date") {
    if (op === "between") return row.d1 !== "" && row.d2 !== "";
    if (DATE_DAYS_OPS.has(op)) return row.n1.trim() !== "";
    return row.d1 !== "";
  }
  // num
  if (op === "between") return row.n1.trim() !== "" && row.n2.trim() !== "";
  return row.n1.trim() !== "";
}

// ────────────────────────────── Serialize (model → Raw) ─────────────────────
function toNum(s: string): number {
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}

function serializeLeaf(row: LeafRow, catalog: FieldsCatalog): RawLeaf | null {
  if (!isLeafComplete(row, catalog)) return null;

  if (row.kind === "not_segment") return { not_segment: row.sys };

  if (row.kind === "event") {
    return {
      event: {
        type: row.etype,
        within_days: toNum(row.within),
        op: row.op,
        count: toNum(row.count),
      },
    };
  }

  const f = fieldByKey(catalog, row.field);
  if (!f) return null;
  const { type } = f;
  const op = row.op;

  if (type === "flag") {
    if (op === "is_null") return { field: f.key, op };
    return { field: f.key, op, value: row.flag };
  }

  if (type === "enum") {
    return { field: f.key, op, value: [...row.sel] };
  }

  if (type === "str") {
    if (STR_LIST_OPS.has(op)) {
      const parts = row.txt
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== "");
      return { field: f.key, op, value: parts };
    }
    return { field: f.key, op, value: row.txt.trim() };
  }

  if (type === "date") {
    if (op === "between") return { field: f.key, op, value: [row.d1, row.d2] };
    if (DATE_DAYS_OPS.has(op)) return { field: f.key, op, value: toNum(row.n1) };
    return { field: f.key, op, value: row.d1 };
  }

  // num
  if (op === "between") return { field: f.key, op, value: [toNum(row.n1), toNum(row.n2)] };
  return { field: f.key, op, value: toNum(row.n1) };
}

/**
 * Editor model → API definition. Incomplete rows and empty ANY-groups are
 * dropped, so the live preview reflects only well-formed clauses while the user
 * is still typing (and Save persists exactly what preview counted).
 */
export function serialize(model: EditorDef, catalog: FieldsCatalog): RawDefinition {
  const all: RawNode[] = [];
  for (const row of model.rows) {
    if (row.kind === "any") {
      const leaves: RawLeaf[] = [];
      for (const leaf of row.rows) {
        const s = serializeLeaf(leaf, catalog);
        if (s) leaves.push(s);
      }
      if (leaves.length > 0) all.push({ any: leaves });
    } else {
      const s = serializeLeaf(row, catalog);
      if (s) all.push(s);
    }
  }
  return { all };
}

// ────────────────────────────── Deserialize (Raw → model) ───────────────────
function scalarStr(v: RawValue | undefined): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.length ? String(v[0]) : "";
  return String(v);
}

function condFromRaw(raw: RawCond, catalog: FieldsCatalog): CondRow {
  const row = newCondRow();
  const f = fieldByKey(catalog, raw.field);
  row.field = raw.field;
  row.op = raw.op;
  const v = raw.value;
  const type = f?.type;

  if (type === "flag") {
    row.flag = raw.op === "is_null" ? true : Boolean(v);
  } else if (type === "enum") {
    row.sel = Array.isArray(v) ? v.map(String) : v != null ? [String(v)] : [];
  } else if (type === "str") {
    row.txt = Array.isArray(v) ? v.map(String).join(", ") : scalarStr(v);
  } else if (type === "date") {
    if (raw.op === "between" && Array.isArray(v)) {
      row.d1 = String(v[0] ?? "");
      row.d2 = String(v[1] ?? "");
    } else if (DATE_DAYS_OPS.has(raw.op)) {
      row.n1 = scalarStr(v);
    } else {
      row.d1 = scalarStr(v);
    }
  } else {
    // num
    if (raw.op === "between" && Array.isArray(v)) {
      row.n1 = String(v[0] ?? "");
      row.n2 = String(v[1] ?? "");
    } else {
      row.n1 = scalarStr(v);
    }
  }
  return row;
}

function leafFromRaw(raw: RawLeaf, catalog: FieldsCatalog): LeafRow {
  if ("not_segment" in raw) {
    return { rid: nextRid(), kind: "not_segment", sys: raw.not_segment };
  }
  if ("event" in raw) {
    return {
      rid: nextRid(),
      kind: "event",
      etype: raw.event.type,
      within: String(raw.event.within_days ?? ""),
      op: raw.event.op,
      count: String(raw.event.count ?? ""),
    };
  }
  return condFromRaw(raw, catalog);
}

/** API definition → editor model (used when editing / cloning an existing def). */
export function deserialize(def: RawDefinition | null | undefined, catalog: FieldsCatalog): EditorDef {
  const nodes = def?.all ?? [];
  const rows: RootRow[] = [];
  for (const node of nodes) {
    if ("any" in node) {
      rows.push({
        rid: nextRid(),
        kind: "any",
        rows: node.any.map((l) => leafFromRaw(l, catalog)),
      });
    } else {
      rows.push(leafFromRaw(node, catalog));
    }
  }
  return { rows };
}

// ────────────────────────────── sys_name transliteration ────────────────────
const TRANSLIT: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z",
  и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r",
  с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "c", ч: "ch", ш: "sh", щ: "sch",
  ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
  ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u",
};

/** Name → a valid sys_name candidate (^[a-z][a-z0-9_]{2,63}$), best-effort. */
export function translitSysName(name: string): string {
  let out = "";
  for (const ch of name.toLowerCase()) {
    if (ch in TRANSLIT) out += TRANSLIT[ch];
    else if (/[a-z0-9]/.test(ch)) out += ch;
    else out += "_";
  }
  out = out.replace(/_+/g, "_").replace(/^_+/, "").slice(0, 64);
  // must start with a letter
  if (out && !/^[a-z]/.test(out)) out = `s_${out}`.slice(0, 64);
  out = out.replace(/_+$/, "");
  return out;
}
