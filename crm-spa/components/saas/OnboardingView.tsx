"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Button, Card, PageHeader } from "@/components/ui";
import { NoTenant, isNoTenant } from "./NoTenant";

/**
 * /onboarding — визард «Get started»: 4 шага с живыми статусами и ГОТОВЫМИ
 * артефактами (сниппет уже с токеном - копируй и вставляй, ничего
 * пересоздавать не нужно). GET /api/v1/saas/onboarding.
 */

interface Payload {
  steps: { snippet: boolean; stripe: boolean; channels: boolean; offers: boolean; autopilot: boolean };
  snippet: {
    token: string; html: string; ingest_url: string;
    rejects: { count: number; last_seen: string; origin: string; token_prefix: string } | null;
    events: number;
    last_event: string;
  };
  stripe: { webhook_url: string; events: string[]; secret_set: boolean; api_key_set: boolean };
  channels: { channel: string; state: string }[];
  offers: { offer_id: string; title: string; max_per_user_30d: number; edited: boolean }[];
  answers: Record<string, unknown>;
  ai_enabled: boolean;
}

const STEP_ORDER = ["snippet", "stripe", "channels", "offers", "autopilot"] as const;

/** Поля опросника (зеркало compose.QUESTIONS): порядок = порядок в форме. */
const Q_FIELDS: { key: string; kind: "str" | "num" | "bool"; showIf?: (a: Record<string, string>) => boolean }[] = [
  { key: "product_name", kind: "str" },
  { key: "product_desc", kind: "str" },
  { key: "app_url", kind: "str" },
  { key: "client_api", kind: "bool" },
  { key: "value_unit", kind: "str" },
  { key: "monthly_units", kind: "num" },
  { key: "callback_url", kind: "str", showIf: (a) => a.client_api === "yes" },
  { key: "has_trial", kind: "bool" },
  { key: "trial_days", kind: "num", showIf: (a) => a.has_trial === "yes" },
  { key: "avg_plan_price", kind: "num" },
  { key: "max_discount_pct", kind: "num" },
  { key: "can_pause", kind: "bool" },
];

