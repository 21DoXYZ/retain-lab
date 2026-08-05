"use client";

import { useState, useSyncExternalStore } from "react";
import {
  PageHeader,
  Button,
  Chip,
  ChipBar,
  DataTable,
  Badge,
  Pill,
  PillRow,
  Modal,
  Card,
  ErrorState,
  type Column,
  type TableState,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { useRole } from "@/lib/role-context";
import type { UserRole } from "@/lib/types";
import { useFlaskData } from "@/components/marketing/useFlaskData";
import { SegmentEditor, type EditorSeed } from "./SegmentEditor";
import { type FieldsCatalog, type Segment, type SegmentPreset, deserialize } from "./catalog";

/**
 * /segments — segment builder home (W4-T2). Lists the saved definitions and
 * routes into the editor for create / edit / clone-from-preset. Everything the
 * editor needs about fields comes from the backend catalog (/segments/fields),
 * so the screen stays generic as the registry grows. Write roles mirror
 * WRITE_ROLES in api/segments.py; read-only roles see the list + editor without
 * the create / save / archive controls.
 */

const WRITE_ROLES: readonly UserRole[] = ["marketing_manager", "head_retention", "super_admin"];

// «now» as an external store: ticks each minute, snapshot cached → no Date.now()
// in render (react-hooks/purity), same pattern as FlagsScreen. Powers "N h ago".
let _nowMs = Date.now();
function subscribeMinute(cb: () => void): () => void {
  const id = setInterval(() => {
    _nowMs = Date.now();
    cb();
  }, 60000);
  return () => clearInterval(id);
}
const useNowMs = () => useSyncExternalStore(subscribeMinute, () => _nowMs, () => _nowMs);

export function SegmentsList() {
  const t = useT();
  const me = useRole();
  const canWrite = WRITE_ROLES.includes(me.role);
  const nowMs = useNowMs();

  const [showArchived, setShowArchived] = useState(false);
  const [showPresets, setShowPresets] = useState(false);
  const [seed, setSeed] = useState<EditorSeed | null>(null);
  const [seedNonce, setSeedNonce] = useState(0);

  const catalogQ = useFlaskData<FieldsCatalog>("/api/v1/segments/fields");
  const listQ = useFlaskData<{ segments: Segment[] }>(
    showArchived ? "/api/v1/segments?archived=1" : "/api/v1/segments",
  );
  const presetsQ = useFlaskData<{ presets: SegmentPreset[] }>("/api/v1/segments/presets");

  const catalog = catalogQ.data;
  const segments = listQ.data?.segments ?? [];

  function openEditor(next: EditorSeed) {
    setSeed(next);
    setSeedNonce((n) => n + 1);
  }
  function openCreate() {
    openEditor({
      mode: "create",
      name: "",
      sysName: "",
      description: "",
      isTrigger: false,
      scheduleAt: "10:00",
      definition: { all: [] },
      model: { rows: [] },
    });
  }
  function openEdit(seg: Segment) {
    if (!catalog) return;
    openEditor({
      mode: "edit",
      segmentId: seg.segment_id,
      name: seg.name,
      sysName: seg.sys_name,
      description: seg.description,
      isTrigger: seg.is_trigger,
      scheduleAt: (seg.schedule_at ?? "10:00").slice(0, 5),
      definition: seg.definition,
      model: deserialize(seg.definition, catalog),
    });
  }
  function openPreset(preset: SegmentPreset) {
    if (!catalog) return;
    setShowPresets(false);
    openEditor({
      mode: "clone",
      name: preset.name,
      sysName: "",
      description: preset.description,
      isTrigger: false,
      scheduleAt: "10:00",
      definition: preset.definition,
      model: deserialize(preset.definition, catalog),
    });
  }

  // ── editor view ──
  if (seed && catalog) {
    return (
      <SegmentEditor
        key={seedNonce}
        catalog={catalog}
        segments={segments}
        seed={seed}
        canWrite={canWrite}
        onClose={() => setSeed(null)}
        onSaved={() => {
          setSeed(null);
          listQ.reload();
        }}
        onClone={openEditor}
      />
    );
  }

  // ── list view ──
  const errored = catalogQ.state === "error" || listQ.state === "error";
  const loading = catalogQ.state === "loading" || listQ.state === "loading";
  const tableState: TableState = loading ? "loading" : segments.length === 0 ? "empty" : "data";

  function recomputedText(seg: Segment): string {
    if (!seg.computed_at) return t("automation.list.recomputed.never");
    const diff = nowMs - new Date(seg.computed_at).getTime();
    const hours = Math.floor(diff / 3_600_000);
    if (hours < 1) return t("automation.list.recomputed.now");
    if (hours < 24) return t("automation.list.recomputed.hours", { n: String(hours) });
    return t("automation.list.recomputed.days", { n: String(Math.floor(hours / 24)) });
  }

  const columns: Column<Segment>[] = [
    {
      key: "name",
      header: t("automation.list.col.name"),
      align: "left",
      render: (s) => (
        <button
          type="button"
          onClick={() => openEdit(s)}
          className="text-primary font-medium hover:underline text-left cursor-pointer"
        >
          {s.name}
        </button>
      ),
    },
    {
      key: "sys",
      header: t("automation.list.col.sysName"),
      align: "left",
      mono: true,
      render: (s) => <span className="text-steel">{s.sys_name}</span>,
    },
    {
      key: "count",
      header: t("automation.list.col.count"),
      mono: true,
      render: (s) => (s.member_count == null ? <span className="text-stone">—</span> : formatInt(s.member_count)),
    },
    {
      key: "recomputed",
      header: t("automation.list.col.recomputed"),
      align: "left",
      render: (s) => <span className="text-steel">{recomputedText(s)}</span>,
    },
    {
      key: "author",
      header: t("automation.list.col.author"),
      align: "left",
      render: (s) => (
        <span className="text-steel">{s.created_by_name ?? t("automation.list.author.system")}</span>
      ),
    },
    {
      key: "type",
      header: t("automation.list.col.type"),
      align: "left",
      render: (s) =>
        s.is_trigger ? (
          <Badge bg="#dde9ff" fg="#1e40af">
            {t("automation.list.badge.trigger")}
          </Badge>
        ) : (
          <Badge bg="#eef2f6" fg="#344054">
            {t("automation.list.badge.scheduled")}
          </Badge>
        ),
    },
    {
      key: "status",
      header: t("automation.list.col.status"),
      align: "left",
      render: (s) =>
        s.archived_at ? (
          <Badge bg="#f2f4f7" fg="#98a2b3">
            {t("automation.list.badge.archived")}
          </Badge>
        ) : (
          <Badge tone="pos">{t("automation.list.badge.active")}</Badge>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("automation.title")}
        accent={listQ.data ? `· ${formatInt(segments.length)}` : undefined}
        lead={t("automation.lead")}
        right={
          canWrite ? (
            <PillRow>
              <Button variant="ghost" onClick={() => setShowPresets(true)} disabled={!catalog}>
                {t("automation.btn.fromTemplate")}
              </Button>
              <Button variant="brand" onClick={openCreate} disabled={!catalog}>
                {t("automation.btn.create")}
              </Button>
            </PillRow>
          ) : (
            <Pill>{t("automation.readOnlyPill")}</Pill>
          )
        }
      />

      {errored ? (
        <div className="mt-6">
          <ErrorState
            title={t("automation.error.title")}
            description={catalogQ.error ?? listQ.error ?? t("automation.error.desc")}
            onRetry={() => {
              catalogQ.reload();
              listQ.reload();
            }}
          />
        </div>
      ) : (
        <>
          <ChipBar>
            <Chip active={showArchived} onClick={() => setShowArchived((v) => !v)}>
              {t("automation.list.showArchived")}
            </Chip>
          </ChipBar>

          <div className="mt-2 overflow-hidden rounded-card border border-hair bg-canvas">
            <DataTable
              columns={columns}
              rows={segments}
              getRowKey={(s) => s.segment_id}
              state={tableState}
              emptyTitle={t("automation.empty.title")}
              emptyDescription={t("automation.empty.desc")}
            />
          </div>
        </>
      )}

      <Modal
        open={showPresets}
        onClose={() => setShowPresets(false)}
        title={t("automation.presets.title")}
        widthClass="max-w-2xl"
      >
        <p className="text-[13px] text-steel mb-4">{t("automation.presets.desc")}</p>
        {presetsQ.state === "error" ? (
          <p className="text-[13px] text-neg">{t("automation.presets.empty")}</p>
        ) : (
          <div className="flex flex-col gap-2.5">
            {(presetsQ.data?.presets ?? []).map((p) => (
              <Card key={p.key} className="!py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-base">{p.icon}</span>
                      <span className="font-semibold text-ink text-[14px]">{p.name}</span>
                      <Badge bg="#eef2f6" fg="#344054">
                        {t(`automation.presets.kind.${p.kind}` as MessageKey)}
                      </Badge>
                    </div>
                    <div className="text-[12.5px] text-steel mt-1">{p.description}</div>
                    {p.offer ? (
                      <div className="text-[12px] text-stone mt-1">
                        {t("automation.presets.offer", { offer: p.offer })}
                      </div>
                    ) : null}
                    {p.note ? <div className="text-[12px] text-stone mt-1 italic">{p.note}</div> : null}
                  </div>
                  {canWrite ? (
                    <Button variant="ghost" size="sm" onClick={() => openPreset(p)} disabled={!catalog}>
                      {t("automation.presets.clone")}
                    </Button>
                  ) : null}
                </div>
              </Card>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}
