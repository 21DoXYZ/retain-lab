"use client";

import { useMemo, useState } from "react";
import {
  Card,
  Eyebrow,
  Button,
  Badge,
  Pill,
  Tabs,
  Modal,
  FormField,
  Input,
  Select,
  Banner,
  Skeleton,
  ErrorState,
} from "@/components/ui";
import { useT, type MessageKey } from "@/lib/i18n";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useFlaskData } from "@/components/marketing/useFlaskData";
import { isLeafComplete } from "./catalog";
import { NodeCard, type NodeTarget } from "./NodeCard";
import { ChainStats } from "./ChainStats";
import {
  type Chain,
  type ChainStatus,
  type ChainEditorModel,
  type EditorNode,
  type FieldsCatalog,
  type Segment,
  type Template,
  type TriggerKind,
  TRIGGER_EVENT_TYPES,
  GOAL_EVENTS,
  newActionNode,
  newWaitNode,
  newConditionNode,
  serializeDefinition,
  modelFromDefinition,
  latestDefinition,
  pendingVersionNo,
} from "./chainModel";

/**
 * ChainEditor — the linear (vertical-flow) chain builder (W4-T5, §2–3).
 *
 * Outer component owns the four fetch states (chain + segment field catalog +
 * segments + templates). Once everything is in, it hands a keyed inner component
 * the loaded data; the inner seeds its editor model synchronously from props
 * (useState initializer — no set-state-in-effect), so React-hooks purity holds
 * and in-progress edits survive draft saves (the model stays the source of truth).
 */

const STATUS_TONE: Record<ChainStatus, { bg: string; fg: string }> = {
  draft: { bg: "#eef2f6", fg: "#475569" },
  active: { bg: "#dcfce7", fg: "#166534" },
  paused: { bg: "#fef9c3", fg: "#854d0e" },
  archived: { bg: "#f1f5f9", fg: "#94a3b8" },
};

interface ChainEditorProps {
  chainId: string;
  canWrite: boolean;
  /** Close the editor and reload the list (reflects any status/version change). */
  onClose: () => void;
}

export function ChainEditor({ chainId, canWrite, onClose }: ChainEditorProps) {
  const t = useT();
  const chainQ = useFlaskData<Chain>(`/api/v1/chains/${chainId}`);
  const catalogQ = useFlaskData<FieldsCatalog>("/api/v1/segments/fields");
  const segmentsQ = useFlaskData<{ segments: Segment[] }>("/api/v1/segments");
  const templatesQ = useFlaskData<{ templates: Template[] }>("/api/v1/chains/templates");

  const loading =
    chainQ.state === "loading" ||
    catalogQ.state === "loading" ||
    segmentsQ.state === "loading" ||
    templatesQ.state === "loading";
  const errored =
    chainQ.state === "error" ||
    catalogQ.state === "error" ||
    segmentsQ.state === "error" ||
    templatesQ.state === "error";

  if (loading) {
    return (
      <>
        <EditorTopBar title={t("automation.chains.editor.loading")} onClose={onClose} />
        <Card className="mt-4">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-24 w-full mt-4" />
          <Skeleton className="h-24 w-full mt-3" />
        </Card>
      </>
    );
  }

  if (errored || !chainQ.data || !catalogQ.data || !segmentsQ.data || !templatesQ.data) {
    return (
      <>
        <EditorTopBar title={t("automation.chains.editor.title")} onClose={onClose} />
        <div className="mt-6">
          <ErrorState
            title={t("automation.chains.error.title")}
            description={
              chainQ.error ?? catalogQ.error ?? segmentsQ.error ?? templatesQ.error ?? t("automation.chains.error.desc")
            }
            onRetry={() => {
              chainQ.reload();
              catalogQ.reload();
              segmentsQ.reload();
              templatesQ.reload();
            }}
          />
        </div>
      </>
    );
  }

  return (
    <ChainEditorReady
      key={chainId}
      chain={chainQ.data}
      catalog={catalogQ.data}
      segments={segmentsQ.data.segments}
      templates={templatesQ.data.templates}
      canWrite={canWrite}
      onClose={onClose}
    />
  );
}

function EditorTopBar({
  title,
  onClose,
  right,
}: {
  title: string;
  onClose: () => void;
  right?: React.ReactNode;
}) {
  const t = useT();
  return (
    <div className="flex items-center justify-between gap-3 flex-wrap">
      <div className="flex items-center gap-3 min-w-0">
        <Button variant="ghost" size="sm" onClick={onClose}>
          {t("automation.chains.editor.back")}
        </Button>
        <h2 className="text-[20px] font-extrabold text-ink truncate">{title}</h2>
      </div>
      {right}
    </div>
  );
}

