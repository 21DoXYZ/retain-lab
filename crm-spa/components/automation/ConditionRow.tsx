"use client";

import { Select, Input, DateInput } from "@/components/ui";
import { useT, type MessageKey } from "@/lib/i18n";
import {
  type FieldsCatalog,
  type FieldDef,
  type LeafRow,
  type CondRow as CondRowT,
  type EventRow as EventRowT,
  type NotSegRow as NotSegRowT,
  type Segment,
  fieldByKey,
  resetCondForField,
} from "./catalog";

/**
 * ConditionRow — one clause of a segment definition. Fully generic over the
 * backend catalog: the field <select> is grouped by section (optgroups),
 * unavailable fields render disabled with a "· waiting for API event" suffix,
 * and the value editor is chosen from the field's type + the picked operator
 * (num / date / enum-multiselect / flag / str). Two special leaves — «NOT in
 * segment» and «Event» — render their own compact controls.
 */

interface ConditionRowProps {
  row: LeafRow;
  catalog: FieldsCatalog;
  segments: Segment[];
  /** sys_name of the segment being edited — excluded from the not_segment list. */
  excludeSysName?: string;
  disabled?: boolean;
  onChange: (row: LeafRow) => void;
  onRemove: () => void;
}

const CTL_SM = "!w-auto min-w-[120px]";
const NUM_W = "w-[96px]";

function RemoveButton({ onRemove, label }: { onRemove: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onRemove}
      aria-label={label}
      title={label}
      className="ml-auto text-steel hover:text-neg text-lg leading-none px-1.5 cursor-pointer"
    >
      ×
    </button>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full bg-cream text-ink text-[11px] font-semibold px-2.5 py-[3px] whitespace-nowrap">
      {children}
    </span>
  );
}

export function ConditionRow({
  row,
  catalog,
  segments,
  excludeSysName,
  disabled = false,
  onChange,
  onRemove,
}: ConditionRowProps) {
  const t = useT();

  const wrap = "flex flex-wrap items-center gap-2 py-2 px-3 rounded-ctl bg-canvas border border-hair";

  if (row.kind === "not_segment") {
    return (
      <NotSegmentRow
        row={row}
        segments={segments}
        excludeSysName={excludeSysName}
        disabled={disabled}
        onChange={onChange}
        onRemove={onRemove}
        wrap={wrap}
      />
    );
  }
  if (row.kind === "event") {
    return (
      <EventLeafRow
        row={row}
        catalog={catalog}
        disabled={disabled}
        onChange={onChange}
        onRemove={onRemove}
        wrap={wrap}
      />
    );
  }

  // ── field condition ── (narrow once; closures below lose flow-narrowing) ──
  const cond: CondRowT = row;
  const field = fieldByKey(catalog, cond.field);
  const sectionKeys = Object.keys(catalog.sections).sort((a, b) => Number(a) - Number(b));

  function chooseField(key: string) {
    if (key === "") {
      onChange({ ...cond, field: "", op: "", n1: "", n2: "", d1: "", d2: "", txt: "", sel: [], flag: true });
      return;
    }
    const f = fieldByKey(catalog, key);
    if (f) onChange(resetCondForField(cond, f));
  }

  return (
    <div className={wrap}>
      <Select
        className={CTL_SM}
        value={cond.field}
        disabled={disabled}
        onChange={(e) => chooseField(e.target.value)}
        aria-label={t("automation.row.field")}
      >
        <option value="">{t("automation.row.fieldPlaceholder")}</option>
        {sectionKeys.map((sk) => {
          const secFields = catalog.fields.filter((f) => String(f.section) === sk);
          if (secFields.length === 0) return null;
          return (
            <optgroup key={sk} label={catalog.sections[sk]}>
              {secFields.map((f) => (
                <option
                  key={f.key}
                  value={f.key}
                  disabled={!f.available && f.key !== cond.field}
                >
                  {f.available ? f.label : `${f.label} ${t("automation.row.unavailable")}`}
                </option>
              ))}
            </optgroup>
          );
        })}
      </Select>

      {field ? (
        <Select
          className={CTL_SM}
          value={cond.op}
          disabled={disabled}
          onChange={(e) => onChange({ ...cond, op: e.target.value })}
          aria-label={t("automation.row.op")}
        >
          {field.operators.map((op) => (
            <option key={op} value={op}>
              {t(`automation.op.${op}` as MessageKey)}
            </option>
          ))}
        </Select>
      ) : null}

      {field ? (
        <ValueEditor row={cond} field={field} disabled={disabled} onChange={onChange} />
      ) : null}

      {!disabled ? <RemoveButton onRemove={onRemove} label={t("automation.editor.removeRow")} /> : null}
    </div>
  );
}

