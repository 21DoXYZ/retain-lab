"use client";

import { useMemo, useState } from "react";
import {
  Card,
  Eyebrow,
  Button,
  Modal,
  FormField,
  Input,
  Textarea,
  Pill,
  Banner,
} from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { formatInt } from "@/lib/format";
import { ConditionRow } from "./ConditionRow";
import {
  type FieldsCatalog,
  type Segment,
  type RawDefinition,
  type EditorDef,
  type RootRow,
  type AnyGroup,
  type LeafRow,
  SYS_NAME_RE,
  serialize,
  translitSysName,
  newCondRow,
  newNotSegRow,
  newEventRow,
  newAnyGroup,
} from "./catalog";
import { useSegmentPreview } from "./useSegmentPreview";

/**
 * SegmentEditor — the definition builder (W4-T2). Root = an AND group; rows are
 * conditions, «NOT in segment» / «Event» leaves, or nested OR groups (max depth
 * 2, so «+ OR group» is offered only at the root). A live counter debounces the
 * serialized definition through /segments/preview. Write actions (save / clone /
 * archive / add) are hidden for read-only roles; CSV export stays available.
 */

export interface EditorSeed {
  mode: "create" | "edit" | "clone";
  name: string;
  sysName: string;
  description: string;
  isTrigger: boolean;
  scheduleAt: string;
  definition: RawDefinition;
  /** Present only when editing a persisted segment (enables PUT / archive / export). */
  segmentId?: string;
  /** Editor model seed (already deserialized by the parent for the given catalog). */
  model: EditorDef;
}

interface SegmentEditorProps {
  catalog: FieldsCatalog;
  segments: Segment[];
  seed: EditorSeed;
  canWrite: boolean;
  onClose: () => void;
  onSaved: () => void;
  onClone: (seed: EditorSeed) => void;
}

