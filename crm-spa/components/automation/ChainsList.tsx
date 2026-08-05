"use client";

import { useMemo, useState } from "react";
import {
  PageHeader,
  Button,
  Pill,
  Badge,
  ChipBar,
  Input,
  Tabs,
  DataTable,
  Modal,
  FormField,
  Textarea,
  ErrorState,
  type Column,
  type TableState,
} from "@/components/ui";
import { useT, type MessageKey } from "@/lib/i18n";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { formatInt, formatDateTime } from "@/lib/format";
import { useRole } from "@/lib/role-context";
import type { UserRole } from "@/lib/types";
import { useFlaskData } from "@/components/marketing/useFlaskData";
import { ChainEditor } from "./ChainEditor";
import { TemplatesPanel } from "./TemplatesPanel";
import { type Chain, type ChainListItem, type ChainStatus } from "./chainModel";

/**
 * /chains — automation chain builder home (W4-T5). Lists saved chains with their
 * status / version / live enrollment count, routes into the linear editor, and
 * runs the lifecycle actions (activate / pause / archive / clone) with confirms.
 * A second tab holds the message TemplatesPanel. Write roles mirror WRITE_ROLES
 * in api/chains.py; read-only roles see the list + editor without the controls.
 */

const WRITE_ROLES: readonly UserRole[] = ["marketing_manager", "head_retention", "super_admin"];

const STATUS_TONE: Record<ChainStatus, { bg: string; fg: string }> = {
  draft: { bg: "#eef2f6", fg: "#344054" },
  active: { bg: "#dcfce7", fg: "#166534" },
  paused: { bg: "#fef9c3", fg: "#854d0e" },
  archived: { bg: "#f2f4f7", fg: "#98a2b3" },
};

type ActionKind = "activate" | "pause" | "archive";