// ──────────────────────────── value editor ──────────────────────────────────
interface ValueEditorProps {
  row: CondRowT;
  field: FieldDef;
  disabled: boolean;
  onChange: (row: LeafRow) => void;
}

function ValueEditor({ row, field, disabled, onChange }: ValueEditorProps) {
  const t = useT();
  const op = row.op;
  const set = (patch: Partial<CondRowT>) => onChange({ ...row, ...patch });

  if (field.type === "flag") {
    if (op === "is_null") {
      return <span className="text-[12.5px] text-steel">{t("automation.row.isNull")}</span>;
    }
    return (
      <Select
        className="!w-auto min-w-[84px]"
        value={row.flag ? "1" : "0"}
        disabled={disabled}
        onChange={(e) => set({ flag: e.target.value === "1" })}
        aria-label={t("automation.row.value")}
      >
        <option value="1">{t("automation.row.flag.yes")}</option>
        <option value="0">{t("automation.row.flag.no")}</option>
      </Select>
    );
  }

  if (field.type === "enum") {
    return <EnumEditor row={row} field={field} disabled={disabled} onChange={onChange} />;
  }

  if (field.type === "str") {
    return (
      <Input
        className="w-[220px]"
        value={row.txt}
        disabled={disabled}
        placeholder={
          op === "in" || op === "not_in"
            ? t("automation.row.list.placeholder")
            : t("automation.row.value")
        }
        onChange={(e) => set({ txt: e.target.value })}
        aria-label={t("automation.row.value")}
      />
    );
  }

  if (field.type === "date") {
    if (op === "between") {
      return (
        <span className="flex items-center gap-2">
          <DateInput className="!w-auto" value={row.d1} disabled={disabled} onChange={(e) => set({ d1: e.target.value })} />
          <span className="text-steel text-[12.5px]">{t("automation.row.between.and")}</span>
          <DateInput className="!w-auto" value={row.d2} disabled={disabled} onChange={(e) => set({ d2: e.target.value })} />
        </span>
      );
    }
    if (op === "days_ago_gt" || op === "days_ago_lt") {
      return (
        <span className="flex items-center gap-2">
          <Input type="number" className={NUM_W} value={row.n1} disabled={disabled} onChange={(e) => set({ n1: e.target.value })} />
          <span className="text-steel text-[12.5px]">{t("automation.row.days")}</span>
        </span>
      );
    }
    return <DateInput className="!w-auto" value={row.d1} disabled={disabled} onChange={(e) => set({ d1: e.target.value })} />;
  }

  // num
  if (op === "between") {
    return (
      <span className="flex items-center gap-2">
        <Input type="number" className={NUM_W} value={row.n1} disabled={disabled} onChange={(e) => set({ n1: e.target.value })} />
        <span className="text-steel text-[12.5px]">{t("automation.row.between.and")}</span>
        <Input type="number" className={NUM_W} value={row.n2} disabled={disabled} onChange={(e) => set({ n2: e.target.value })} />
      </span>
    );
  }
  if (op === "top_pct") {
    return (
      <span className="flex items-center gap-2">
        <Input type="number" className={NUM_W} value={row.n1} disabled={disabled} onChange={(e) => set({ n1: e.target.value })} />
        <span className="text-steel text-[12.5px]">{t("automation.row.pct")}</span>
      </span>
    );
  }
  return <Input type="number" className={NUM_W} value={row.n1} disabled={disabled} onChange={(e) => set({ n1: e.target.value })} aria-label={t("automation.row.value")} />;
}

