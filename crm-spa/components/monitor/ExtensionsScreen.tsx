"use client";

import { useEffect, useState } from "react";
import {
  PageHeader,
  Eyebrow,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  Button,
  Skeleton,
  ErrorState,
  Banner,
} from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useResource } from "./kit";

/**
 * ExtensionsScreen — «Внутренние номера»: сопоставление оператора и Tegsoft
 * extension (crm.operator_extensions через api/calls.py). Без extension звонок
 * оператора падает (422) — это блокер телефонии. Управляет super_admin/главы.
 */
interface ExtRow {
  operator_id: string;
  full_name: string;
  role: string;
  ext: string | null;
  usercode: string | null;
  has_password: boolean;
  has_token: boolean;
  updated_at: string | null;
}
interface ExtData {
  operators: ExtRow[];
}

export function ExtensionsScreen() {
  const t = useT();
  const { state, data, error, reload } = useResource<ExtData>("/api/v1/calls/extensions");

  return (
    <>
      <PageHeader
        title={t("ext.title")}
        accent={t("ext.accent")}
        lead={t("ext.lead")}
      />
      {state === "error" ? (
        <div className="mt-6">
          <ErrorState description={error ?? undefined} onRetry={reload} />
        </div>
      ) : state === "loading" || !data ? (
        <div className="mt-6 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : (
        <ExtTable rows={data.operators} onSaved={reload} />
      )}
    </>
  );
}

function ExtTable({ rows, onSaved }: { rows: ExtRow[]; onSaved: () => void }) {
  const t = useT();
  // на этом кластере звонок идёт через entegreapi + extension → достаточно ext
  const ready = (r: ExtRow) => Boolean(r.ext);
  const missing = rows.filter((r) => !ready(r)).length;
  return (
    <div className="mt-4">
      {missing > 0 ? (
        <Banner className="!mt-0 mb-3">⚠ {t("ext.warnMissing", { n: missing })}</Banner>
      ) : null}
      <Eyebrow>{t("ext.tableCaption")}</Eyebrow>
      <div className="mt-2 overflow-hidden rounded-card border border-hair bg-canvas">
        <Table>
          <THead>
            <TR>
              <TH className="!text-left">{t("ext.colOperator")}</TH>
              <TH className="!text-left">{t("ext.colExt")}</TH>
              <TH className="!text-left">{t("ext.colToken")}</TH>
              <TH></TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((r) => (
              <ExtRowEditor key={r.operator_id} row={r} onSaved={onSaved} />
            ))}
          </TBody>
        </Table>
      </div>
    </div>
  );
}

function ExtRowEditor({ row, onSaved }: { row: ExtRow; onSaved: () => void }) {
  const t = useT();
  const [ext, setExt] = useState(row.ext ?? "");
  const [token, setToken] = useState("");         // write-only: пусто = не менять
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => setExt(row.ext ?? ""), [row.ext]);

  const dirty = ext.trim() !== (row.ext ?? "") || token.trim() !== "";
  const ready = Boolean(row.ext);                    // звонок = entegreapi + ext
  const hasAny = Boolean(row.ext || row.has_token);  // есть что сбрасывать

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await flaskFetch(`/api/v1/calls/extensions/${row.operator_id}`, {
        method: "PUT",
        body: { ext: ext.trim(), token: token.trim() || undefined },
      });
      setToken("");
      onSaved();
    } catch (e) {
      setErr(flaskErrorText(e, t, "common.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function testCall() {
    const dest = window.prompt(t("ext.testPrompt"), "90");
    if (!dest) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await flaskFetch<{ ext: string; destination_masked: string }>(
        "/api/v1/calls/test",
        { method: "POST", body: { operator_id: row.operator_id, destination: dest.trim() } },
      );
      window.alert(t("ext.testOk", { ext: r.ext, dest: r.destination_masked }));
    } catch (e) {
      setErr(flaskErrorText(e, t, "common.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm(t("ext.resetConfirm", { name: row.full_name }))) return;
    setBusy(true);
    setErr(null);
    try {
      await flaskFetch(`/api/v1/calls/extensions/${row.operator_id}`, { method: "DELETE" });
      setExt("");
      setToken("");
      onSaved();
    } catch (e) {
      setErr(flaskErrorText(e, t, "common.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <TR className={ready ? undefined : "bg-cream/40"}>
      <TD className="!text-left">
        <div className="font-medium text-ink">{row.full_name}</div>
        <div className="text-steel font-mono text-[11px]">{row.role}</div>
      </TD>
      <TD className="!text-left">
        <input
          value={ext}
          onChange={(e) => setExt(e.target.value)}
          placeholder={t("ext.placeholder")}
          inputMode="numeric"
          className="w-20 rounded-md border border-hair2 bg-surface px-2.5 py-1.5 text-[13.5px] font-mono text-ink"
        />
      </TD>
      <TD className="!text-left">
        <input
          value={token}
          onChange={(e) => setToken(e.target.value)}
          type="password"
          autoComplete="off"
          placeholder={row.has_token ? t("ext.tokenKeep") : t("ext.tokenNew")}
          className="w-44 rounded-md border border-hair2 bg-surface px-2.5 py-1.5 text-[13px] font-mono text-ink"
        />
        <span className={"ml-2 text-[11.5px] " + (row.has_token ? "text-pos" : "text-stone")}>
          {row.has_token ? t("ext.tokenSet") : t("ext.tokenNone")}
        </span>
      </TD>
      <TD className="!text-right whitespace-nowrap">
        {err ? <span className="mr-2 text-[12px] text-neg">{err}</span> : null}
        {ready && !dirty ? (
          <Button variant="ghost" size="sm" onClick={testCall} disabled={busy} className="mr-1.5">
            {t("ext.test")}
          </Button>
        ) : null}
        {hasAny ? (
          <Button variant="ghost" size="sm" onClick={reset} disabled={busy} className="mr-1.5 !text-neg">
            {t("ext.reset")}
          </Button>
        ) : null}
        <Button variant="brand" size="sm" onClick={save} disabled={!dirty || busy} loading={busy}>
          {t("ext.save")}
        </Button>
      </TD>
    </TR>
  );
}
