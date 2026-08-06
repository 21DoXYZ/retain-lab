"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Banner, DataTable, PageHeader, type Column, type TableState } from "@/components/ui";
import { NoTenant, isNoTenant } from "./NoTenant";

/**
 * /users — юзеры SaaS-контура (замена казино-экрана /players): стадия,
 * действие, ценность на кону, скоры. GET /api/v1/saas/users?stage=.
 */

interface SaasUser {
  identity_id: string;
  email: string;
  client_user_id: string;
  sub_status: string;
  plan_id: string;
  mrr: number;
  stage: string;
  action: string;
  value_at_stake: number;
  p_churn: number;
  ltv: number;
  last_seen: string;
  stage_note: string;
}

interface UsersData {
  stages: Record<string, number>;
  users: SaasUser[];
  demo?: boolean;
}

const STAGE_ORDER = ["DUNNING", "SAVE", "CONVERT", "UPGRADE", "ACTIVATE", "WINBACK", "MONITOR"];

const STAGE_TONE: Record<string, string> = {
  DUNNING: "bg-[#fef3f2] text-neg border-[#fecdca]",
  SAVE: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  CONVERT: "bg-cream text-primary border-beige",
  UPGRADE: "bg-[#ecfdf3] text-pos border-[#abefc6]",
  ACTIVATE: "bg-surface text-slate border-hair2",
  WINBACK: "bg-surface text-slate border-hair2",
  MONITOR: "bg-surface text-steel border-hair2",
};

function usd(n: number): string {
  return "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function UsersView() {
  const t = useT();
  const [data, setData] = useState<UsersData | null>(null);
  const [stage, setStage] = useState<string>("");
  const [state, setState] = useState<TableState>("loading");
  const [noTenant, setNoTenant] = useState(false);

  const load = useCallback((s: string) => {
    setState("loading");
    flaskFetch<UsersData>("/api/v1/saas/users" + (s ? `?stage=${s}` : ""))
      .then((d) => {
        setData(d);
        setState(d.users.length ? "data" : "empty");
      })
      .catch((e: unknown) => {
        setNoTenant(isNoTenant(e));
        setState("error");
      });
  }, []);

  useEffect(() => load(stage), [load, stage]);

  const columns: Column<SaasUser>[] = [
    {
      key: "email", header: t("saas.users.col.user"),
      render: (r) => (
        <div className="min-w-0">
          <div className="font-medium text-ink truncate">{r.email || r.client_user_id || r.identity_id.slice(0, 8)}</div>
          {r.client_user_id ? <div className="text-[11px] text-steel">{r.client_user_id}</div> : null}
        </div>
      ),
    },
    { key: "plan_id", header: t("saas.users.col.plan"), render: (r) => r.plan_id || "-" },
    { key: "mrr", header: t("saas.users.col.mrr"), align: "right", mono: true, render: (r) => usd(r.mrr) },
    {
      key: "stage", header: t("saas.users.col.stage"),
      render: (r) => (
        <span className={"inline-block border rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold " + (STAGE_TONE[r.stage] ?? STAGE_TONE.MONITOR)}
              title={r.stage_note ? t("saas.users.note.post_cancel_cooldown") : undefined}>
          {/* Только что отменил - это НЕ «всё хорошо»: показываем пометку,
              иначе ушедший клиент выглядит как спокойный. */}
          {r.stage_note === "post_cancel_cooldown" ? t("saas.users.stage.justCanceled") : r.stage}
        </span>
      ),
    },
    { key: "action", header: t("saas.users.col.action"), mono: true, render: (r) => r.action },
    {
      key: "value_at_stake", header: t("saas.users.col.atStake"), align: "right", mono: true,
      render: (r) => (r.value_at_stake > 0 ? <span className="text-neg">{usd(r.value_at_stake)}</span> : "-"),
    },
    {
      key: "p_churn", header: t("saas.users.col.churn"), align: "right", mono: true,
      render: (r) => (r.p_churn > 0 ? (r.p_churn * 100).toFixed(0) + "%" : "-"),
    },
    { key: "ltv", header: t("saas.users.col.ltv"), align: "right", mono: true, render: (r) => usd(r.ltv) },
    {
      key: "last_seen", header: t("saas.users.col.lastSeen"), mono: true,
      render: (r) => (r.last_seen ? (
        <span title={r.last_seen + " UTC"}>{r.last_seen.slice(0, 10)}</span>
      ) : "-"),
    },
  ];

  const total = data ? Object.values(data.stages).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.users.title")} lead={t("saas.users.lead")} />

      {data?.demo ? <Banner className="mt-0">{t("saas.users.demoBanner")}</Banner> : null}

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setStage("")}
          className={"border rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors " +
            (stage === "" ? "bg-primary text-white border-primary" : "bg-canvas text-slate border-hair2 hover:border-primary")}
        >
          {t("saas.users.all")} {total ? `· ${total}` : ""}
        </button>
        {STAGE_ORDER.map((s) => (
          <button
            key={s}
            onClick={() => setStage(s)}
            className={"border rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors " +
              (stage === s ? "bg-primary text-white border-primary" : "bg-canvas text-slate border-hair2 hover:border-primary")}
          >
            {s} {data?.stages[s] ? `· ${data.stages[s]}` : "· 0"}
          </button>
        ))}
      </div>

      {noTenant ? (
        <NoTenant />
      ) : (
      <DataTable
        columns={columns}
        rows={data?.users ?? []}
        getRowKey={(r) => r.identity_id}
        state={state}
        onRetry={() => load(stage)}
        emptyTitle={t("saas.users.empty.title")}
        emptyDescription={t("saas.users.empty.desc")}
      />
      )}
    </div>
  );
}