// ─────────────────────────────── ready (seeded) ─────────────────────────────
interface ReadyProps {
  chain: Chain;
  catalog: FieldsCatalog;
  segments: Segment[];
  templates: Template[];
  canWrite: boolean;
  onClose: () => void;
}

function ChainEditorReady({ chain, catalog, segments, templates, canWrite, onClose }: ReadyProps) {
  const t = useT();

  const [model, setModel] = useState<ChainEditorModel>(() =>
    modelFromDefinition(latestDefinition(chain), catalog),
  );
  const [name, setName] = useState(chain.name);
  const [description, setDescription] = useState(chain.description);
  const [status, setStatus] = useState<ChainStatus>(chain.status);
  const [tab, setTab] = useState<"editor" | "stats">("editor");

  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [pendingVer, setPendingVer] = useState<number>(() => pendingVersionNo(chain));

  const [confirmActivate, setConfirmActivate] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [cloneName, setCloneName] = useState(`${chain.name} (копия)`);

  const isDraft = status === "draft";
  const isArchived = status === "archived";
  const editable = canWrite && !isArchived;

  // incomplete conditions — the server validator only checks `if` is an object,
  // so we guard completeness client-side before activation.
  const incompleteConditions = useMemo(
    () =>
      model.nodes.filter((n) => n.kind === "condition" && !isLeafComplete(n.cond, catalog)).map((n) => n.id),
    [model.nodes, catalog],
  );

  const activeSegments = useMemo(
    () => segments.filter((s) => s.archived_at == null),
    [segments],
  );

  function nodeShortLabel(node: EditorNode, idx: number): string {
    const n = idx + 1;
    if (node.kind === "action") return `${n} · ${t(`automation.chains.action.${node.action}` as MessageKey)}`;
    if (node.kind === "wait") return `${n} · ${t(`automation.chains.waitMode.${node.mode}` as MessageKey)}`;
    return `${n} · ${t("automation.chains.node.kind.condition")}`;
  }
  const nodeLabels = useMemo(() => {
    const out: Record<string, string> = {};
    model.nodes.forEach((n, i) => {
      out[n.id] = nodeShortLabel(n, i);
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model.nodes, t]);

  // ── immutable node edits ──
  function updateNode(id: string, next: EditorNode) {
    setModel((m) => ({ ...m, nodes: m.nodes.map((n) => (n.id === id ? next : n)) }));
  }
  function removeNode(id: string) {
    setModel((m) => ({ ...m, nodes: m.nodes.filter((n) => n.id !== id) }));
  }
  function moveNode(index: number, dir: -1 | 1) {
    setModel((m) => {
      const j = index + dir;
      if (j < 0 || j >= m.nodes.length) return m;
      const nodes = [...m.nodes];
      [nodes[index], nodes[j]] = [nodes[j], nodes[index]];
      return { ...m, nodes };
    });
  }
  function addNode(kind: "action" | "wait" | "condition") {
    setModel((m) => {
      const ids = m.nodes.map((n) => n.id);
      const node =
        kind === "action" ? newActionNode(ids) : kind === "wait" ? newWaitNode(ids) : newConditionNode(ids);
      return { ...m, nodes: [...m.nodes, node] };
    });
  }

  // ── persistence ──
  /** PUT header (draft only) then POST definition. Returns version_no or null on error. */
  async function persist(): Promise<number | null> {
    setActionError(null);
    setSavedNote(null);
    try {
      if (isDraft && (name.trim() !== chain.name || description !== chain.description) && name.trim() !== "") {
        await flaskFetch(`/api/v1/chains/${chain.chain_id}`, {
          method: "PUT",
          body: { name: name.trim(), description },
        });
      }
      const res = await flaskFetch<{ version_no: number }>(
        `/api/v1/chains/${chain.chain_id}/definition`,
        { method: "POST", body: { definition: serializeDefinition(model, catalog) } },
      );
      setPendingVer(res.version_no);
      return res.version_no;
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "automation.chains.editor.saveFailed"));
      return null;
    }
  }

  async function saveDraft() {
    setSaving(true);
    const v = await persist();
    setSaving(false);
    if (v != null) setSavedNote(t("automation.chains.editor.savedNote", { n: String(v) }));
  }

  function onActivateClick() {
    setActionError(null);
    if (incompleteConditions.length > 0) {
      setActionError(t("automation.chains.editor.incompleteConditions", { ids: incompleteConditions.join(", ") }));
      return;
    }
    void (async () => {
      setSaving(true);
      const v = await persist();
      setSaving(false);
      if (v != null) setConfirmActivate(true);
    })();
  }

  async function doActivate() {
    setConfirmActivate(false);
    setSaving(true);
    try {
      await flaskFetch(`/api/v1/chains/${chain.chain_id}/activate`, { method: "POST", body: {} });
      onClose();
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "automation.chains.editor.activateFailed"));
      setSaving(false);
    }
  }

  async function doPause() {
    setActionError(null);
    setSaving(true);
    try {
      await flaskFetch(`/api/v1/chains/${chain.chain_id}/pause`, { method: "POST", body: {} });
      setStatus("paused");
      setSavedNote(t("automation.chains.editor.pausedNote"));
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "automation.chains.editor.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function doArchive() {
    setConfirmArchive(false);
    setSaving(true);
    try {
      await flaskFetch(`/api/v1/chains/${chain.chain_id}/archive`, { method: "POST", body: {} });
      onClose();
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "automation.chains.editor.saveFailed"));
      setSaving(false);
    }
  }

  async function doClone() {
    if (cloneName.trim() === "") return;
    setCloneOpen(false);
    setSaving(true);
    try {
      await flaskFetch(`/api/v1/chains/${chain.chain_id}/clone`, {
        method: "POST",
        body: { name: cloneName.trim() },
      });
      onClose();
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "automation.chains.editor.cloneFailed"));
      setSaving(false);
    }
  }

  const statusTone = STATUS_TONE[status];

  return (
    <>
      <EditorTopBar
        title={name || t("automation.chains.editor.title")}
        onClose={onClose}
        right={
          <div className="flex items-center gap-2">
            <Badge bg={statusTone.bg} fg={statusTone.fg}>
              {t(`automation.chains.status.${status}` as MessageKey)}
            </Badge>
            <Pill>{t("automation.chains.editor.versionPill", { n: String(pendingVer) })}</Pill>
          </div>
        }
      />

      {!canWrite ? <Banner className="mt-4">{t("automation.chains.editor.readonly")}</Banner> : null}
      {isArchived ? <Banner className="mt-4">{t("automation.chains.editor.archivedNote")}</Banner> : null}

      <div className="mt-4">
        <Tabs
          value={tab}
          onChange={(k) => setTab(k as "editor" | "stats")}
          tabs={[
            { key: "editor", label: t("automation.chains.tab.editor") },
            { key: "stats", label: t("automation.chains.tab.stats") },
          ]}
        />
      </div>

      {tab === "stats" ? (
        <div className="mt-5">
          <ChainStats chainId={chain.chain_id} nodeLabels={nodeLabels} />
        </div>
      ) : (
        <>
          {actionError ? (
            <div className="mt-4 rounded-card border border-neg/40 bg-neg/5 px-4 py-3 text-[13px] text-neg whitespace-pre-wrap">
              {actionError}
            </div>
          ) : null}
          {savedNote ? (
            <div className="mt-4 rounded-card border border-pos/40 bg-pos/5 px-4 py-3 text-[13px] text-pos">
              {savedNote}
            </div>
          ) : null}

          {/* ── properties ── */}
          <Eyebrow>{t("automation.chains.editor.section.props")}</Eyebrow>
          <Card>
            <div className="grid md:grid-cols-2 gap-4">
              <FormField
                label={t("automation.chains.editor.field.name")}
                required
                hint={!isDraft ? t("automation.chains.editor.field.nameLocked") : undefined}
              >
                <Input
                  value={name}
                  disabled={!editable || !isDraft}
                  placeholder={t("automation.chains.editor.field.namePlaceholder")}
                  onChange={(e) => setName(e.target.value)}
                />
              </FormField>
              <FormField label={t("automation.chains.editor.field.description")}>
                <Input
                  value={description}
                  disabled={!editable || !isDraft}
                  placeholder={t("automation.chains.editor.field.descriptionPlaceholder")}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </FormField>
            </div>
          </Card>

          {/* ── trigger ── */}
          <Eyebrow>{t("automation.chains.editor.section.trigger")}</Eyebrow>
          <TriggerSection
            model={model}
            segments={activeSegments}
            disabled={!editable}
            onChange={setModel}
          />

          {/* ── control + goal ── */}
          <Eyebrow>{t("automation.chains.editor.section.goal")}</Eyebrow>
          <Card>
            <div className="grid md:grid-cols-3 gap-4">
              <FormField
                label={t("automation.chains.editor.field.controlPct")}
                hint={t("automation.chains.editor.field.controlPctHint")}
              >
                <Input
                  type="number"
                  min={0}
                  max={50}
                  className="!w-[120px]"
                  value={model.controlPct}
                  disabled={!editable}
                  onChange={(e) => setModel((m) => ({ ...m, controlPct: e.target.value }))}
                />
              </FormField>
              <FormField label={t("automation.chains.editor.field.goalEvent")}>
                <Select
                  value={model.goalEvent}
                  disabled={!editable}
                  onChange={(e) => setModel((m) => ({ ...m, goalEvent: e.target.value }))}
                >
                  {GOAL_EVENTS.map((ev) => (
                    <option key={ev} value={ev}>
                      {t(`automation.chains.goalEvent.${ev}` as MessageKey)}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField
                label={t("automation.chains.editor.field.attribution")}
                hint={t("automation.chains.editor.field.attributionHint")}
              >
                <Input
                  type="number"
                  min={1}
                  max={90}
                  className="!w-[120px]"
                  value={model.goalAttributionDays}
                  disabled={!editable}
                  onChange={(e) => setModel((m) => ({ ...m, goalAttributionDays: e.target.value }))}
                />
              </FormField>
            </div>
          </Card>

          {/* ── nodes ── */}
          <Eyebrow>{t("automation.chains.editor.section.nodes")}</Eyebrow>
          {incompleteConditions.length > 0 ? (
            <Banner className="!mt-0 mb-3">
              {t("automation.chains.editor.incompleteConditions", { ids: incompleteConditions.join(", ") })}
            </Banner>
          ) : null}

          {model.nodes.length === 0 ? (
            <Card>
              <p className="text-[13px] text-steel">{t("automation.chains.editor.emptyNodes")}</p>
            </Card>
          ) : (
            <div className="flex flex-col gap-3">
              {model.nodes.map((node, index) => {
                const laterNodes: NodeTarget[] = model.nodes
                  .slice(index + 1)
                  .map((n, j) => ({ id: n.id, label: nodeShortLabel(n, index + 1 + j) }));
                return (
                  <NodeCard
                    key={node.id}
                    node={node}
                    index={index}
                    total={model.nodes.length}
                    laterNodes={laterNodes}
                    catalog={catalog}
                    segments={segments}
                    templates={templates}
                    disabled={!editable}
                    onChange={(next) => updateNode(node.id, next)}
                    onMove={(dir) => moveNode(index, dir)}
                    onRemove={() => removeNode(node.id)}
                  />
                );
              })}
            </div>
          )}

          {editable ? (
            <div className="flex flex-wrap gap-2 mt-3">
              <Button variant="ghost" size="sm" onClick={() => addNode("action")}>
                {t("automation.chains.editor.add.action")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => addNode("wait")}>
                {t("automation.chains.editor.add.wait")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => addNode("condition")}>
                {t("automation.chains.editor.add.condition")}
              </Button>
            </div>
          ) : null}

          {/* ── action bar ── */}
          <div className="flex flex-wrap items-center gap-2 mt-6">
            {editable ? (
              <Button variant="primary" onClick={saveDraft} loading={saving}>
                {t("automation.chains.editor.btn.saveDraft")}
              </Button>
            ) : null}
            {editable ? (
              <Button variant="brand" onClick={onActivateClick} disabled={saving}>
                {t("automation.chains.editor.btn.activate")}
              </Button>
            ) : null}
            {canWrite && status === "active" ? (
              <Button variant="ghost" onClick={doPause} disabled={saving}>
                {t("automation.chains.editor.btn.pause")}
              </Button>
            ) : null}
            {canWrite ? (
              <Button variant="ghost" onClick={() => setCloneOpen(true)} disabled={saving}>
                {t("automation.chains.editor.btn.clone")}
              </Button>
            ) : null}
            {canWrite && !isArchived ? (
              <Button
                variant="ghost"
                className="!text-neg hover:!border-neg"
                onClick={() => setConfirmArchive(true)}
                disabled={saving}
              >
                {t("automation.chains.editor.btn.archive")}
              </Button>
            ) : null}
          </div>
        </>
      )}

      {/* ── confirmations ── */}
      <Modal
        open={confirmActivate}
        onClose={() => setConfirmActivate(false)}
        title={t("automation.chains.editor.activate.title")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmActivate(false)}>
              {t("automation.chains.editor.cancel")}
            </Button>
            <Button variant="brand" onClick={doActivate}>
              {t("automation.chains.editor.activate.confirm")}
            </Button>
          </>
        }
      >
        {t("automation.chains.editor.activate.body", { n: String(pendingVer) })}
      </Modal>

      <Modal
        open={confirmArchive}
        onClose={() => setConfirmArchive(false)}
        title={t("automation.chains.editor.archive.title")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmArchive(false)}>
              {t("automation.chains.editor.cancel")}
            </Button>
            <Button variant="primary" onClick={doArchive}>
              {t("automation.chains.editor.archive.confirm")}
            </Button>
          </>
        }
      >
        {t("automation.chains.editor.archive.body", { name })}
      </Modal>

      <Modal
        open={cloneOpen}
        onClose={() => setCloneOpen(false)}
        title={t("automation.chains.editor.clone.title")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setCloneOpen(false)}>
              {t("automation.chains.editor.cancel")}
            </Button>
            <Button variant="brand" onClick={doClone} disabled={cloneName.trim() === ""}>
              {t("automation.chains.editor.clone.confirm")}
            </Button>
          </>
        }
      >
        <FormField label={t("automation.chains.editor.clone.nameLabel")}>
          <Input value={cloneName} onChange={(e) => setCloneName(e.target.value)} autoFocus />
        </FormField>
      </Modal>
    </>
  );
}

