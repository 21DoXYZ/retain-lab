"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Banner, Button, Card, PageHeader } from "@/components/ui";

/**
 * /admin/workspaces — создание рабочего пространства клиента (только платформа).
 * Одна форма: название продукта + почта владельца. Система сама делает id,
 * ingest-токен, логин владельца со скоупом своего тенанта и пустое пространство.
 * Пароль и токен показываются ОДИН раз - дальше только у клиента.
 */

interface TenantRow {
  tenant_id: string;
  product_name: string;
  has_token: boolean;
  onboarded: boolean;
}

interface Created {
  tenant_id: string;
  product_name: string;
  owner_email: string;
  owner_password: string;
  ingest_token: string;
  // Секрет Server Events API: только он проносит открытый email через ingest.
  server_events_token?: string;
  snippet: string;
  login_url: string;
}

const inputCls =
  "h-[38px] w-full rounded-ctl border border-hair2 bg-canvas px-3 text-[13px] " +
  "text-ink outline-none transition-[border-color] duration-150 focus:border-primary";

export function WorkspacesView() {
  const t = useT();
  const [rows, setRows] = useState<TenantRow[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [created, setCreated] = useState<Created | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    flaskFetch<{ tenants: TenantRow[] }>("/api/v1/saas/tenants")
      .then((d) => setRows(d.tenants))
      .catch(() => {});
  }, []);

  useEffect(load, [load]);

  const submit = () => {
    setBusy(true);
    setErr("");
    flaskFetch<Created>("/api/v1/saas/tenants", {
      method: "POST",
      body: { product_name: name.trim(), owner_email: email.trim() },
    })
      .then((d) => {
        setCreated(d);
        setName("");
        setEmail("");
        load();
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : "error"))
      .finally(() => setBusy(false));
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.ws.title")} lead={t("saas.ws.lead")} />

      {created && (
        <Card className="flex flex-col gap-3 border-l-[3px] border-l-pos p-5">
          <div className="text-[15px] font-semibold text-ink">
            {t("saas.ws.created", { name: created.product_name })}
          </div>
          <p className="text-[13px] text-neg">{t("saas.ws.oneTime")}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label={t("saas.ws.f.tenant")} value={created.tenant_id} />
            <Field label={t("saas.ws.f.login")} value={created.owner_email} />
            <Field label={t("saas.ws.f.password")} value={created.owner_password} />
            <Field label={t("saas.ws.f.token")} value={created.ingest_token} />
            {created.server_events_token ? (
              <Field
                label={t("saas.ws.f.serverToken")}
                value={created.server_events_token}
              />
            ) : null}
          </div>
          <pre className="overflow-x-auto rounded-ctl bg-sb p-3.5 font-mono text-[12px] leading-relaxed text-sb-text2 whitespace-pre">
            {created.snippet}
          </pre>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="brand"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(
                  `${t("saas.ws.f.login")}: ${created.owner_email}\n` +
                    `${t("saas.ws.f.password")}: ${created.owner_password}\n` +
                    `${t("saas.ws.f.token")}: ${created.ingest_token}\n` +
                    (created.server_events_token
                      ? `${t("saas.ws.f.serverToken")}: ${created.server_events_token}\n`
                      : "") +
                    `${created.login_url}\n\n${created.snippet}`,
                );
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? t("saas.channels.copied") : t("saas.ws.copyAll")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setCreated(null)}>
              {t("saas.ws.hide")}
            </Button>
          </div>
        </Card>
      )}

      <Card className="flex flex-col gap-3 p-5">
        <div className="text-[15px] font-semibold text-ink">{t("saas.ws.newTitle")}</div>
        <div className="grid gap-2.5 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-[12px] text-steel">
            {t("saas.q.product_name")}
            <input className={inputCls} placeholder="Acme Analytics" value={name}
                   onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-steel">
            {t("saas.ws.f.ownerEmail")}
            <input className={inputCls} placeholder="owner@acme.com" value={email}
                   onChange={(e) => setEmail(e.target.value)} />
          </label>
        </div>
        <p className="text-[12px] text-steel">{t("saas.ws.hint")}</p>
        {err && <p className="text-[12px] text-neg">{err}</p>}
        <div>
          <Button variant="brand" size="sm" loading={busy}
                  disabled={!name.trim() || !email.trim()} onClick={submit}>
            {t("saas.ws.create")}
          </Button>
        </div>
      </Card>

      <Card className="flex flex-col gap-2 p-5">
        <div className="text-[12px] font-semibold uppercase tracking-[0.5px] text-steel">
          {t("saas.ws.existing", { n: rows.length })}
        </div>
        {rows.length === 0 ? (
          <Banner>{t("saas.ws.none")}</Banner>
        ) : (
          <div className="flex flex-col">
            {rows.map((r) => (
              <div key={r.tenant_id} className="flex items-center justify-between gap-3 border-b border-hair py-2 text-[13px] last:border-0">
                <span className="min-w-0 truncate">
                  <span className="font-medium text-ink">{r.product_name || r.tenant_id}</span>{" "}
                  <span className="font-mono text-[11.5px] text-steel">{r.tenant_id}</span>
                </span>
                <span className="flex-none text-[11.5px] text-steel">
                  {r.has_token ? t("saas.ws.tokenOk") : t("saas.ws.tokenNo")}
                  {r.onboarded ? ` · ${t("saas.ws.onboarded")}` : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-ctl border border-hair bg-canvas px-[13px] py-[9px] text-[13px]">
      <span className="flex-none text-steel">{label}</span>
      <span className="min-w-0 truncate text-right font-mono select-all">{value}</span>
    </div>
  );
}
