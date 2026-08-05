"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { DataTable, PageHeader, type Column, type TableState } from "@/components/ui";

/**
 * /channel-settings — статус каналов: провайдеры платформы (ключ настроен?)
 * + покрытие контактами/согласиями. GET /api/v1/saas/channels.
 */

interface ChannelRow {
  channel: string;
  provider: string;
  configured: boolean;
  detail: string;
  contacts: number;
  consented: number;
}

const CHANNEL_EMOJI: Record<string, string> = {
  email: "✉️", sms: "💬", viber: "💜", whatsapp: "🟢", telegram: "✈️",
};

export function ChannelsView() {
  const t = useT();
  const [rows, setRows] = useState<ChannelRow[]>([]);
  const [state, setState] = useState<TableState>("loading");

  const load = useCallback(() => {
    setState("loading");
    flaskFetch<{ providers: ChannelRow[] }>("/api/v1/saas/channels")
      .then((d) => {
        setRows(d.providers);
        setState("data");
      })
      .catch(() => setState("error"));
  }, []);

  useEffect(load, [load]);

  const columns: Column<ChannelRow>[] = [
    {
      key: "channel", header: t("saas.channels.col.channel"),
      render: (r) => (
        <span className="font-medium text-ink">
          {CHANNEL_EMOJI[r.channel] ?? "📡"} {r.channel}
        </span>
      ),
    },
    { key: "provider", header: t("saas.channels.col.provider"), render: (r) => r.provider },
    {
      key: "configured", header: t("saas.channels.col.status"),
      render: (r) => (
        <span className={"inline-block border rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold " +
          (r.configured ? "bg-[#ecfdf3] text-pos border-[#abefc6]" : "bg-surface text-steel border-hair2")}>
          {r.configured ? t("saas.channels.on") : t("saas.channels.off")}
        </span>
      ),
      sortValue: (r) => (r.configured ? 1 : 0),
    },
    { key: "detail", header: t("saas.channels.col.detail"), mono: true, render: (r) => r.detail || "-" },
    { key: "contacts", header: t("saas.channels.col.contacts"), align: "right", mono: true,
      render: (r) => String(r.contacts) },
    { key: "consented", header: t("saas.channels.col.consented"), align: "right", mono: true,
      render: (r) => String(r.consented) },
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.channels.title")} lead={t("saas.channels.lead")} />
      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(r) => r.channel}
        state={state}
        onRetry={load}
        sortable={false}
      />
    </div>
  );
}
