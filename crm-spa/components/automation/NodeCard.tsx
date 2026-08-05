"use client";

import { Card, Select, Input, FormField, Button, Badge } from "@/components/ui";
import { useT, type MessageKey } from "@/lib/i18n";
import { ConditionRow } from "./ConditionRow";
import { newCondRow, type LeafRow } from "./catalog";
import {
  type EditorNode,
  type EditorActionNode,
  type EditorWaitNode,
  type EditorConditionNode,
  type ActionKind,
  type WaitMode,
  type Channel,
  type FieldsCatalog,
  type Segment,
  type Template,
  ACTION_KINDS,
  WAIT_MODES,
  CHANNELS,
  BONUS_CODES,
  TEMPLATE_VARS,
  EXIT_TARGETS,
  newParam,
} from "./chainModel";

/**
 * NodeCard — one step of the linear chain flow (W4-T5). The node kind is fixed at
 * add-time (delete + re-add to change it); the card renders kind-specific controls:
 *   • action    — action select → bonus code / message (channel+template+params) /
 *                 desk task (reason) / tag.
 *   • wait       — mode (fixed/event/ml) + fallback/wait hours + optional HH:MM window.
 *   • condition  — reuses the segment <ConditionRow> for the `if` clause; then/else
 *                 point to a LATER node (forward-only, per the server validator) or an
 *                 exit, rendered as indented "→ то / → иначе" branches (text, no canvas).
 * Up / down / delete live in the header.
 */

export interface NodeTarget {
  id: string;
  label: string;
}

interface NodeCardProps {
  node: EditorNode;
  index: number;
  total: number;
  /** Nodes AFTER this one — the only legal then/else jump targets (forward-only). */
  laterNodes: NodeTarget[];
  catalog: FieldsCatalog;
  segments: Segment[];
  templates: Template[];
  disabled: boolean;
  onChange: (node: EditorNode) => void;
  onMove: (dir: -1 | 1) => void;
  onRemove: () => void;
}

const CTL_SM = "!w-auto min-w-[150px]";

export function NodeCard({
  node,
  index,
  total,
  laterNodes,
  catalog,
  segments,
  templates,
  disabled,
  onChange,
  onMove,
  onRemove,
}: NodeCardProps) {
  const t = useT();

  return (
    <Card className="!py-4">
      {/* header: step number + kind + reorder / delete */}
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-cream text-ink text-[12px] font-semibold flex-none">
            {index + 1}
          </span>
          <Badge bg="#eef2f6" fg="#344054">
            {t(`automation.chains.node.kind.${node.kind}` as MessageKey)}
          </Badge>
          <span className="text-[12px] text-stone font-mono truncate">{node.id}</span>
        </div>
        {!disabled ? (
          <div className="flex items-center gap-1 flex-none">
            <button
              type="button"
              onClick={() => onMove(-1)}
              disabled={index === 0}
              aria-label={t("automation.chains.node.moveUp")}
              title={t("automation.chains.node.moveUp")}
              className="text-steel hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed px-1.5 text-[15px] cursor-pointer"
            >
              ↑
            </button>
            <button
              type="button"
              onClick={() => onMove(1)}
              disabled={index === total - 1}
              aria-label={t("automation.chains.node.moveDown")}
              title={t("automation.chains.node.moveDown")}
              className="text-steel hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed px-1.5 text-[15px] cursor-pointer"
            >
              ↓
            </button>
            <button
              type="button"
              onClick={onRemove}
              aria-label={t("automation.chains.node.remove")}
              title={t("automation.chains.node.remove")}
              className="text-steel hover:text-neg px-1.5 text-lg leading-none cursor-pointer"
            >
              ×
            </button>
          </div>
        ) : null}
      </div>

      {node.kind === "action" ? (
        <ActionBody node={node} templates={templates} disabled={disabled} onChange={onChange} />
      ) : node.kind === "wait" ? (
        <WaitBody node={node} disabled={disabled} onChange={onChange} />
      ) : (
        <ConditionBody
          node={node}
          laterNodes={laterNodes}
          catalog={catalog}
          segments={segments}
          disabled={disabled}
          onChange={onChange}
        />
      )}
    </Card>
  );
}