function Questionnaire({ prefill, onDone }: { prefill: Record<string, unknown>; onDone: () => void }) {
  const t = useT();
  const [a, setA] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of Q_FIELDS) {
      const v = prefill[f.key];
      if (v === undefined || v === null) continue;
      init[f.key] = f.kind === "bool" ? (v ? "yes" : "no") : String(v);
    }
    return init;
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState("");
  // Что мы САМИ нашли на сайте - чтобы поле честно говорило, откуда значение
  const [fromSite, setFromSite] = useState<Set<string>>(new Set());
  const [plans, setPlans] = useState<{ name: string; price_usd: number; units_included: number | null }[]>([]);
  // Пока сайт не разобран и ответов нет - показываем ОДНО поле, а не стену
  const [phase, setPhase] = useState<"site" | "review">(
    Object.keys(prefill || {}).length ? "review" : "site");

  const scanSite = () => {
    setScanning(true);
    setScanNote("");
    flaskFetch<{ profile: Record<string, unknown>; pages: string[]; note: string }>(
      "/api/v1/saas/scan", { method: "POST", body: { url: a.app_url } },
    )
      .then((d) => {
        const p = (d.profile || {}) as Record<string, unknown>;
        const filled: string[] = [];
        setA((prev) => {
          const next = { ...prev };
          for (const k of ["product_name", "product_desc", "value_unit",
                           "monthly_units", "avg_plan_price", "trial_days"]) {
            const v = p[k];
            if (v === null || v === undefined || v === "") continue;
            next[k] = String(v);
            filled.push(k);
          }
          if (p.trial_days) { next.has_trial = "yes"; filled.push("has_trial"); }
          return next;
        });
        setFromSite(new Set(filled));
        setPlans(Array.isArray(p.plans) ? (p.plans as typeof plans) : []);
        setPhase("review");
        setScanNote(filled.length
          ? t("saas.q.scan.done", { n: filled.length, pages: (d.pages || []).length })
          : t("saas.q.scan.empty"));
      })
      .catch((e: unknown) => setScanNote(e instanceof Error ? e.message : "scan failed"))
      .finally(() => setScanning(false));
  };

  const inputCls =
    "h-[38px] w-full rounded-ctl border border-hair2 bg-canvas px-3 text-[13px] " +
    "text-ink outline-none transition-[border-color] duration-150 focus:border-primary";

  // ── Шаг 1: спрашиваем ТОЛЬКО сайт. Всё остальное система достанет сама ──
  if (phase === "site") {
    return (
      <div className="flex flex-col gap-3">
        <p className="max-w-[640px] text-[13.5px] leading-relaxed text-slate">
          {t("saas.q.stage1.lead")}
        </p>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            className={inputCls + " sm:max-w-[420px]"}
            placeholder={t("saas.q.app_url.ph")}
            value={a.app_url ?? ""}
            onChange={(e) => setA((p) => ({ ...p, app_url: e.target.value }))}
            onKeyDown={(e) => { if (e.key === "Enter" && a.app_url) scanSite(); }}
          />
          <Button variant="brand" size="sm" loading={scanning}
                  disabled={!(a.app_url || "").trim()} onClick={scanSite}>
            {t("saas.q.stage1.cta")}
          </Button>
          <button type="button" className="cursor-pointer text-[12.5px] text-steel underline"
                  onClick={() => setPhase("review")}>
            {t("saas.q.stage1.skip")}
          </button>
        </div>
        {scanning && <p className="text-[12.5px] text-steel">{t("saas.q.stage1.working")}</p>}
        {scanNote && !scanning && <p className="text-[12.5px] text-steel">{scanNote}</p>}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Что мы вычитали с сайта - показываем как доказательство, а не на веру */}
      {plans.length > 0 && (
        <div className="rounded-ctl border border-hair bg-surface p-3">
          <div className="text-[12.5px] font-medium text-ink">{t("saas.q.plansFound")}</div>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {plans.map((pl, i) => (
              <span key={i} className="rounded-full border border-hair2 bg-canvas px-2.5 py-0.5 font-mono text-[11.5px] text-slate">
                {pl.name || "-"}: ${pl.price_usd}
                {pl.units_included ? ` / ${pl.units_included}` : ""}
              </span>
            ))}
          </div>
        </div>
      )}
      {fromSite.size > 0 && (
        <p className="text-[12.5px] leading-relaxed text-steel">
          {t("saas.q.stage2.lead", { n: fromSite.size })}
        </p>
      )}
      <div className="grid gap-2.5 sm:grid-cols-2">
        {Q_FIELDS.filter((f) => !f.showIf || f.showIf(a)).map((f) => (
          <label key={f.key} className="flex flex-col gap-1 text-[12px] text-steel">
            <span className="flex items-center gap-1.5">
              {t(`saas.q.${f.key}` as MessageKey)}
              {fromSite.has(f.key) ? (
                <span className="rounded-full border border-[#abefc6] bg-[#ecfdf3] px-1.5 py-0.5 text-[10px] font-semibold text-pos">
                  {t("saas.q.fromSite")}
                </span>
              ) : phase === "review" && fromSite.size > 0 && !a[f.key] ? (
                <span className="rounded-full border border-[#fedf89] bg-[#fffcf5] px-1.5 py-0.5 text-[10px] font-semibold text-[#b54708]">
                  {t("saas.q.checkThis")}
                </span>
              ) : null}
            </span>
            {f.kind === "bool" ? (
              <select
                className={inputCls + " cursor-pointer"}
                value={a[f.key] ?? ""}
                onChange={(e) => setA((p) => ({ ...p, [f.key]: e.target.value }))}
              >
                <option value="" disabled>-</option>
                <option value="yes">{t("saas.q.yes")}</option>
                <option value="no">{t("saas.q.no")}</option>
              </select>
            ) : f.key === "app_url" ? (
              <div className="flex gap-2">
                <input
                  className={inputCls}
                  placeholder={t("saas.q.app_url.ph")}
                  value={a[f.key] ?? ""}
                  onChange={(e) => setA((p) => ({ ...p, [f.key]: e.target.value }))}
                />
                <Button variant="ghost" size="sm" loading={scanning}
                        disabled={!(a.app_url || "").trim()} onClick={scanSite}>
                  {t("saas.q.scan")}
                </Button>
              </div>
            ) : (
              <input
                className={inputCls}
                inputMode={f.kind === "num" ? "decimal" : "text"}
                placeholder={t(`saas.q.${f.key}.ph` as MessageKey)}
                value={a[f.key] ?? ""}
                onChange={(e) => setA((p) => ({ ...p, [f.key]: e.target.value }))}
              />
            )}
          </label>
        ))}
      </div>
      {scanNote && <p className="text-[12px] text-primary">{scanNote}</p>}
      {err && <p className="text-[12px] text-neg">{err}</p>}
      <div>
        <Button
          variant="brand"
          size="sm"
          loading={busy}
          disabled={!a.product_name || !a.client_api || !a.has_trial || !a.can_pause || a.max_discount_pct === undefined || a.max_discount_pct === ""}
          onClick={() => {
            setBusy(true);
            setErr("");
            const answers: Record<string, unknown> = {};
            for (const f of Q_FIELDS) {
              const v = a[f.key];
              if (v === undefined || v === "") continue;
              answers[f.key] = f.kind === "bool" ? v === "yes" : f.kind === "num" ? Number(v) : v;
            }
            flaskFetch("/api/v1/saas/questionnaire", { method: "POST", body: { answers } })
              .then(onDone)
              .catch((e: unknown) => setErr(e instanceof Error ? e.message : t("saas.channels.err.generic")))
              .finally(() => setBusy(false));
          }}
        >
          {t("saas.q.generate")}
        </Button>
      </div>
    </div>
  );
}

