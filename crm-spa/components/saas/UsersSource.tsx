"use client";

import { useRef, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Button } from "@/components/ui";

/**
 * Откуда система берёт базу пользователей.
 *
 * Сниппет видит только то, что происходит ПОСЛЕ установки, а у работающего
 * продукта вся база уже есть - в его СУБД, в провайдере авторизации или в
 * биллинге. Здесь два пути без единой строки кода клиента: разово положить
 * выгрузку и подключить постоянный источник.
 *
 * Файл сначала РАЗБИРАЕТСЯ и показывается: какие колонки распознаны, сколько
 * строк пригодно и что именно попадёт в систему. Загрузка - вторым шагом,
 * осознанно.
 */

interface Preview {
  columns: string[];
  mapping: Record<string, string>;
  rows: number;
  usable: number;
  unusable: number;
  with_email: number;
  sample: { id: string; email: string; created_at: string }[];
}

const FIELD_LABELS: Record<string, string> = {
  id: "id",
  email: "email",
  created_at: "created",
  stripe_customer_id: "stripe",
};

export function UsersSource({ onImported }: { onImported?: () => void }) {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const [raw, setRaw] = useState("");
  const [name, setName] = useState("");
  const [prev, setPrev] = useState<Preview | null>(null);
  const [done, setDone] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const [kind, setKind] = useState("supabase");
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [srcNote, setSrcNote] = useState("");

  const inputCls =
    "h-[38px] w-full rounded-ctl border border-hair2 bg-canvas px-3 text-[13px] " +
    "text-ink outline-none transition-[border-color] duration-150 focus:border-primary";

  const readFile = (file: File) => {
    setErr("");
    setDone("");
    setName(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || "");
      setRaw(text);
      setBusy(true);
      flaskFetch<Preview>("/api/v1/saas/users/import", {
        method: "POST",
        body: { data: text, preview: true },
      })
        .then(setPrev)
        .catch((e: unknown) => setErr(e instanceof Error ? e.message : "error"))
        .finally(() => setBusy(false));
    };
    reader.readAsText(file);
  };

  const load = () => {
    setBusy(true);
    setErr("");
    flaskFetch<{ imported: number; skipped: number; without_email: number }>("/api/v1/saas/users/import", {
      method: "POST",
      body: { data: raw },
    })
      .then((r) => {
        setDone(t("saas.src.loaded", { n: r.imported, skipped: r.skipped })
                + (r.without_email ? " " + t("saas.src.noEmails", { n: r.without_email }) : ""));
        setPrev(null);
        setRaw("");
        onImported?.();
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : "error"))
      .finally(() => setBusy(false));
  };

  const connect = () => {
    setBusy(true);
    setSrcNote("");
    flaskFetch<{ users_seen: number }>("/api/v1/saas/users/source", {
      method: "POST",
      body: { kind, url: url.trim(), key: key.trim() },
    })
      .then((r) => {
        setSrcNote(t("saas.src.connected", { n: r.users_seen }));
        onImported?.();
      })
      .catch((e: unknown) => setSrcNote(e instanceof Error ? e.message : "error"))
      .finally(() => setBusy(false));
  };

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-[680px] text-[13px] leading-relaxed text-steel">
        {t("saas.src.lead")}
      </p>

      {/* ── Способ 1: положить выгрузку ── */}
      <div className="rounded-ctl border border-hair bg-surface p-3.5">
        <div className="text-[13px] font-medium text-ink">{t("saas.src.file.title")}</div>
        <p className="mt-1 text-[12.5px] leading-relaxed text-steel">
          {t("saas.src.file.desc")}
        </p>
        <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.tsv,.json,text/csv,application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) readFile(f);
            }}
          />
          <Button variant="ghost" size="sm" onClick={() => fileRef.current?.click()}>
            {t("saas.src.file.pick")}
          </Button>
          {name && <span className="font-mono text-[12px] text-slate">{name}</span>}
        </div>

        {prev && (
          <div className="mt-3 rounded-ctl border border-hair2 bg-canvas p-3">
            <div className="text-[12.5px] text-slate">
              {t("saas.src.file.understood", {
                rows: prev.rows, usable: prev.usable, bad: prev.unusable,
              })}
            </div>
            {prev.usable > 0 && prev.with_email < prev.usable && (
              /* Без почты человеку нельзя написать - сказать это ДО загрузки */
              <p className="mt-1.5 rounded-ctl border border-[#fedf89] bg-[#fffcf5] p-2 text-[12px] leading-relaxed text-[#b54708]">
                {t("saas.src.file.emailWarn", {
                  with: prev.with_email, total: prev.usable,
                })}
              </p>
            )}
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {Object.entries(prev.mapping).map(([field, column]) => (
                <span key={field} className="rounded-full border border-[#abefc6] bg-[#ecfdf3] px-2 py-0.5 font-mono text-[11px] text-pos">
                  {column} → {FIELD_LABELS[field] ?? field}
                </span>
              ))}
              {!Object.keys(prev.mapping).length && (
                <span className="text-[12px] text-[#b54708]">{t("saas.src.file.noColumns")}</span>
              )}
            </div>
            {prev.sample.length > 0 && (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-[11.5px]">
                  <tbody>
                    {prev.sample.map((r, i) => (
                      <tr key={i} className="border-t border-hair first:border-0">
                        <td className="py-1 pr-3 font-mono text-slate">{r.id || "-"}</td>
                        <td className="py-1 pr-3 font-mono text-slate">{r.email || "-"}</td>
                        <td className="py-1 font-mono text-steel">{r.created_at.slice(0, 10)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-2.5">
              <Button variant="brand" size="sm" loading={busy} disabled={!prev.usable}
                      onClick={load}>
                {t("saas.src.file.load", { n: prev.usable })}
              </Button>
            </div>
          </div>
        )}
        {done && <p className="mt-2 text-[12.5px] text-pos">{done}</p>}
        {err && <p className="mt-2 text-[12.5px] text-neg">{err}</p>}
      </div>

      {/* ── Способ 2: постоянный источник ── */}
      <div className="rounded-ctl border border-hair bg-surface p-3.5">
        <div className="text-[13px] font-medium text-ink">{t("saas.src.live.title")}</div>
        <p className="mt-1 text-[12.5px] leading-relaxed text-steel">
          {t("saas.src.live.desc")}
        </p>
        <div className="mt-2.5 grid gap-2 sm:grid-cols-3">
          <select className={inputCls + " cursor-pointer"} value={kind}
                  onChange={(e) => setKind(e.target.value)}>
            <option value="supabase">Supabase</option>
            <option value="clerk">Clerk</option>
            <option value="json">{t("saas.src.live.own")}</option>
          </select>
          {kind !== "clerk" && (
            <input className={inputCls} placeholder={t("saas.src.live.urlPh")}
                   value={url} onChange={(e) => setUrl(e.target.value)} />
          )}
          <input className={inputCls + " font-mono"} placeholder={t("saas.src.live.keyPh")}
                 value={key} onChange={(e) => setKey(e.target.value)} />
        </div>
        <div className="mt-2.5">
          <Button variant="brand" size="sm" loading={busy}
                  disabled={!key.trim() && kind !== "json"} onClick={connect}>
            {t("saas.src.live.connect")}
          </Button>
        </div>
        {srcNote && <p className="mt-2 text-[12.5px] text-slate">{srcNote}</p>}
      </div>
    </div>
  );
}
