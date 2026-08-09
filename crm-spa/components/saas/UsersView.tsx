"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
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
  online: boolean;
}

interface UsersData {
  stages: Record<string, number>;
  users: SaasUser[];
  online_count?: number;
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
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [seen, setSeen] = useState<string>("");        // 1d | 7d | 30d | ""
  const [pay, setPay] = useState<string>("");          // paying | trial | free | ""
  const [query, setQuery] = useState<string>("");
  const [debouncedQuery, setDebouncedQuery] = useState<string>("");
  const [state, setState] = useState<TableState>("loading");
  const [noTenant, setNoTenant] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedQuery(query.trim()), 350);
    return () => clearTimeout(id);
  }, [query]);

  const load = useCallback((s: string, online: boolean, sn: string, p: string, q2: string) => {
    setState("loading");
    const params = new URLSearchParams();
    if (s) params.set("stage", s);
    if (online) params.set("online", "1");
    if (sn) params.set("seen", sn);
    if (p) params.set("status", p);
    if (q2) params.set("q", q2);
    const qs = params.toString();
    flaskFetch<UsersData>("/api/v1/saas/users" + (qs ? `?${qs}` : ""))
      .then((d) => {
        setData(d);
        setState(d.users.length ? "data" : "empty");
      })
      .catch((e: unknown) => {
        setNoTenant(isNoTenant(e));
        setState("error");
      });
  }, []);

  useEffect(() => load(stage, onlineOnly, seen, pay, debouncedQuery),
            [load, stage, onlineOnly, seen, pay, debouncedQuery]);

  const columns: Column<SaasUser>[] = [
    {
      key: "email", header: t("saas.users.col.user"),
      render: (r) => (
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 font-medium text-ink">
            {r.online ? (
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-pos" title={t("saas.ucard.online")} />
            ) : null}
            <span className="truncate">{r.email || r.client_user_id || r.identity_id.slice(0, 8)}</span>
          </div>
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
          {r.stage_note === "post_cancel_cooldown"
            ? t("saas.users.stage.justCanceled")
            : t(`saas.stage.${r.stage}` as MessageKey)}
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

      <div className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("saas.users.searchPh")}
            className="w-[240px] rounded-full border border-hair2 bg-canvas px-4 py-1.5 text-[12.5px] text-ink outline-none transition-colors placeholder:text-steel focus:border-primary"
          />
          <button
            onClick={() => setOnlineOnly(!onlineOnly)}
            className={"inline-flex items-center gap-1.5 border rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors " +
              (onlineOnly ? "bg-pos text-white border-pos" : "bg-canvas text-slate border-hair2 hover:border-pos")}
          >
            <span className={"h-1.5 w-1.5 rounded-full " + (onlineOnly ? "bg-white" : "bg-pos")} />
            {t("saas.users.onlineNow")}{data?.online_count ? ` · ${data.online_count}` : ""}
          </button>
          <select
            value={seen}
            onChange={(e) => setSeen(e.target.value)}
            className="rounded-full border border-hair2 bg-canvas px-3 py-1.5 text-[12.5px] font-semibold text-slate outline-none transition-colors focus:border-primary"
          >
            <option value="">{t("saas.users.seen.any")}</option>
            <option value="1d">{t("saas.users.seen.1d")}</option>
            <option value="7d">{t("saas.users.seen.7d")}</option>
            <option value="30d">{t("saas.users.seen.30d")}</option>
          </select>
          <select
            value={pay}
            onChange={(e) => setPay(e.target.value)}
            className="rounded-full border border-hair2 bg-canvas px-3 py-1.5 text-[12.5px] font-semibold text-slate outline-none transition-colors focus:border-primary"
          >
            <option value="">{t("saas.users.pay.any")}</option>
            <option value="paying">{t("saas.users.pay.paying")}</option>
            <option value="trial">{t("saas.users.pay.trial")}</option>
            <option value="free">{t("saas.users.pay.free")}</option>
          </select>
          {(stage || onlineOnly || seen || pay || query) ? (
            <button
              onClick={() => { setStage(""); setOnlineOnly(false); setSeen(""); setPay(""); setQuery(""); }}
              className="text-[12px] font-medium text-steel transition-colors hover:text-primary"
            >
              {t("saas.users.clearFilters")}
            </button>
          ) : null}
        </div>
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
              {t(`saas.stage.${s}` as MessageKey)} {data?.stages[s] ? `· ${data.stages[s]}` : "· 0"}
            </button>
          ))}
        </div>
      </div>

      {noTenant ? (
        <NoTenant />
      ) : (
      <DataTable
        columns={columns}
        rows={data?.users ?? []}
        getRowKey={(r) => r.identity_id}
        getRowHref={(r) => `/users/${encodeURIComponent(r.identity_id)}`}
        state={state}
        onRetry={() => load(stage, onlineOnly, seen, pay, debouncedQuery)}
        emptyTitle={t("saas.users.empty.title")}
        emptyDescription={t("saas.users.empty.desc")}
      />
      )}
    </div>
  );
}