function CopyBtn({ text, label, copied }: { text: string; label: string; copied: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => {
        void navigator.clipboard.writeText(text);
        setDone(true);
        window.setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? copied : label}
    </Button>
  );
}

function StepBadge({ done, waitKey }: { done: boolean; waitKey: MessageKey }) {
  const t = useT();
  return (
    <span
      className={
        "inline-block rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold " +
        (done ? "bg-[#ecfdf3] text-pos border-[#abefc6]" : "bg-[#fffaeb] text-[#b54708] border-[#fedf89]")
      }
    >
      {done ? t("saas.ob.done") : t(waitKey)}
    </span>
  );
}

/** Ключи Stripe клиента: подписной секрет вебхука + restricted-ключ. Оба живут
 *  в его аккаунте Stripe - платформа их только хранит и использует. */
function StripeKeys({ data, onSaved }: { data: Payload["stripe"]; onSaved: (p: Payload) => void }) {
  const t = useT();
  const [secret, setSecret] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const save = (body: Record<string, string>) => {
    setBusy(true);
    setErr("");
    flaskFetch<Payload>("/api/v1/saas/onboarding/stripe", { method: "POST", body })
      .then((p) => {
        setSecret("");
        setKey("");
        onSaved(p);
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : "error"))
      .finally(() => setBusy(false));
  };

  const field = (
    label: string, hint: string, ok: boolean, value: string,
    set: (v: string) => void, holder: string, send: (v: string) => Record<string, string>,
  ) => (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span className="text-[13px] text-slate">{label}</span>
        <span className={"text-[12px] " + (ok ? "text-pos" : "text-steel")}>
          {ok ? t("saas.ob.stripe.saved") : t("saas.ob.stripe.notSaved")}
        </span>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          className="h-[42px] w-full rounded-ctl border border-hair2 bg-canvas px-[13px] font-mono text-sm text-ink placeholder:text-steel/70 outline-none transition-[border-color] duration-150 focus:border-primary"
          placeholder={holder}
          value={value}
          onChange={(e) => set(e.target.value)}
        />
        <Button variant="brand" size="sm" loading={busy} disabled={!value.trim()}
                onClick={() => save(send(value.trim()))}>
          {t("saas.ob.stripe.save")}
        </Button>
      </div>
      <p className="text-[12.5px] leading-relaxed text-steel">{hint}</p>
    </div>
  );

  return (
    <div className="flex flex-col gap-4 rounded-ctl border border-hair bg-surface p-3.5">
      {field(t("saas.ob.stripe.secretLabel"), t("saas.ob.stripe.secretHint"),
             data.secret_set, secret, setSecret, "whsec_...", (v) => ({ webhook_secret: v }))}
      {field(t("saas.ob.stripe.keyLabel"), t("saas.ob.stripe.keyHint"),
             data.api_key_set, key, setKey, "rk_live_...", (v) => ({ api_key: v }))}
      {err && <p className="text-[12.5px] text-neg">{err}</p>}
    </div>
  );
}

