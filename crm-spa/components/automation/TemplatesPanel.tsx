"use client";

import { useState } from "react";
import {
  Button,
  Badge,
  Pill,
  PillRow,
  DataTable,
  Modal,
  FormField,
  Input,
  Textarea,
  Select,
  Tabs,
  ErrorState,
  type Column,
  type TableState,
} from "@/components/ui";
import { useT, type MessageKey } from "@/lib/i18n";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useFlaskData } from "@/components/marketing/useFlaskData";
import { type Template, type Channel, CHANNELS, TEMPLATE_VARS } from "./chainModel";

/**
 * TemplatesPanel — message templates CRUD (W4-T5, §5). Templates carry ru/en/tr
 * bodies with {vars} placeholders; a template is picked by a send_message node.
 * CRUD via /api/v1/chains/templates (POST/PUT/DELETE). Write actions are gated by
 * `canWrite` (mirrors WRITE_ROLES in api/chains.py).
 */

const LOCALES = ["ru", "en", "tr"] as const;
type Loc = (typeof LOCALES)[number];

interface EditorState {
  template_id?: string;
  name: string;
  channel_kind: Channel;
  texts: Record<string, string>;
}

interface TemplatesPanelProps {
  canWrite: boolean;
}

export function TemplatesPanel({ canWrite }: TemplatesPanelProps) {
  const t = useT();
  const listQ = useFlaskData<{ templates: Template[] }>("/api/v1/chains/templates");
  const [editor, setEditor] = useState<EditorState | null>(null);

  const templates = listQ.data?.templates ?? [];

  function openCreate() {
    setEditor({ name: "", channel_kind: "casino_webhook", texts: { ru: "", en: "", tr: "" } });
  }
  function openEdit(tpl: Template) {
    setEditor({
      template_id: tpl.template_id,
      name: tpl.name,
      channel_kind: tpl.channel_kind,
      texts: { ru: "", en: "", tr: "", ...tpl.texts },
    });
  }

  const loading = listQ.state === "loading";
  const tableState: TableState = loading ? "loading" : templates.length === 0 ? "empty" : "data";

  const columns: Column<Template>[] = [
    {
      key: "name",
      header: t("automation.chains.tpl.col.name"),
      align: "left",
      render: (tpl) => (
        <button
          type="button"
          onClick={() => openEdit(tpl)}
          className="text-primary font-medium hover:underline text-left cursor-pointer"
        >
          {tpl.name}
        </button>
      ),
    },
    {
      key: "channel",
      header: t("automation.chains.tpl.col.channel"),
      align: "left",
      render: (tpl) => (
        <Badge bg="#eef2f6" fg="#475569">
          {t(`automation.chains.channel.${tpl.channel_kind}` as MessageKey)}
        </Badge>
      ),
    },
    {
      key: "langs",
      header: t("automation.chains.tpl.col.langs"),
      align: "left",
      render: (tpl) => (
        <div className="flex gap-1">
          {LOCALES.map((loc) => {
            const has = (tpl.texts?.[loc] ?? "").trim() !== "";
            return (
              <span
                key={loc}
                className={
                  "inline-block text-[11px] font-semibold rounded px-1.5 py-[1px] " +
                  (has ? "bg-cream text-ink" : "bg-hair2/50 text-stone")
                }
              >
                {loc.toUpperCase()}
              </span>
            );
          })}
        </div>
      ),
    },
    {
      key: "updated",
      header: t("automation.chains.tpl.col.updated"),
      align: "left",
      render: (tpl) => <span className="text-steel">{formatDateTime(tpl.updated_at)}</span>,
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <p className="text-[13px] text-steel max-w-2xl">{t("automation.chains.tpl.lead")}</p>
        {canWrite ? (
          <Button variant="brand" size="sm" onClick={openCreate}>
            {t("automation.chains.tpl.create")}
          </Button>
        ) : (
          <Pill>{t("automation.chains.readOnlyPill")}</Pill>
        )}
      </div>

      {listQ.state === "error" ? (
        <ErrorState
          title={t("automation.chains.tpl.error.title")}
          description={listQ.error ?? t("automation.chains.error.desc")}
          onRetry={listQ.reload}
        />
      ) : (
        <div className="overflow-hidden rounded-card border border-hair bg-canvas">
          <DataTable
            columns={columns}
            rows={templates}
            getRowKey={(tpl) => tpl.template_id}
            state={tableState}
            emptyTitle={t("automation.chains.tpl.empty.title")}
            emptyDescription={t("automation.chains.tpl.empty.desc")}
          />
        </div>
      )}

      {editor ? (
        <TemplateEditorModal
          initial={editor}
          canWrite={canWrite}
          onClose={() => setEditor(null)}
          onSaved={() => {
            setEditor(null);
            listQ.reload();
          }}
        />
      ) : null}
    </div>
  );
}

// ─────────────────────────────── editor modal ───────────────────────────────
function TemplateEditorModal({
  initial,
  canWrite,
  onClose,
  onSaved,
}: {
  initial: EditorState;
  canWrite: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const [name, setName] = useState(initial.name);
  const [channel, setChannel] = useState<Channel>(initial.channel_kind);
  const [texts, setTexts] = useState<Record<string, string>>(initial.texts);
  const [lang, setLang] = useState<Loc>("ru");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const isEdit = !!initial.template_id;
  const canSave = canWrite && name.trim() !== "" && !saving;

  async function save() {
    if (!canSave) {
      if (name.trim() === "") setError(t("automation.chains.tpl.nameRequired"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = { name: name.trim(), channel_kind: channel, texts };
      if (isEdit) {
        await flaskFetch(`/api/v1/chains/templates/${initial.template_id}`, { method: "PUT", body });
      } else {
        await flaskFetch("/api/v1/chains/templates", { method: "POST", body });
      }
      onSaved();
    } catch (e: unknown) {
      setError(flaskErrorText(e, t, "automation.chains.tpl.saveFailed"));
      setSaving(false);
    }
  }

  async function remove() {
    setConfirmDelete(false);
    setSaving(true);
    setError(null);
    try {
      await flaskFetch(`/api/v1/chains/templates/${initial.template_id}`, { method: "DELETE" });
      onSaved();
    } catch (e: unknown) {
      setError(flaskErrorText(e, t, "automation.chains.tpl.saveFailed"));
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      widthClass="max-w-2xl"
      title={isEdit ? t("automation.chains.tpl.editTitle") : t("automation.chains.tpl.newTitle")}
      footer={
        <div className="flex items-center justify-between w-full gap-2">
          <div>
            {canWrite && isEdit ? (
              <Button
                variant="ghost"
                className="!text-neg hover:!border-neg"
                onClick={() => setConfirmDelete(true)}
                disabled={saving}
              >
                {t("automation.chains.tpl.delete")}
              </Button>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              {t("automation.chains.editor.cancel")}
            </Button>
            {canWrite ? (
              <Button variant="brand" onClick={save} loading={saving} disabled={!canSave}>
                {t("automation.chains.tpl.save")}
              </Button>
            ) : null}
          </div>
        </div>
      }
    >
      {error ? (
        <div className="mb-4 rounded-card border border-neg/40 bg-neg/5 px-4 py-3 text-[13px] text-neg">
          {error}
        </div>
      ) : null}

      {confirmDelete ? (
        <div className="mb-4 rounded-card border border-neg/40 bg-neg/5 px-4 py-3 text-[13px]">
          <p className="text-ink mb-2">{t("automation.chains.tpl.delete.confirm", { name })}</p>
          <PillRow>
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
              {t("automation.chains.editor.cancel")}
            </Button>
            <Button variant="primary" size="sm" onClick={remove}>
              {t("automation.chains.tpl.delete")}
            </Button>
          </PillRow>
        </div>
      ) : null}

      <div className="grid md:grid-cols-2 gap-4">
        <FormField label={t("automation.chains.tpl.field.name")} required>
          <Input
            value={name}
            disabled={!canWrite}
            placeholder={t("automation.chains.tpl.field.namePlaceholder")}
            onChange={(e) => setName(e.target.value)}
          />
        </FormField>
        <FormField label={t("automation.chains.tpl.field.channel")}>
          <Select value={channel} disabled={!canWrite} onChange={(e) => setChannel(e.target.value as Channel)}>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {t(`automation.chains.channel.${c}` as MessageKey)}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <div className="mt-4">
        <Tabs
          value={lang}
          onChange={(k) => setLang(k as Loc)}
          tabs={LOCALES.map((loc) => ({ key: loc, label: loc.toUpperCase() }))}
        />
        <div className="mt-3">
          <Textarea
            value={texts[lang] ?? ""}
            disabled={!canWrite}
            className="min-h-[140px]"
            placeholder={t("automation.chains.tpl.field.bodyPlaceholder")}
            onChange={(e) => setTexts((prev) => ({ ...prev, [lang]: e.target.value }))}
          />
          <p className="text-[12px] text-stone mt-2">
            {t("automation.chains.tpl.field.varsHint", { vars: TEMPLATE_VARS.map((v) => `{${v}}`).join(", ") })}
          </p>
        </div>
      </div>
    </Modal>
  );
}