// ─────────────────────────────── trigger section ────────────────────────────
function TriggerSection({
  model,
  segments,
  disabled,
  onChange,
}: {
  model: ChainEditorModel;
  segments: Segment[];
  disabled: boolean;
  onChange: (updater: (m: ChainEditorModel) => ChainEditorModel) => void;
}) {
  const t = useT();
  const kind = model.triggerKind;
  const unknownSegment =
    model.triggerSegment !== "" && !segments.some((s) => s.sys_name === model.triggerSegment);

  return (
    <Card>
      <div className="grid md:grid-cols-2 gap-4">
        <FormField label={t("automation.chains.trigger.kind")}>
          <Select
            value={kind}
            disabled={disabled}
            onChange={(e) => onChange((m) => ({ ...m, triggerKind: e.target.value as TriggerKind }))}
          >
            <option value="segment">{t("automation.chains.trigger.kind.segment")}</option>
            <option value="event">{t("automation.chains.trigger.kind.event")}</option>
            {/* schedule — phase 3б; selectable only if already set on an old definition */}
            <option value="schedule" disabled={kind !== "schedule"}>
              {t("automation.chains.trigger.kind.schedule")} · {t("automation.chains.trigger.phase3b")}
            </option>
          </Select>
        </FormField>

        {kind === "segment" ? (
          <>
            <FormField
              label={t("automation.chains.trigger.segment")}
              hint={segments.length === 0 ? t("automation.chains.trigger.segment.none") : undefined}
            >
              <Select
                value={model.triggerSegment}
                disabled={disabled}
                onChange={(e) => onChange((m) => ({ ...m, triggerSegment: e.target.value }))}
              >
                <option value="">{t("automation.chains.trigger.segment.placeholder")}</option>
                {unknownSegment ? <option value={model.triggerSegment}>{model.triggerSegment}</option> : null}
                {segments.map((s) => (
                  <option key={s.sys_name} value={s.sys_name}>
                    {s.name} ({s.sys_name})
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField
              label={t("automation.chains.trigger.reentry")}
              hint={t("automation.chains.trigger.reentryHint")}
            >
              <Input
                type="number"
                min={0}
                max={365}
                className="!w-[120px]"
                value={model.triggerReentryDays}
                disabled={disabled}
                onChange={(e) => onChange((m) => ({ ...m, triggerReentryDays: e.target.value }))}
              />
            </FormField>
          </>
        ) : null}

        {kind === "event" ? (
          <FormField label={t("automation.chains.trigger.event")}>
            <Select
              value={model.triggerEventType}
              disabled={disabled}
              onChange={(e) => onChange((m) => ({ ...m, triggerEventType: e.target.value }))}
            >
              {TRIGGER_EVENT_TYPES.map((ev) => (
                <option key={ev} value={ev}>
                  {t(`automation.chains.trigger.event.${ev}` as MessageKey)}
                </option>
              ))}
            </Select>
          </FormField>
        ) : null}

        {kind === "schedule" ? (
          <FormField label={t("automation.chains.trigger.cron")} hint={t("automation.chains.trigger.phase3b")}>
            <Input value={model.triggerCron} disabled className="font-mono" />
          </FormField>
        ) : null}
      </div>
    </Card>
  );
}