/** Кнопка «проверить сейчас» с человеческим вердиктом вместо тишины. */
function SnippetCheck({ data, onData }: { data: Payload; onData: (p: Payload) => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState<Payload | null>(null);

  const run = () => {
    setBusy(true);
    flaskFetch<Payload>("/api/v1/saas/onboarding")
      .then((p) => {
        onData(p);
        setChecked(p);
      })
      .catch(() => {})
      .finally(() => setBusy(false));
  };

  const verdict = () => {
    if (!checked) return "";
    if (checked.steps.snippet) {
      return t("saas.ob.snippet.verdict.ok", {
        n: checked.snippet.events,
        when: checked.snippet.last_event.slice(0, 19) || "-",
      });
    }
    if (checked.snippet.rejects) {
      return t("saas.ob.snippet.verdict.badKey", {
        prefix: checked.snippet.rejects.token_prefix || "-",
      });
    }
    return t("saas.ob.snippet.verdict.silence");
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="brand" size="sm" loading={busy} onClick={run}>
        {t("saas.ob.snippet.check")}
      </Button>
      {checked && (
        <span className={"text-[12.5px] " + (checked.steps.snippet ? "text-pos" : "text-slate")}>
          {verdict()}
        </span>
      )}
    </div>
  );
}

export function OnboardingView() {
  const t = useT();
  const [data, setData] = useState<Payload | null>(null);
  const [state, setState] = useState<"loading" | "data" | "error" | "no_tenant">("loading");

  const load = useCallback(() => {
    flaskFetch<Payload>("/api/v1/saas/onboarding")
      .then((d) => {
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => setState(isNoTenant(e) ? "no_tenant" : "error"));
  }, []);

  useEffect(load, [load]);

  const doneCount = data ? STEP_ORDER.filter((k) => data.steps[k]).length : 0;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("saas.ob.title")}
        lead={t("saas.ob.lead")}
        right={
          <Button variant="ghost" size="sm" onClick={load}>
            {t("saas.ob.refresh")}
          </Button>
        }
      />

      {/* Шкала прогресса: что сделано / что осталось - видно сразу */}
      {data && (
        <div className="rounded-card border border-hair bg-canvas p-4">
          <div className="mb-2.5 flex items-baseline justify-between">
            <span className="text-[13.5px] font-semibold text-ink">
              {t("saas.ob.progress", { n: doneCount, total: STEP_ORDER.length })}
            </span>
            <span className="font-mono text-[12px] text-steel">
              {Math.round((doneCount / STEP_ORDER.length) * 100)}%
            </span>
          </div>
          <div className="flex gap-1.5">
            {STEP_ORDER.map((k) => (
              <div
                key={k}
                title={t(`saas.ob.${k}.title` as MessageKey)}
                className={
                  "h-2 flex-1 rounded-full transition-colors duration-300 " +
                  (data.steps[k] ? "bg-pos" : "bg-surface border border-hair2")
                }
              />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {STEP_ORDER.map((k, i) => (
              <span key={k} className={"text-[11.5px] " + (data.steps[k] ? "text-pos" : "text-steel")}>
                {data.steps[k] ? "✓" : i + 1} {t(`saas.ob.${k}.title` as MessageKey)}
              </span>
            ))}
          </div>
        </div>
      )}

      {state === "loading" && (
        <div className="flex flex-col gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-32 animate-pulse rounded-lg border border-hair bg-surface" />
          ))}
        </div>
      )}

      {state === "data" && data && (
        <>
          {/* ── Шаг 1: сниппет (готовый код с живым токеном) ── */}
          <Card className="flex flex-col gap-3 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[15px] font-semibold text-ink">
                <span className="mr-2 text-steel">1</span>
                {t("saas.ob.snippet.title")}
              </div>
              <StepBadge done={data.steps.snippet} waitKey="saas.ob.snippet.waiting" />
            </div>
            <p className="text-[13.5px] leading-relaxed text-slate">{t("saas.ob.snippet.desc")}</p>
            {/* Сайт стучится, но ключ не тот - самая частая причина «поставил,
                а статус не меняется». Говорим прямо, а не оставляем в тишине. */}
            {data.snippet.rejects && (
              <div className="rounded-ctl border border-[#fecdca] bg-[#fef3f2] p-3.5">
                <div className="text-[13px] font-semibold text-ink">
                  {t("saas.ob.snippet.badKey.title")}
                </div>
                <p className="mt-1 text-[12.5px] leading-relaxed text-slate">
                  {t("saas.ob.snippet.badKey.body", {
                    n: data.snippet.rejects.count,
                    origin: data.snippet.rejects.origin || "-",
                    prefix: data.snippet.rejects.token_prefix || "-",
                  })}
                </p>
              </div>
            )}

            {data.snippet.html ? (
              <>
                <pre className="overflow-x-auto rounded-ctl bg-sb p-3.5 font-mono text-[12px] leading-relaxed text-sb-text2 whitespace-pre">
                  {data.snippet.html}
                </pre>
                <div className="flex items-center gap-3">
                  <CopyBtn text={data.snippet.html} label={t("saas.ob.copyCode")} copied={t("saas.channels.copied")} />
                  <span className="text-[12.5px] text-steel">{t("saas.ob.snippet.identify")}</span>
                </div>
              </>
            ) : (
              /* Лучше честно сказать, что кода нет, чем показать чужой токен */
              <p className="rounded-ctl border border-[#fedf89] bg-[#fffcf5] p-3 text-[13px] text-slate">
                {t("saas.ob.snippet.noToken")}
              </p>
            )}
            <p className="text-[12.5px] text-steel">
              {data.steps.snippet ? t("saas.ob.snippet.okNote") : t("saas.ob.snippet.checkNote")}
            </p>

            {/* Явная проверка по кнопке: клиент вставил код и хочет ответ
                СРАЗУ, а не гадать, обновилась страница или нет. */}
            <SnippetCheck data={data} onData={setData} />
          </Card>

          {/* ── Шаг 2: Stripe ── */}
          <Card className="flex flex-col gap-3 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[15px] font-semibold text-ink">
                <span className="mr-2 text-steel">2</span>
                {t("saas.ob.stripe.title")}
              </div>
              <StepBadge done={data.steps.stripe} waitKey="saas.ob.stripe.waiting" />
            </div>
            <p className="text-[13.5px] leading-relaxed text-slate">{t("saas.ob.stripe.desc")}</p>
            <div className="flex items-center gap-2.5">
              <code className="min-w-0 flex-1 truncate rounded-ctl border border-hair bg-surface px-[13px] py-[9px] font-mono text-[12.5px]">
                {data.stripe.webhook_url}
              </code>
              <CopyBtn text={data.stripe.webhook_url} label={t("saas.channels.copy")} copied={t("saas.channels.copied")} />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {data.stripe.events.map((ev) => (
                <span key={ev} className="rounded-md border border-hair2 bg-surface px-2 py-0.5 font-mono text-[11.5px] text-slate">
                  {ev}
                </span>
              ))}
            </div>
            <StripeKeys data={data.stripe} onSaved={setData} />
          </Card>

          {/* ── Шаг 3: каналы ── */}
          <Card className="flex flex-col gap-3 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[15px] font-semibold text-ink">
                <span className="mr-2 text-steel">3</span>
                {t("saas.ob.channels.title")}
              </div>
              <StepBadge done={data.steps.channels} waitKey="saas.ob.channels.waiting" />
            </div>
            <p className="text-[13.5px] leading-relaxed text-slate">{t("saas.ob.channels.desc")}</p>
            <div className="flex flex-wrap gap-2">
              {data.channels.map((c) => (
                <span key={c.channel} className="inline-flex items-center gap-1.5 rounded-full border border-hair2 bg-surface px-3 py-1 text-[12px]">
                  <span className="font-semibold text-ink">{t(`saas.channels.name.${c.channel}` as MessageKey)}</span>
                  <span className="text-steel">{t(`saas.channels.state.${c.state}` as MessageKey)}</span>
                </span>
              ))}
            </div>
            <div>
              <Link href="/channel-settings">
                <Button variant="brand" size="sm">{t("saas.ob.channels.cta")}</Button>
              </Link>
            </div>
          </Card>

          {/* ── Шаг 4: офферы (щедрость и лимиты) ── */}
          <Card className="flex flex-col gap-3 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[15px] font-semibold text-ink">
                <span className="mr-2 text-steel">4</span>
                {t("saas.ob.offers.title")}
              </div>
              <StepBadge done={data.steps.offers} waitKey="saas.ob.offers.waiting" />
            </div>
            <p className="text-[13.5px] leading-relaxed text-slate">
              {t(Object.keys(data.answers ?? {}).length ? "saas.ob.offers.descDone" : "saas.q.lead")}
            </p>

            <Questionnaire prefill={data.answers ?? {}} onDone={load} />

            {data.offers.length > 0 && (
              <>
                <div className="mt-1 text-[12px] font-semibold uppercase tracking-[0.5px] text-steel">
                  {t("saas.ob.offers.listTitle", { n: data.offers.length })}
                </div>
                <div className="flex flex-col">
                  {data.offers.map((o) => (
                    <div key={o.offer_id} className="flex items-center justify-between gap-3 border-b border-hair py-1.5 text-[13px] last:border-0">
                      <span className="min-w-0 truncate text-ink">
                        {o.title}
                        {o.offer_id.startsWith("AI_") && (
                          <span className="ml-2 inline-block rounded-full border border-[#b2ddff] bg-[#eff8ff] px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                            AI
                          </span>
                        )}
                      </span>
                      <span className="flex-none font-mono text-[12px] text-steel">
                        {t("saas.ob.offers.cap", { n: o.max_per_user_30d })}
                      </span>
                    </div>
                  ))}
                </div>
                <div>
                  <Link href="/offers">
                    <Button variant="ghost" size="sm">{t("saas.ob.offers.cta")}</Button>
                  </Link>
                </div>
              </>
            )}
            {!data.ai_enabled && (
              <p className="text-[11.5px] text-steel">{t("saas.q.aiOff")}</p>
            )}
          </Card>

          {/* ── Шаг 5: автопилот ── */}
          <Card className="flex flex-col gap-3 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[15px] font-semibold text-ink">
                <span className="mr-2 text-steel">5</span>
                {t("saas.ob.autopilot.title")}
              </div>
              <StepBadge done={data.steps.autopilot} waitKey="saas.ob.autopilot.waiting" />
            </div>
            <p className="text-[13.5px] leading-relaxed text-slate">{t("saas.ob.autopilot.desc")}</p>
            <div>
              <Link href="/campaigns">
                <Button variant="brand" size="sm">{t("saas.ob.autopilot.cta")}</Button>
              </Link>
            </div>
          </Card>
        </>
      )}

      {state === "no_tenant" && <NoTenant />}

      {state === "error" && (
        <Card className="p-5">
          <p className="text-[13.5px] text-slate">{t("saas.channels.err.generic")}</p>
          <div className="mt-3">
            <Button variant="ghost" size="sm" onClick={load}>{t("common.retry")}</Button>
          </div>
        </Card>
      )}
    </div>
  );
}