export function SegmentEditor({
  catalog,
  segments,
  seed,
  canWrite,
  onClose,
  onSaved,
  onClone,
}: SegmentEditorProps) {
  const t = useT();

  const [name, setName] = useState(seed.name);
  const [sysName, setSysName] = useState(seed.sysName);
  const [sysEdited, setSysEdited] = useState(seed.mode !== "create");
  const [description, setDescription] = useState(seed.description);
  const [isTrigger, setIsTrigger] = useState(seed.isTrigger);
  const [scheduleAt, setScheduleAt] = useState(seed.scheduleAt);
  const [model, setModel] = useState<EditorDef>(seed.model);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);

  const def = useMemo(() => serialize(model, catalog), [model, catalog]);
  const preview = useSegmentPreview(def);

  const sysValid = SYS_NAME_RE.test(sysName);
  const canSave = canWrite && name.trim() !== "" && sysValid && !saving;

  // ── name → sys_name auto-transliteration (until the user edits sys_name) ──
  function onNameChange(v: string) {
    setName(v);
    if (!sysEdited) setSysName(translitSysName(v));
  }

  // ── immutable tree edits (root + one nested level) ──
  function setRootRow(rid: string, next: RootRow | null) {
    setModel((m) => ({
      rows: next === null ? m.rows.filter((r) => r.rid !== rid) : m.rows.map((r) => (r.rid === rid ? next : r)),
    }));
  }
  function addRootRow(row: RootRow) {
    setModel((m) => ({ rows: [...m.rows, row] }));
  }
  function setGroupLeaf(groupRid: string, leafRid: string, next: LeafRow | null) {
    setModel((m) => ({
      rows: m.rows.map((r) => {
        if (r.rid !== groupRid || r.kind !== "any") return r;
        const rows = next === null ? r.rows.filter((l) => l.rid !== leafRid) : r.rows.map((l) => (l.rid === leafRid ? next : l));
        return { ...r, rows };
      }),
    }));
  }
  function addGroupLeaf(groupRid: string, leaf: LeafRow) {
    setModel((m) => ({
      rows: m.rows.map((r) => (r.rid === groupRid && r.kind === "any" ? { ...r, rows: [...r.rows, leaf] } : r)),
    }));
  }

  // ── actions ──
  async function save() {
    if (!canSave) {
      if (name.trim() === "") setSaveError(t("automation.editor.save.nameRequired"));
      else if (!sysValid) setSaveError(t("automation.editor.field.sysNameError"));
      return;
    }
    setSaving(true);
    setSaveError(null);
    const body = {
      name: name.trim(),
      sys_name: sysName,
      description,
      definition: def,
      is_trigger: isTrigger,
      schedule_at: scheduleAt || "10:00",
    };
    try {
      if (seed.mode === "edit" && seed.segmentId) {
        await flaskFetch(`/api/v1/segments/${seed.segmentId}`, { method: "PUT", body });
      } else {
        await flaskFetch("/api/v1/segments", { method: "POST", body });
      }
      onSaved();
    } catch (e: unknown) {
      setSaveError(flaskErrorText(e, t, "automation.editor.save.failed"));
    } finally {
      setSaving(false);
    }
  }

  async function archive() {
    if (!seed.segmentId) return;
    setConfirmArchive(false);
    setSaving(true);
    setSaveError(null);
    try {
      await flaskFetch(`/api/v1/segments/${seed.segmentId}/archive`, { method: "POST", body: {} });
      onSaved();
    } catch (e: unknown) {
      setSaveError(flaskErrorText(e, t, "automation.editor.save.failed"));
      setSaving(false);
    }
  }

  function cloneCurrent() {
    onClone({
      mode: "clone",
      name,
      sysName: `${sysName}_copy`.slice(0, 64),
      description,
      isTrigger,
      scheduleAt,
      definition: def,
      model,
    });
  }

  async function exportCsv() {
    if (!seed.segmentId) return;
    try {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const base = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";
      const res = await fetch(`${base}/api/v1/segments/${seed.segmentId}/export.csv`, {
        headers: session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : undefined,
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const disposition = res.headers.get("Content-Disposition") ?? "";
      const match = /filename="?([^"]+)"?/.exec(disposition);
      const a = document.createElement("a");
      a.href = url;
      a.download = match?.[1] ?? `segment_${seed.sysName}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setSaveError(t("automation.editor.export.error"));
    }
  }

  const titleKey =
    seed.mode === "edit"
      ? "automation.editor.editTitle"
      : seed.mode === "clone"
        ? "automation.editor.cloneTitle"
        : "automation.editor.newTitle";

  return (
    <>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("automation.editor.back")}
          </Button>
          <h2 className="text-[20px] font-extrabold text-ink">{t(titleKey)}</h2>
        </div>
        <PreviewBadge preview={preview} />
      </div>

      {!canWrite ? (
        <Banner className="mt-4">{t("automation.editor.readonly")}</Banner>
      ) : null}

      {saveError ? (
        <div className="mt-4 rounded-card border border-neg/40 bg-neg/5 px-4 py-3 text-[13px] text-neg">
          {saveError}
        </div>
      ) : null}

      {/* ── properties ── */}
      <Eyebrow>{t("automation.editor.section.props")}</Eyebrow>
      <Card>
        <div className="grid md:grid-cols-2 gap-4">
          <FormField label={t("automation.editor.field.name")} required>
            <Input
              value={name}
              disabled={!canWrite}
              placeholder={t("automation.editor.field.namePlaceholder")}
              onChange={(e) => onNameChange(e.target.value)}
            />
          </FormField>
          <FormField
            label={t("automation.editor.field.sysName")}
            required
            hint={t("automation.editor.field.sysNameHint")}
            error={sysName !== "" && !sysValid ? t("automation.editor.field.sysNameError") : undefined}
          >
            <Input
              value={sysName}
              disabled={!canWrite}
              className="font-mono"
              onChange={(e) => {
                setSysName(e.target.value);
                setSysEdited(true);
              }}
            />
          </FormField>
          <FormField label={t("automation.editor.field.description")} className="md:col-span-2">
            <Textarea
              value={description}
              disabled={!canWrite}
              placeholder={t("automation.editor.field.descriptionPlaceholder")}
              onChange={(e) => setDescription(e.target.value)}
            />
          </FormField>
          <FormField label={t("automation.editor.field.schedule")} hint={t("automation.editor.field.scheduleHint")}>
            <Input
              type="time"
              className="!w-auto"
              value={scheduleAt}
              disabled={!canWrite}
              onChange={(e) => setScheduleAt(e.target.value)}
            />
          </FormField>
          <FormField label={t("automation.editor.field.trigger")} hint={t("automation.editor.field.triggerHint")}>
            <label className="inline-flex items-center gap-2 h-[42px] cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isTrigger}
                disabled={!canWrite}
                onChange={(e) => setIsTrigger(e.target.checked)}
                className="w-4 h-4 accent-primary"
              />
              <span className="text-[13.5px] text-slate">{t("automation.editor.field.triggerLabel")}</span>
            </label>
          </FormField>
        </div>
      </Card>

      {/* ── conditions tree ── */}
      <Eyebrow>{t("automation.editor.section.conditions")}</Eyebrow>
      <Card>
        <div className="text-[12.5px] font-semibold uppercase tracking-[0.5px] text-primary mb-3">
          {t("automation.editor.rootGroup")}
        </div>

        {model.rows.length === 0 ? (
          <div className="text-[13px] text-steel mb-3">{t("automation.editor.emptyConditions")}</div>
        ) : (
          <div className="flex flex-col gap-2">
            {model.rows.map((row) =>
              row.kind === "any" ? (
                <AnyGroupBlock
                  key={row.rid}
                  group={row}
                  catalog={catalog}
                  segments={segments}
                  excludeSysName={seed.sysName}
                  disabled={!canWrite}
                  onLeafChange={(leafRid, next) => setGroupLeaf(row.rid, leafRid, next)}
                  onAddLeaf={(leaf) => addGroupLeaf(row.rid, leaf)}
                  onRemoveGroup={() => setRootRow(row.rid, null)}
                />
              ) : (
                <ConditionRow
                  key={row.rid}
                  row={row}
                  catalog={catalog}
                  segments={segments}
                  excludeSysName={seed.sysName}
                  disabled={!canWrite}
                  onChange={(next) => setRootRow(row.rid, next)}
                  onRemove={() => setRootRow(row.rid, null)}
                />
              ),
            )}
          </div>
        )}

        {canWrite ? (
          <div className="flex flex-wrap gap-2 mt-4">
            <Button variant="ghost" size="sm" onClick={() => addRootRow(newCondRow())}>
              {t("automation.editor.add.condition")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => addRootRow(newNotSegRow())}>
              {t("automation.editor.add.notSegment")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => addRootRow(newEventRow(catalog))}>
              {t("automation.editor.add.event")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => addRootRow(newAnyGroup())}>
              {t("automation.editor.add.group")}
            </Button>
          </div>
        ) : null}
      </Card>

      {/* ── action bar ── */}
      <div className="flex flex-wrap items-center gap-2 mt-6">
        {canWrite ? (
          <Button variant="brand" onClick={save} loading={saving} disabled={!canSave}>
            {seed.mode === "edit" ? t("automation.editor.btn.save") : t("automation.editor.btn.saveCreate")}
          </Button>
        ) : null}
        {canWrite && seed.segmentId ? (
          <Button variant="ghost" onClick={cloneCurrent}>
            {t("automation.editor.btn.clone")}
          </Button>
        ) : null}
        {seed.segmentId ? (
          <Button variant="ghost" onClick={exportCsv}>
            {t("automation.editor.btn.export")}
          </Button>
        ) : null}
        {canWrite && seed.segmentId ? (
          <Button variant="ghost" className="!text-neg hover:!border-neg" onClick={() => setConfirmArchive(true)}>
            {t("automation.editor.btn.archive")}
          </Button>
        ) : null}
      </div>

      <Modal
        open={confirmArchive}
        onClose={() => setConfirmArchive(false)}
        title={t("automation.editor.archive.confirmTitle")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmArchive(false)}>
              {t("automation.editor.cancel")}
            </Button>
            <Button variant="primary" onClick={archive}>
              {t("automation.editor.archive.confirm")}
            </Button>
          </>
        }
      >
        {t("automation.editor.archive.confirmBody", { name })}
      </Modal>
    </>
  );
}

// ──────────────────────────── live preview badge ────────────────────────────
function PreviewBadge({ preview }: { preview: ReturnType<typeof useSegmentPreview> }) {
  const t = useT();
  if (preview.error) {
    return (
      <span className="text-[12.5px] text-neg max-w-[420px] text-right">
        {t("automation.editor.preview.error", { msg: preview.error })}
      </span>
    );
  }
  if (preview.loading) {
    return <Pill>{t("automation.editor.preview.loading")}</Pill>;
  }
  return <Pill live>{t("automation.editor.preview.count", { n: formatInt(preview.count) })}</Pill>;
}

// ──────────────────────────── OR group block ────────────────────────────────
function AnyGroupBlock({
  group,
  catalog,
  segments,
  excludeSysName,
  disabled,
  onLeafChange,
  onAddLeaf,
  onRemoveGroup,
}: {
  group: AnyGroup;
  catalog: FieldsCatalog;
  segments: Segment[];
  excludeSysName?: string;
  disabled: boolean;
  onLeafChange: (leafRid: string, next: LeafRow | null) => void;
  onAddLeaf: (leaf: LeafRow) => void;
  onRemoveGroup: () => void;
}) {
  const t = useT();
  return (
    <div className="rounded-card border border-hair2 border-l-[3px] border-l-primary bg-surface/40 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[12px] font-semibold uppercase tracking-[0.5px] text-primary">
          {t("automation.editor.anyGroup")}
        </span>
        {!disabled ? (
          <button
            type="button"
            onClick={onRemoveGroup}
            className="text-steel hover:text-neg text-[12.5px] cursor-pointer"
          >
            {t("automation.editor.removeGroup")} ×
          </button>
        ) : null}
      </div>
      <div className="flex flex-col gap-2">
        {group.rows.map((leaf) => (
          <ConditionRow
            key={leaf.rid}
            row={leaf}
            catalog={catalog}
            segments={segments}
            excludeSysName={excludeSysName}
            disabled={disabled}
            onChange={(next) => onLeafChange(leaf.rid, next)}
            onRemove={() => onLeafChange(leaf.rid, null)}
          />
        ))}
      </div>
      {!disabled ? (
        <div className="flex flex-wrap gap-2 mt-3">
          <Button variant="ghost" size="sm" onClick={() => onAddLeaf(newCondRow())}>
            {t("automation.editor.add.condition")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onAddLeaf(newNotSegRow())}>
            {t("automation.editor.add.notSegment")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onAddLeaf(newEventRow(catalog))}>
            {t("automation.editor.add.event")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
