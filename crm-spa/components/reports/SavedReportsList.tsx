"use client";

import { useState } from "react";
import {
  DataTable,
  Badge,
  Button,
  Modal,
  type Column,
  type TableState,
} from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { useRole } from "@/lib/role-context";
import { useFlaskData } from "@/components/marketing/useFlaskData";
import type { SavedReport } from "./types";

/**
 * SavedReportsList — сохранённые отчёты (GET /api/v1/reports/saved). Backend уже
 * сортирует официальные вверх и режет видимость по ролям (личные + общие + по
 * ролям) — здесь только отрисовка + действия. «Открыть» подставляет spec в билдер
 * (колбэк родителя), «Дублировать»/«Удалить» бьют в API и перезагружают список.
 *
 * `reloadKey` в пути (?r=) заставляет useFlaskData перечитать список после
 * сохранения из билдера (backend query-параметр игнорирует).
 */
interface SavedReportsListProps {
  onOpen: (report: SavedReport) => void;
  reloadKey: number;
}

const VIS_KEY: Record<string, MessageKey> = {
  personal: "reports.saved.vis.personal",
  shared: "reports.saved.vis.shared",
  roles: "reports.saved.vis.roles",
};

export function SavedReportsList({ onOpen, reloadKey }: SavedReportsListProps) {
  const t = useT();
  const me = useRole();
  const listQ = useFlaskData<{ rows: SavedReport[] }>(`/api/v1/reports/saved?r=${reloadKey}`);
  const rows = listQ.data?.rows ?? [];

  const [toDelete, setToDelete] = useState<SavedReport | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canDelete = (r: SavedReport) => r.mine || me.role === "super_admin";

  async function duplicate(r: SavedReport) {
    setActionError(null);
    try {
      await flaskFetch(`/api/v1/reports/saved/${r.report_id}/duplicate`, { method: "POST" });
      listQ.reload();
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "reports.saved.duplicate.failed"));
    }
  }

  async function confirmDelete() {
    if (!toDelete) return;
    setBusy(true);
    setActionError(null);
    try {
      await flaskFetch(`/api/v1/reports/saved/${toDelete.report_id}`, { method: "DELETE" });
      setToDelete(null);
      listQ.reload();
    } catch (e: unknown) {
      setActionError(flaskErrorText(e, t, "reports.saved.delete.failed"));
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<SavedReport>[] = [
    {
      key: "name",
      header: t("reports.saved.col.name"),
      align: "left",
      render: (r) => (
        <span className="inline-flex items-center gap-2">
          {r.is_official ? (
            <Badge bg="#fef9c3" fg="#854d0e" title={t("reports.saved.official")}>
              ⭐ {t("reports.saved.official")}
            </Badge>
          ) : null}
          <button
            type="button"
            onClick={() => onOpen(r)}
            className="text-primary font-medium hover:underline text-left cursor-pointer"
          >
            {r.name}
          </button>
        </span>
      ),
    },
    {
      key: "visibility",
      header: t("reports.saved.col.visibility"),
      align: "left",
      render: (r) => (
        <Badge bg="#eef2f6" fg="#475569">
          {t(VIS_KEY[r.visibility] ?? "reports.saved.vis.personal")}
        </Badge>
      ),
    },
    {
      key: "owner",
      header: t("reports.saved.col.owner"),
      align: "left",
      render: (r) => (
        <span className="text-steel">
          {r.mine ? t("reports.saved.mine") : (r.owner_name ?? "—")}
        </span>
      ),
    },
    {
      key: "updated",
      header: t("reports.saved.col.updated"),
      align: "left",
      render: (r) => <span className="text-steel">{formatDate(r.updated_at)}</span>,
    },
    {
      key: "actions",
      header: t("reports.saved.col.actions"),
      align: "right",
      render: (r) => (
        <span className="inline-flex gap-1.5 justify-end">
          <Button variant="ghost" size="sm" onClick={() => onOpen(r)}>
            {t("reports.saved.open")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => duplicate(r)}>
            {t("reports.saved.duplicate")}
          </Button>
          {canDelete(r) ? (
            <Button variant="ghost" size="sm" onClick={() => setToDelete(r)}>
              {t("reports.saved.delete")}
            </Button>
          ) : null}
        </span>
      ),
    },
  ];

  const state: TableState =
    listQ.state === "loading" ? "loading" : listQ.state === "error" ? "error" : rows.length === 0 ? "empty" : "data";

  return (
    <>
      {actionError ? <p className="text-[12.5px] text-neg mb-2">{actionError}</p> : null}

      <div className="overflow-hidden rounded-card border border-hair bg-canvas">
        <DataTable
          columns={columns}
          rows={rows}
          getRowKey={(r) => r.report_id}
          state={state}
          emptyTitle={t("reports.saved.empty.title")}
          emptyDescription={t("reports.saved.empty.desc")}
          errorTitle={t("reports.saved.error.title")}
          errorDescription={listQ.error ?? t("reports.saved.error.desc")}
          onRetry={listQ.reload}
        />
      </div>

      <Modal
        open={Boolean(toDelete)}
        onClose={() => setToDelete(null)}
        title={t("reports.saved.delete.title")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setToDelete(null)} disabled={busy}>
              {t("ui.cancel")}
            </Button>
            <Button variant="brand" onClick={confirmDelete} loading={busy}>
              {t("reports.saved.delete")}
            </Button>
          </>
        }
      >
        <p className="text-[13.5px] text-slate">
          {t("reports.saved.delete.confirm", { name: toDelete?.name ?? "" })}
        </p>
      </Modal>
    </>
  );
}