// ──────────────────────────── enum multiselect ──────────────────────────────
function EnumEditor({ row, field, disabled, onChange }: ValueEditorProps) {
  const t = useT();
  const values = field.values ?? [];
  const remaining = values.filter((v) => !row.sel.includes(v));

  function add(v: string) {
    if (v === "" || row.sel.includes(v)) return;
    onChange({ ...row, sel: [...row.sel, v] });
  }
  function remove(v: string) {
    onChange({ ...row, sel: row.sel.filter((x) => x !== v) });
  }

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {row.sel.length === 0 ? (
        <span className="text-[12px] text-stone">{t("automation.row.enum.empty")}</span>
      ) : (
        row.sel.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 rounded-full bg-cream text-ink text-[12px] px-2 py-[3px] max-w-[220px]"
          >
            <span className="truncate">{v}</span>
            {!disabled ? (
              <button
                type="button"
                onClick={() => remove(v)}
                aria-label={t("automation.editor.removeRow")}
                className="text-steel hover:text-neg leading-none cursor-pointer"
              >
                ×
              </button>
            ) : null}
          </span>
        ))
      )}
      {!disabled && remaining.length > 0 ? (
        <Select
          className="!w-auto min-w-[150px]"
          value=""
          onChange={(e) => add(e.target.value)}
          aria-label={t("automation.row.enum.add")}
        >
          <option value="">{t("automation.row.enum.placeholder")}</option>
          {remaining.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </Select>
      ) : null}
    </span>
  );
}

// ──────────────────────────── not_segment ───────────────────────────────────
function NotSegmentRow({
  row,
  segments,
  excludeSysName,
  disabled,
  onChange,
  onRemove,
  wrap,
}: {
  row: NotSegRowT;
  segments: Segment[];
  excludeSysName?: string;
  disabled: boolean;
  onChange: (row: LeafRow) => void;
  onRemove: () => void;
  wrap: string;
}) {
  const t = useT();
  const options = segments.filter(
    (s) => s.archived_at == null && s.sys_name !== excludeSysName,
  );
  return (
    <div className={wrap}>
      <Tag>🚫 {t("automation.row.notSegment.label")}</Tag>
      {options.length === 0 ? (
        <span className="text-[12.5px] text-steel">{t("automation.row.notSegment.none")}</span>
      ) : (
        <Select
          className={CTL_SM}
          value={row.sys}
          disabled={disabled}
          onChange={(e) => onChange({ ...row, sys: e.target.value })}
          aria-label={t("automation.row.notSegment.label")}
        >
          <option value="">{t("automation.row.notSegment.placeholder")}</option>
          {options.map((s) => (
            <option key={s.sys_name} value={s.sys_name}>
              {s.name} ({s.sys_name})
            </option>
          ))}
        </Select>
      )}
      {!disabled ? <RemoveButton onRemove={onRemove} label={t("automation.editor.removeRow")} /> : null}
    </div>
  );
}

// ──────────────────────────── event leaf ────────────────────────────────────
function EventLeafRow({
  row,
  catalog,
  disabled,
  onChange,
  onRemove,
  wrap,
}: {
  row: EventRowT;
  catalog: FieldsCatalog;
  disabled: boolean;
  onChange: (row: LeafRow) => void;
  onRemove: () => void;
  wrap: string;
}) {
  const t = useT();
  const set = (patch: Partial<EventRowT>) => onChange({ ...row, ...patch });
  const eventLabel = (key: string): string => {
    const k = `automation.event.${key}` as MessageKey;
    const translated = t(k);
    return translated === k ? key : translated;
  };
  return (
    <div className={wrap}>
      <Tag>⚡ {t("automation.row.event.label")}</Tag>
      <Select
        className={CTL_SM}
        value={row.etype}
        disabled={disabled}
        onChange={(e) => set({ etype: e.target.value })}
        aria-label={t("automation.row.event.type")}
      >
        {catalog.events.map((ev) => (
          <option key={ev.key} value={ev.key}>
            {eventLabel(ev.key)}
          </option>
        ))}
      </Select>
      <Select
        className="!w-auto min-w-[64px]"
        value={row.op}
        disabled={disabled}
        onChange={(e) => set({ op: e.target.value })}
        aria-label={t("automation.row.event.op")}
      >
        {catalog.event_ops.map((op) => (
          <option key={op} value={op}>
            {t(`automation.eop.${op}` as MessageKey)}
          </option>
        ))}
      </Select>
      <Input
        type="number"
        className={NUM_W}
        value={row.count}
        disabled={disabled}
        onChange={(e) => set({ count: e.target.value })}
        aria-label={t("automation.row.event.count")}
      />
      <span className="text-steel text-[12.5px]">{t("automation.row.event.count")}</span>
      <span className="text-steel text-[12.5px]">{t("automation.row.event.within")}</span>
      <Input
        type="number"
        className={NUM_W}
        value={row.within}
        disabled={disabled}
        onChange={(e) => set({ within: e.target.value })}
        aria-label={t("automation.row.event.within")}
      />
      {!disabled ? <RemoveButton onRemove={onRemove} label={t("automation.editor.removeRow")} /> : null}
    </div>
  );
}