export function ChainsList() {
  const t = useT();
  const me = useRole();
  const canWrite = WRITE_ROLES.includes(me.role);

  const listQ = useFlaskData<{ chains: ChainListItem[] }>("/api/v1/chains");
  const chains = useMemo(() => listQ.data?.chains ?? [], [listQ.data]);

  const [tab, setTab] = useState<"chains" | "templates">("chains");
  const [selectedChainId, setSelectedChainId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [confirm, setConfirm] = useState<{ kind: ActionKind; chain: ChainListItem } | null>(null);
  const [clone, setClone] = useState<{ chain: ChainListItem; name: string } | null>(null);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return chains;
    return chains.filter((c) => c.name.toLowerCase().includes(q));
  }, [chains, search]);

  // ── editor view ──
  if (selectedChainId) {
    return (
      <ChainEditor
        chainId={selectedChainId}
        canWrite={canWrite}
        onClose={() => {
          setSelectedChainId(null);
          listQ.reload();
        }}
      />
    );
  }

  // ── list helpers ──
  function canActivate(c: ChainListItem): boolean {
    return c.has_draft || c.status === "paused";
  }
  function activateVersion(c: ChainListItem): number | null {
    return c.has_draft ? c.versions_count : c.active_version_no;
  }

  async function createChain() {
    if (createName.trim() === "") return;
    setBusy(true);
    setActionError(null);
    try {
      const chain = await flaskFetch<Chain>("/api/v1/chains", {
        method: "POST",
        body: { name: createName.trim(), description: createDesc },
      });
      setCreateOpen(false);
      setCreateName("");
      setCreateDesc("");
      setSelectedChainId(chain.chain_id);
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "automation.chains.error.desc"));
    } finally {
      setBusy(false);
    }
  }

  async function runAction(kind: ActionKind, chain: ChainListItem) {
    setConfirm(null);
    setBusy(true);
    setActionError(null);
    try {
      await flaskFetch(`/api/v1/chains/${chain.chain_id}/${kind}`, { method: "POST", body: {} });
      listQ.reload();
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "automation.chains.error.desc"));
    } finally {
      setBusy(false);
    }
  }

  async function runClone() {
    if (!clone || clone.name.trim() === "") return;
    const src = clone;
    setClone(null);
    setBusy(true);
    setActionError(null);
    try {
      const created = await flaskFetch<Chain>(`/api/v1/chains/${src.chain.chain_id}/clone`, {
        method: "POST",
        body: { name: src.name.trim() },
      });
      setSelectedChainId(created.chain_id);
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "automation.chains.error.desc"));
      listQ.reload();
    } finally {
      setBusy(false);
    }
  }

  const loading = listQ.state === "loading";
  const tableState: TableState = loading ? "loading" : filtered.length === 0 ? "empty" : "data";

  const columns: Column<ChainListItem>[] = [
    {
      key: "name",
      header: t("automation.chains.list.col.name"),
      align: "left",
      render: (c) => (
        <button
          type="button"
          onClick={() => setSelectedChainId(c.chain_id)}
          className="text-primary font-medium hover:underline text-left cursor-pointer"
        >
          {c.name}
        </button>
      ),
    },
    {
      key: "status",
      header: t("automation.chains.list.col.status"),
      align: "left",
      render: (c) => {
        const tone = STATUS_TONE[c.status];
        return (
          <Badge bg={tone.bg} fg={tone.fg}>
            {t(`automation.chains.status.${c.status}` as MessageKey)}
          </Badge>
        );
      },
    },
    {
      key: "version",
      header: t("automation.chains.list.col.version"),
      align: "left",
      render: (c) => (
        <div className="flex items-center gap-1.5">
          <Pill>{c.active_version_no != null ? `v${c.active_version_no}` : "—"}</Pill>
          {c.has_draft ? (
            <Badge bg="#fef9c3" fg="#854d0e">
              {t("automation.chains.list.badge.draft")}
            </Badge>
          ) : null}
        </div>
      ),
    },
    {
      key: "enrollments",
      header: t("automation.chains.list.col.enrollments"),
      mono: true,
      render: (c) => formatInt(c.active_enrollments),
    },
    {
      key: "updated",
      header: t("automation.chains.list.col.updated"),
      align: "left",
      render: (c) => <span className="text-steel">{formatDateTime(c.updated_at)}</span>,
    },
    {
      key: "actions",
      header: t("automation.chains.list.col.actions"),
      align: "left",
      render: (c) =>
        canWrite ? (
          <div className="flex flex-wrap gap-1.5">
            {canActivate(c) ? (
              <Button variant="ghost" size="sm" onClick={() => setConfirm({ kind: "activate", chain: c })} disabled={busy}>
                {t("automation.chains.list.action.activate")}
              </Button>
            ) : null}
            {c.status === "active" ? (
              <Button variant="ghost" size="sm" onClick={() => setConfirm({ kind: "pause", chain: c })} disabled={busy}>
                {t("automation.chains.list.action.pause")}
              </Button>
            ) : null}
            {c.versions_count > 0 ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setClone({ chain: c, name: `${c.name} (копия)` })}
                disabled={busy}
              >
                {t("automation.chains.list.action.clone")}
              </Button>
            ) : null}
            {c.status !== "archived" ? (
              <Button
                variant="ghost"
                size="sm"
                className="!text-neg hover:!border-neg"
                onClick={() => setConfirm({ kind: "archive", chain: c })}
                disabled={busy}
              >
                {t("automation.chains.list.action.archive")}
              </Button>
            ) : null}
          </div>
        ) : (
          <span className="text-stone">—</span>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("automation.chains.title")}
        accent={listQ.data ? `· ${formatInt(chains.length)}` : undefined}
        lead={t("automation.chains.lead")}
        right={
          canWrite ? (
            <Button variant="brand" onClick={() => setCreateOpen(true)}>
              {t("automation.chains.btn.create")}
            </Button>
          ) : (
            <Pill>{t("automation.chains.readOnlyPill")}</Pill>
          )
        }
      />

      {actionError ? (
        <div className="mt-4 rounded-card border border-neg/40 bg-neg/5 px-4 py-3 text-[13px] text-neg">
          {actionError}
        </div>
      ) : null}

      <div className="mt-4">
        <Tabs
          value={tab}
          onChange={(k) => setTab(k as "chains" | "templates")}
          tabs={[
            { key: "chains", label: t("automation.chains.tab.chains") },
            { key: "templates", label: t("automation.chains.tab.templates") },
          ]}
        />
      </div>

      {tab === "templates" ? (
        <div className="mt-5">
          <TemplatesPanel canWrite={canWrite} />
        </div>
      ) : listQ.state === "error" ? (
        <div className="mt-6">
          <ErrorState
            title={t("automation.chains.error.title")}
            description={listQ.error ?? t("automation.chains.error.desc")}
            onRetry={listQ.reload}
          />
        </div>
      ) : (
        <>
          <ChipBar className="mt-4">
            <div className="w-full max-w-sm">
              <Input
                value={search}
                placeholder={t("automation.chains.list.search")}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </ChipBar>

          <div className="mt-2 overflow-hidden rounded-card border border-hair bg-canvas">
            <DataTable
              columns={columns}
              rows={filtered}
              getRowKey={(c) => c.chain_id}
              state={tableState}
              emptyTitle={t("automation.chains.empty.title")}
              emptyDescription={t("automation.chains.empty.desc")}
            />
          </div>
        </>
      )}

      {/* ── create ── */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t("automation.chains.create.title")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              {t("automation.chains.editor.cancel")}
            </Button>
            <Button variant="brand" onClick={createChain} loading={busy} disabled={createName.trim() === ""}>
              {t("automation.chains.create.confirm")}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <FormField label={t("automation.chains.create.nameLabel")} required>
            <Input
              value={createName}
              placeholder={t("automation.chains.create.namePlaceholder")}
              onChange={(e) => setCreateName(e.target.value)}
              autoFocus
            />
          </FormField>
          <FormField label={t("automation.chains.create.descLabel")}>
            <Textarea
              value={createDesc}
              placeholder={t("automation.chains.create.descPlaceholder")}
              onChange={(e) => setCreateDesc(e.target.value)}
            />
          </FormField>
        </div>
      </Modal>

      {/* ── activate / pause / archive confirm ── */}
      <Modal
        open={confirm != null}
        onClose={() => setConfirm(null)}
        title={confirm ? t(`automation.chains.confirm.${confirm.kind}.title` as MessageKey) : ""}
        footer={
          confirm ? (
            <>
              <Button variant="ghost" onClick={() => setConfirm(null)}>
                {t("automation.chains.editor.cancel")}
              </Button>
              <Button
                variant={confirm.kind === "archive" ? "primary" : "brand"}
                onClick={() => runAction(confirm.kind, confirm.chain)}
              >
                {t(`automation.chains.confirm.${confirm.kind}.confirm` as MessageKey)}
              </Button>
            </>
          ) : null
        }
      >
        {confirm ? <ConfirmBody kind={confirm.kind} chain={confirm.chain} activateVersion={activateVersion} /> : null}
      </Modal>

      {/* ── clone ── */}
      <Modal
        open={clone != null}
        onClose={() => setClone(null)}
        title={t("automation.chains.clone.title")}
        footer={
          clone ? (
            <>
              <Button variant="ghost" onClick={() => setClone(null)}>
                {t("automation.chains.editor.cancel")}
              </Button>
              <Button variant="brand" onClick={runClone} disabled={clone.name.trim() === ""}>
                {t("automation.chains.clone.confirm")}
              </Button>
            </>
          ) : null
        }
      >
        {clone ? (
          <FormField label={t("automation.chains.clone.nameLabel")}>
            <Input value={clone.name} onChange={(e) => setClone({ ...clone, name: e.target.value })} autoFocus />
          </FormField>
        ) : null}
      </Modal>
    </>
  );
}

function ConfirmBody({
  kind,
  chain,
  activateVersion,
}: {
  kind: ActionKind;
  chain: ChainListItem;
  activateVersion: (c: ChainListItem) => number | null;
}) {
  const t = useT();
  if (kind === "activate") {
    const n = activateVersion(chain);
    if (chain.has_draft) {
      return <>{t("automation.chains.confirm.activate.bodyDraft", { name: chain.name, n: String(n ?? "?") })}</>;
    }
    return <>{t("automation.chains.confirm.activate.bodyResume", { name: chain.name, n: String(n ?? "?") })}</>;
  }
  if (kind === "pause") {
    return <>{t("automation.chains.confirm.pause.body", { name: chain.name })}</>;
  }
  return <>{t("automation.chains.confirm.archive.body", { name: chain.name })}</>;
}
