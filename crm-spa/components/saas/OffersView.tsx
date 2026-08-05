"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Button, Card, DataTable, PageHeader, type Column, type TableState } from "@/components/ui";

/**
 * /offers — каталог офферов тенанта + статистика выдач. Щедрость и лимиты
 * редактируются здесь (overrides поверх базового каталога, без деплоя):
 * GET /api/v1/saas/offers, POST /api/v1/saas/offers/update.
 */

interface OfferRow {
  offer_id: string;
  title: string;
  executor: string;
  monetary: boolean;
  cost_estimate: number;
  max_per_user_30d: number;
  params: Record<string, unknown>;
  edited: boolean;
  stats: { issued: number; dry_run: number; holdout: number; rejected: number };
}

interface OffersData {
  control_pct: number;
  offers: OfferRow[];
}

const inputCls =
  "h-[38px] w-full rounded-ctl border border-hair2 bg-canvas px-3 text-[13px] " +
  "text-ink outline-none transition-[border-color] duration-150 focus:border-primary";

function OfferEditor({
  offer,
  onDone,
}: {
  offer: OfferRow;
  onDone: (reload: boolean) => void;
}) {
  const t = useT();
  const numericParams = Object.entries(offer.params).filter(
    ([, v]) => typeof v === "number",
  ) as [string, number][];

  const [title, setTitle] = useState(offer.title);
  const [cap, setCap] = useState(String(offer.max_per_user_30d));
  const [params, setParams] = useState<Record<string, string>>(
    Object.fromEntries(numericParams.map(([k, v]) => [k, String(v)])),
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const post = (body: Record<string, unknown>) => {
    setBusy(true);
    setErr("");
    flaskFetch("/api/v1/saas/offers/update", {
      method: "POST",
      body: { offer_id: offer.offer_id, ...body },
    })
      .then(() => onDone(true))
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : t("saas.channels.err.generic")))
      .finally(() => setBusy(false));
  };

  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-[15px] font-semibold text-ink">
          {t("saas.offers.editTitle")}{" "}
          <span className="font-mono text-[12px] text-steel">{offer.offer_id}</span>
        </div>
        {offer.edited && (
          <span className="rounded-full border border-[#b2ddff] bg-[#eff8ff] px-2 py-0.5 text-[10.5px] font-semibold text-primary">
            {t("saas.camp.edited")}
          </span>
        )}
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-[12px] text-steel">
          {t("saas.offers.f.title")}
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-steel">
          {t("saas.offers.col.limit")}
          <input className={inputCls} value={cap} inputMode="numeric"
                 onChange={(e) => setCap(e.target.value)} />
        </label>
        {numericParams.map(([k]) => (
          <label key={k} className="flex flex-col gap-1 text-[12px] text-steel">
            <span className="font-mono">{k}</span>
            <input
              className={inputCls}
              value={params[k] ?? ""}
              inputMode="decimal"
              onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))}
            />
          </label>
        ))}
      </div>
      <p className="text-[11.5px] text-steel">{t("saas.offers.f.note")}</p>
      {err && <p className="text-[12px] text-neg">{err}</p>}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="brand" size="sm" loading={busy}
          onClick={() =>
            post({
              title,
              max_per_user_30d: Number(cap),
              params: Object.fromEntries(
                Object.entries(params).map(([k, v]) => [k, Number(v)]),
              ),
            })
          }
        >
          {t("saas.camp.save")}
        </Button>
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => onDone(false)}>
          {t("saas.camp.cancel")}
        </Button>
        {offer.edited && (
          <Button variant="ghost" size="sm" loading={busy} onClick={() => post({ reset: true })}>
            {t("saas.camp.resetDefault")}
          </Button>
        )}
      </div>
    </Card>
  );
}

export function OffersView() {
  const t = useT();
  const [data, setData] = useState<OffersData | null>(null);
  const [state, setState] = useState<TableState>("loading");
  const [editId, setEditId] = useState<string | null>(null);

  const load = useCallback(() => {
    setState("loading");
    flaskFetch<OffersData>("/api/v1/saas/offers")
      .then((d) => {
        setData(d);
        setState(d.offers.length ? "data" : "empty");
      })
      .catch(() => setState("error"));
  }, []);

  useEffect(load, [load]);

  const columns: Column<OfferRow>[] = [
    {
      key: "offer_id", header: t("saas.offers.col.offer"),
      render: (r) => (
        <div className="min-w-0">
          <div className="font-medium text-ink">
            {r.title}
            {r.edited && (
              <span className="ml-2 inline-block rounded-full border border-[#b2ddff] bg-[#eff8ff] px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                {t("saas.camp.edited")}
              </span>
            )}
          </div>
          <div className="text-[11px] text-steel font-mono">{r.offer_id}</div>
        </div>
      ),
    },
    { key: "executor", header: t("saas.offers.col.executor"), mono: true, render: (r) => r.executor },
    {
      key: "monetary", header: t("saas.offers.col.monetary"),
      render: (r) => (r.monetary ? t("saas.offers.yes") : t("saas.offers.no")),
      sortValue: (r) => (r.monetary ? 1 : 0),
    },
    {
      key: "cost_estimate", header: t("saas.offers.col.cost"), align: "right", mono: true,
      render: (r) => "$" + r.cost_estimate.toFixed(2),
    },
    { key: "max_per_user_30d", header: t("saas.offers.col.limit"), align: "right", mono: true,
      render: (r) => String(r.max_per_user_30d || "-") },
    {
      key: "issued", header: t("saas.offers.col.issued"), align: "right", mono: true,
      render: (r) => String(r.stats.issued + r.stats.dry_run),
      sortValue: (r) => r.stats.issued + r.stats.dry_run,
    },
    { key: "holdout", header: t("saas.offers.col.holdout"), align: "right", mono: true,
      render: (r) => String(r.stats.holdout), sortValue: (r) => r.stats.holdout },
    {
      key: "rejected", header: t("saas.offers.col.rejected"), align: "right", mono: true,
      render: (r) => (r.stats.rejected ? <span className="text-neg">{r.stats.rejected}</span> : "0"),
      sortValue: (r) => r.stats.rejected,
    },
    {
      key: "edit", header: "",
      render: (r) => (
        <button
          type="button"
          className="cursor-pointer rounded-md border border-hair2 px-2 py-0.5 text-[11.5px] text-steel transition-[color,border-color] duration-150 hover:border-primary hover:text-primary"
          onClick={() => setEditId(r.offer_id)}
        >
          {t("saas.camp.edit")}
        </button>
      ),
    },
  ];

  const editing = editId ? data?.offers.find((o) => o.offer_id === editId) : null;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("saas.offers.title")}
        lead={t("saas.offers.lead", { pct: data?.control_pct ?? 10 })}
      />
      {editing && (
        <OfferEditor
          key={editing.offer_id + (editing.edited ? ":e" : ":b")}
          offer={editing}
          onDone={(reload) => {
            setEditId(null);
            if (reload) load();
          }}
        />
      )}
      <DataTable
        columns={columns}
        rows={data?.offers ?? []}
        getRowKey={(r) => r.offer_id}
        state={state}
        onRetry={load}
      />
    </div>
  );
}