// ──────────────────────────────── action ────────────────────────────────────
function ActionBody({
  node,
  templates,
  disabled,
  onChange,
}: {
  node: EditorActionNode;
  templates: Template[];
  disabled: boolean;
  onChange: (node: EditorNode) => void;
}) {
  const t = useT();
  const set = (patch: Partial<EditorActionNode>) => onChange({ ...node, ...patch });

  return (
    <div className="flex flex-col gap-3">
      <FormField label={t("automation.chains.action.label")}>
        <Select
          className={CTL_SM}
          value={node.action}
          disabled={disabled}
          onChange={(e) => set({ action: e.target.value as ActionKind })}
        >
          {ACTION_KINDS.map((a) => (
            <option key={a} value={a}>
              {t(`automation.chains.action.${a}` as MessageKey)}
            </option>
          ))}
        </Select>
      </FormField>

      {node.action === "bonus_grant" ? (
        <FormField
          label={t("automation.chains.action.bonus.label")}
          hint={t("automation.chains.action.bonus.hint")}
        >
          <Select
            className={CTL_SM}
            value={node.bonus}
            disabled={disabled}
            onChange={(e) => set({ bonus: e.target.value })}
          >
            {BONUS_CODES.map((code) => (
              <option key={code} value={code}>
                {t(`automation.chains.bonus.${code}` as MessageKey)}
              </option>
            ))}
          </Select>
        </FormField>
      ) : null}

      {node.action === "send_message" ? (
        <MessageBody node={node} templates={templates} disabled={disabled} onChange={onChange} />
      ) : null}

      {node.action === "desk_task" ? (
        <FormField
          label={t("automation.chains.action.reason.label")}
          hint={t("automation.chains.action.reason.hint")}
        >
          <Input
            value={node.reason}
            disabled={disabled}
            placeholder={t("automation.chains.action.reason.placeholder")}
            onChange={(e) => set({ reason: e.target.value })}
          />
        </FormField>
      ) : null}

      {node.action === "player_tag" ? (
        <FormField label={t("automation.chains.action.tag.label")} hint={t("automation.chains.action.tag.hint")}>
          <Input
            value={node.tag}
            disabled={disabled}
            placeholder={t("automation.chains.action.tag.placeholder")}
            onChange={(e) => set({ tag: e.target.value })}
          />
        </FormField>
      ) : null}
    </div>
  );
}

function MessageBody({
  node,
  templates,
  disabled,
  onChange,
}: {
  node: EditorActionNode;
  templates: Template[];
  disabled: boolean;
  onChange: (node: EditorNode) => void;
}) {
  const t = useT();
  const set = (patch: Partial<EditorActionNode>) => onChange({ ...node, ...patch });
  const channelTemplates = templates.filter((tpl) => tpl.channel_kind === node.channel);

  function setParam(pid: string, patch: Partial<{ key: string; value: string }>) {
    set({ params: node.params.map((p) => (p.pid === pid ? { ...p, ...patch } : p)) });
  }
  function removeParam(pid: string) {
    set({ params: node.params.filter((p) => p.pid !== pid) });
  }

  return (
    <div className="grid md:grid-cols-2 gap-3">
      <FormField label={t("automation.chains.action.channel.label")}>
        <Select
          value={node.channel}
          disabled={disabled}
          onChange={(e) => set({ channel: e.target.value as Channel })}
        >
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {t(`automation.chains.channel.${c}` as MessageKey)}
            </option>
          ))}
        </Select>
      </FormField>

      <FormField
        label={t("automation.chains.action.template.label")}
        hint={channelTemplates.length === 0 ? t("automation.chains.action.template.none") : undefined}
      >
        <Select
          value={node.template}
          disabled={disabled || channelTemplates.length === 0}
          onChange={(e) => set({ template: e.target.value })}
        >
          <option value="">{t("automation.chains.action.template.placeholder")}</option>
          {/* keep an unknown/foreign template id selectable so it isn't silently dropped */}
          {node.template && !channelTemplates.some((tpl) => tpl.template_id === node.template) ? (
            <option value={node.template}>{node.template}</option>
          ) : null}
          {channelTemplates.map((tpl) => (
            <option key={tpl.template_id} value={tpl.template_id}>
              {tpl.name}
            </option>
          ))}
        </Select>
      </FormField>

      <div className="md:col-span-2">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[12.5px] font-medium text-slate">
            {t("automation.chains.action.params.label")}
          </span>
          {!disabled ? (
            <Button variant="ghost" size="sm" onClick={() => set({ params: [...node.params, newParam()] })}>
              {t("automation.chains.action.params.add")}
            </Button>
          ) : null}
        </div>
        <p className="text-[12px] text-stone mb-2">
          {t("automation.chains.action.params.hint", { vars: TEMPLATE_VARS.map((v) => `{${v}}`).join(", ") })}
        </p>
        {node.params.length === 0 ? (
          <p className="text-[12px] text-stone italic">{t("automation.chains.action.params.empty")}</p>
        ) : (
          <div className="flex flex-col gap-2">
            {node.params.map((p) => (
              <div key={p.pid} className="flex items-center gap-2">
                <Input
                  className="w-[180px] font-mono"
                  value={p.key}
                  disabled={disabled}
                  placeholder={t("automation.chains.action.params.key")}
                  onChange={(e) => setParam(p.pid, { key: e.target.value })}
                />
                <span className="text-steel">=</span>
                <Input
                  className="flex-1 font-mono"
                  value={p.value}
                  disabled={disabled}
                  placeholder={t("automation.chains.action.params.value")}
                  onChange={(e) => setParam(p.pid, { value: e.target.value })}
                />
                {!disabled ? (
                  <button
                    type="button"
                    onClick={() => removeParam(p.pid)}
                    aria-label={t("automation.chains.node.remove")}
                    className="text-steel hover:text-neg text-lg leading-none px-1.5 cursor-pointer"
                  >
                    ×
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ──────────────────────────────── wait ──────────────────────────────────────
function WaitBody({
  node,
  disabled,
  onChange,
}: {
  node: EditorWaitNode;
  disabled: boolean;
  onChange: (node: EditorNode) => void;
}) {
  const t = useT();
  const set = (patch: Partial<EditorWaitNode>) => onChange({ ...node, ...patch });
  const hoursLabel =
    node.mode === "fixed"
      ? t("automation.chains.wait.hours.fixed")
      : t("automation.chains.wait.hours.fallback");

  return (
    <div className="flex flex-col gap-3">
      <div className="grid md:grid-cols-2 gap-3">
        <FormField label={t("automation.chains.wait.mode.label")} hint={t("automation.chains.wait.mode.hint")}>
          <Select value={node.mode} disabled={disabled} onChange={(e) => set({ mode: e.target.value as WaitMode })}>
            {WAIT_MODES.map((m) => (
              <option key={m} value={m}>
                {t(`automation.chains.waitMode.${m}` as MessageKey)}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label={hoursLabel}>
          <Input
            type="number"
            className="!w-[120px]"
            min={1}
            value={node.fallbackHours}
            disabled={disabled}
            onChange={(e) => set({ fallbackHours: e.target.value })}
          />
        </FormField>
      </div>

      <FormField label={t("automation.chains.wait.window.label")} hint={t("automation.chains.wait.window.hint")}>
        <label className="inline-flex items-center gap-2 h-[42px] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={node.hasWindow}
            disabled={disabled}
            onChange={(e) => set({ hasWindow: e.target.checked })}
            className="w-4 h-4 accent-primary"
          />
          <span className="text-[13.5px] text-slate">{t("automation.chains.wait.window.enable")}</span>
        </label>
      </FormField>

      {node.hasWindow ? (
        <div className="flex items-center gap-2">
          <span className="text-[12.5px] text-steel">{t("automation.chains.wait.window.from")}</span>
          <Input
            type="time"
            className="!w-auto"
            value={node.windowFrom}
            disabled={disabled}
            onChange={(e) => set({ windowFrom: e.target.value })}
          />
          <span className="text-[12.5px] text-steel">{t("automation.chains.wait.window.to")}</span>
          <Input
            type="time"
            className="!w-auto"
            value={node.windowTo}
            disabled={disabled}
            onChange={(e) => set({ windowTo: e.target.value })}
          />
        </div>
      ) : null}
    </div>
  );
}

// ──────────────────────────────── condition ─────────────────────────────────
function ConditionBody({
  node,
  laterNodes,
  catalog,
  segments,
  disabled,
  onChange,
}: {
  node: EditorConditionNode;
  laterNodes: NodeTarget[];
  catalog: FieldsCatalog;
  segments: Segment[];
  disabled: boolean;
  onChange: (node: EditorNode) => void;
}) {
  const t = useT();

  function onCondChange(next: LeafRow) {
    if (next.kind === "cond") onChange({ ...node, cond: next });
  }

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="text-[12.5px] font-medium text-slate mb-1.5">
          {t("automation.chains.condition.if")}
        </div>
        <ConditionRow
          row={node.cond}
          catalog={catalog}
          segments={segments}
          disabled={disabled}
          onChange={onCondChange}
          onRemove={() => onChange({ ...node, cond: newCondRow() })}
        />
      </div>

      {/* forward-only branches, rendered as indented arrows (text, no canvas) */}
      <div className="border-l-[3px] border-l-primary pl-3 ml-1 flex flex-col gap-2">
        <BranchSelect
          arrow="→"
          label={t("automation.chains.condition.then")}
          value={node.then}
          laterNodes={laterNodes}
          disabled={disabled}
          onChange={(v) => onChange({ ...node, then: v })}
        />
        <BranchSelect
          arrow="→"
          label={t("automation.chains.condition.else")}
          value={node.els}
          laterNodes={laterNodes}
          disabled={disabled}
          onChange={(v) => onChange({ ...node, els: v })}
        />
      </div>
    </div>
  );
}

function BranchSelect({
  arrow,
  label,
  value,
  laterNodes,
  disabled,
  onChange,
}: {
  arrow: string;
  label: string;
  value: string;
  laterNodes: NodeTarget[];
  disabled: boolean;
  onChange: (v: string) => void;
}) {
  const t = useT();
  // A jump target from an older definition may point above this node (no longer a
  // legal forward jump); keep it visible so it isn't silently lost on save.
  const isKnown =
    value === "" || EXIT_TARGETS.includes(value) || laterNodes.some((n) => n.id === value);

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-primary text-[13px] font-semibold">{arrow}</span>
      <span className="text-[12.5px] text-slate min-w-[42px]">{label}</span>
      <Select
        className={CTL_SM}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{t("automation.chains.condition.target.next")}</option>
        {laterNodes.map((n) => (
          <option key={n.id} value={n.id}>
            {n.label}
          </option>
        ))}
        <option value="exit_converted">{t("automation.chains.condition.target.exitConverted")}</option>
        <option value="exit">{t("automation.chains.condition.target.exit")}</option>
        {!isKnown ? <option value={value}>{value}</option> : null}
      </Select>
    </div>
  );
}
