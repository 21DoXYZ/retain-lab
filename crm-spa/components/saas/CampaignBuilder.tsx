"use client";

import { useEffect, useRef, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Button, Card } from "@/components/ui";

/**
 * Конструктор ручной кампании: широкие фильтры аудитории с живым превью
 * («сколько людей и скольким реально можно написать») + шаги email/in-app.
 * Запуск = снапшот-зачисление; дальше кампанию ведёт штатный тик со всеми
 * предохранителями (dry-run до автопилота, подавления, тихие часы).
 */

const STAGES = ["ACTIVATE", "CONVERT", "UPGRADE", "SAVE", "DUNNING", "WINBACK", "MONITOR"];

interface Preview {
  count: number;
  reachable_email: number;
  reachable_inapp: number;
  reach?: { email?: number; inapp?: number; phone?: number; whatsapp?: number; telegram?: number };
  description: string;
  ignored_filters: string[];
}

// Типы контакта для сегмента (совпадают с CONTACT_TOKENS движка сегментов).
const CONTACT_TYPES: { key: string; label: MessageKey }[] = [
  { key: "email", label: "saas.users.contact.email" },
  { key: "phone", label: "saas.users.contact.phone" },
  { key: "whatsapp", label: "saas.users.contact.whatsapp" },
  { key: "telegram", label: "saas.users.contact.telegram" },
  { key: "inapp", label: "saas.users.contact.inapp" },
];

interface BuilderStep {
  action: "email" | "inapp";
  subject: string;
  body: string;
  cta_label: string;
  cta_url: string;
  delay_h: string;
}

const EMPTY_STEP: BuilderStep = {
  action: "email", subject: "", body: "", cta_label: "", cta_url: "", delay_h: "0",
};

interface LaunchResult {
  campaign_id: string;
  enrolled: number;
  control: number;
  copy_warnings: string[];
  autopilot: boolean;
}

export function CampaignBuilder({ onLaunched }: { onLaunched: () => void }) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [stages, setStages] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [online, setOnline] = useState(false);
  const [seenDays, setSeenDays] = useState("");
  const [quietDays, setQuietDays] = useState("");
  const [signupWithin, setSignupWithin] = useState("");
  const [mrrMin, setMrrMin] = useState("");
  const [churnMin, setChurnMin] = useState("");
  const [intentMin, setIntentMin] = useState("");
  const [gensMin, setGensMin] = useState("");
  const [gensMax, setGensMax] = useState("");
  const [ticketsMin, setTicketsMin] = useState("");
  const [bugsMin, setBugsMin] = useState("");
  const [country, setCountry] = useState("");
  const [contacts, setContacts] = useState<string[]>([]);
  const [noContact, setNoContact] = useState(false);
  const [contactConsent, setContactConsent] = useState(false);
  const [controlPct, setControlPct] = useState("10");
  const [steps, setSteps] = useState<BuilderStep[]>([{ ...EMPTY_STEP }]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<LaunchResult | null>(null);

  const num = (v: string): number | undefined => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : undefined;
  };

  const audience = {
    stages: stages.length ? stages : undefined,
    status: status || undefined,
    online: online || undefined,
    seen_within_days: num(seenDays),
    not_seen_days: num(quietDays),
    signup_within_days: num(signupWithin),
    mrr_min: num(mrrMin),
    churn_min: num(churnMin),
    intent_min: num(intentMin),
    gens_min: num(gensMin),
    gens_max: num(gensMax),
    tickets_min: num(ticketsMin),
    bugs_min: num(bugsMin),
    country: country.trim() || undefined,
    contacts: contacts.length ? contacts : undefined,
    no_contact: noContact || undefined,
    contact_consent: contactConsent || undefined,
  };
  const audienceKey = JSON.stringify(audience);
  const previewSeq = useRef(0);

  useEffect(() => {
    const id = setTimeout(() => {
      // latest-wins: поздний ответ на старый фильтр не должен показать/дать
      // запустить не ту аудиторию (аудит r3 2026-08-26)
      const mine = ++previewSeq.current;
      flaskFetch<Preview>("/api/v1/saas/segments/preview", {
        method: "POST",
        body: { audience: JSON.parse(audienceKey) },
      })
        .then((p) => { if (mine === previewSeq.current) setPreview(p); })
        .catch(() => { if (mine === previewSeq.current) setPreview(null); });
    }, 400);
    return () => clearTimeout(id);
    // audienceKey - сериализованный фильтр целиком
  }, [audienceKey]);

  const setStep = (i: number, patch: Partial<BuilderStep>) =>
    setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const launch = () => {
    setBusy(true);
    setErr("");
    flaskFetch<LaunchResult>("/api/v1/saas/campaigns/custom", {
      method: "POST",
      body: {
        title,
        audience: JSON.parse(audienceKey),
        control_pct: num(controlPct) ?? 10,
        steps: steps.map((s) => ({
          action: s.action, subject: s.subject, body: s.body,
          cta_label: s.cta_label || undefined, cta_url: s.cta_url || undefined,
          delay_h: num(s.delay_h) ?? 0,
        })),
      },
    })
      .then((r) => { setResult(r); onLaunched(); })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : "error"))
      .finally(() => setBusy(false));
  };

  const inputCls = "rounded-ctl border border-hair2 bg-canvas px-3 py-1.5 text-[12.5px] text-ink outline-none transition-colors placeholder:text-steel focus:border-primary";
  const labelCls = "text-[11px] font-medium uppercase tracking-wide text-steel";

  if (result) {
    return (
      <Card className="p-5">
        <div className="text-[15px] font-semibold text-ink">{t("saas.builder.done.title")}</div>
        <p className="mt-2 text-[13px] text-slate">
          {t("saas.builder.done.body", { n: result.enrolled, c: result.control })}
        </p>
        {!result.autopilot ? (
          <p className="mt-2 text-[12.5px] text-amber-600">{t("saas.builder.done.dry")}</p>
        ) : null}
        {result.copy_warnings.length ? (
          <p className="mt-2 text-[12px] text-steel">
            {t("saas.builder.done.warnings")}: {result.copy_warnings.join(", ")}
          </p>
        ) : null}
      </Card>
    );
  }

  return (
    <Card className="flex flex-col gap-5 p-5">
      <div>
        <div className="text-[15px] font-semibold text-ink">{t("saas.builder.title")}</div>
        <p className="mt-1 text-[12.5px] text-steel">{t("saas.builder.lead")}</p>
      </div>

      <input className={inputCls + " max-w-[420px]"} value={title} maxLength={80}
             onChange={(e) => setTitle(e.target.value)}
             placeholder={t("saas.builder.namePh")} />

      {/* ── аудитория ── */}
      <div className="flex flex-col gap-3">
        <div className={labelCls}>{t("saas.builder.audience")}</div>
        <div className="flex flex-wrap gap-2">
          {STAGES.map((s) => (
            <button key={s}
              onClick={() => setStages(stages.includes(s) ? stages.filter((x) => x !== s) : [...stages, s])}
              className={"border rounded-full px-3 py-1 text-[12px] font-semibold transition-colors " +
                (stages.includes(s) ? "bg-primary text-white border-primary" : "bg-canvas text-slate border-hair2 hover:border-primary")}>
              {t(`saas.stage.${s}` as MessageKey)}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className={inputCls} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("saas.users.pay.any")}</option>
            <option value="paying">{t("saas.users.pay.paying")}</option>
            <option value="trial">{t("saas.users.pay.trial")}</option>
            <option value="free">{t("saas.users.pay.free")}</option>
          </select>
          <button onClick={() => setOnline(!online)}
            className={"inline-flex items-center gap-1.5 border rounded-full px-3 py-1.5 text-[12px] font-semibold transition-colors " +
              (online ? "bg-pos text-white border-pos" : "bg-canvas text-slate border-hair2 hover:border-pos")}>
            <span className={"h-1.5 w-1.5 rounded-full " + (online ? "bg-white" : "bg-pos")} />
            {t("saas.users.onlineNow")}
          </button>
          <input className={inputCls + " w-[130px]"} inputMode="numeric" value={seenDays}
                 onChange={(e) => setSeenDays(e.target.value)} placeholder={t("saas.builder.f.seen")} />
          <input className={inputCls + " w-[140px]"} inputMode="numeric" value={quietDays}
                 onChange={(e) => setQuietDays(e.target.value)} placeholder={t("saas.builder.f.quiet")} />
          <input className={inputCls + " w-[150px]"} inputMode="numeric" value={signupWithin}
                 onChange={(e) => setSignupWithin(e.target.value)} placeholder={t("saas.builder.f.signup")} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input className={inputCls + " w-[110px]"} inputMode="decimal" value={mrrMin}
                 onChange={(e) => setMrrMin(e.target.value)} placeholder={t("saas.builder.f.mrrMin")} />
          <input className={inputCls + " w-[140px]"} inputMode="decimal" value={churnMin}
                 onChange={(e) => setChurnMin(e.target.value)} placeholder={t("saas.builder.f.churnMin")} />
          <input className={inputCls + " w-[140px]"} inputMode="decimal" value={intentMin}
                 onChange={(e) => setIntentMin(e.target.value)} placeholder={t("saas.builder.f.intentMin")} />
          <input className={inputCls + " w-[130px]"} inputMode="numeric" value={gensMin}
                 onChange={(e) => setGensMin(e.target.value)} placeholder={t("saas.builder.f.gensMin")} />
          <input className={inputCls + " w-[130px]"} inputMode="numeric" value={gensMax}
                 onChange={(e) => setGensMax(e.target.value)} placeholder={t("saas.builder.f.gensMax")} />
          <input className={inputCls + " w-[150px]"} inputMode="numeric" value={ticketsMin}
                 onChange={(e) => setTicketsMin(e.target.value)} placeholder={t("saas.builder.f.tickets")} />
          <input className={inputCls + " w-[150px]"} inputMode="numeric" value={bugsMin}
                 onChange={(e) => setBugsMin(e.target.value)} placeholder={t("saas.builder.f.bugs")} />
          <input className={inputCls + " w-[110px]"} maxLength={2} value={country}
                 onChange={(e) => setCountry(e.target.value.toUpperCase())}
                 placeholder={t("saas.builder.f.country")} />
        </div>
        {/* тип контакта: кому и как можно написать (широкий фильтр, ИЛИ) */}
        <div className="flex flex-wrap items-center gap-2">
          <span className={labelCls}>{t("saas.builder.f.contact")}</span>
          {CONTACT_TYPES.map((c) => (
            <button key={c.key} type="button"
              onClick={() => { setNoContact(false); setContacts(contacts.includes(c.key) ? contacts.filter((x) => x !== c.key) : [...contacts, c.key]); }}
              className={"border rounded-full px-3 py-1 text-[12px] font-semibold transition-colors " +
                (contacts.includes(c.key) && !noContact ? "bg-primary text-white border-primary" : "bg-canvas text-slate border-hair2 hover:border-primary")}>
              {t(c.label)}
            </button>
          ))}
          <button type="button"
            onClick={() => { setContacts([]); setNoContact(!noContact); }}
            className={"border rounded-full px-3 py-1 text-[12px] font-semibold transition-colors " +
              (noContact ? "bg-neg text-white border-neg" : "bg-canvas text-slate border-hair2 hover:border-neg")}>
            {t("saas.users.contact.none")}
          </button>
          {contacts.length && !noContact ? (
            <label className="flex items-center gap-1.5 text-[12px] text-slate">
              <input type="checkbox" checked={contactConsent}
                     onChange={(e) => setContactConsent(e.target.checked)} />
              {t("saas.builder.f.consentOnly")}
            </label>
          ) : null}
        </div>
        <div className="rounded-ctl border border-hair bg-surface px-4 py-3 text-[13px]">
          {preview ? (
            <>
              <b className="text-ink">{t("saas.builder.preview", { n: preview.count })}</b>{" "}
              <span className="text-steel">
                {t("saas.builder.previewReach", { e: preview.reachable_email, i: preview.reachable_inapp })}
              </span>
              {preview.reach && (preview.reach.phone || preview.reach.telegram) ? (
                <span className="text-steel">
                  {" · "}phone {preview.reach.phone ?? 0} · TG {preview.reach.telegram ?? 0}
                </span>
              ) : null}
              {preview.ignored_filters.length ? (
                <div className="mt-1 text-[12px] text-amber-600">
                  {t("saas.builder.ignored")}: {preview.ignored_filters.join(", ")}
                </div>
              ) : null}
            </>
          ) : (
            <span className="text-steel">…</span>
          )}
        </div>
      </div>

      {/* ── шаги ── */}
      <div className="flex flex-col gap-3">
        <div className={labelCls}>{t("saas.builder.steps")}</div>
        {steps.map((s, i) => (
          <div key={i} className="flex flex-col gap-2 rounded-ctl border border-hair bg-surface p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px] text-steel">#{i + 1}</span>
              <select className={inputCls} value={s.action}
                      onChange={(e) => setStep(i, { action: e.target.value as BuilderStep["action"] })}>
                <option value="email">Email</option>
                <option value="inapp">In-app</option>
              </select>
              <input className={inputCls + " w-[150px]"} inputMode="decimal" value={s.delay_h}
                     onChange={(e) => setStep(i, { delay_h: e.target.value })}
                     placeholder={t("saas.builder.s.delay")} />
              {steps.length > 1 ? (
                <button onClick={() => setSteps(steps.filter((_, j) => j !== i))}
                        className="ml-auto text-[12px] text-steel transition-colors hover:text-neg">
                  {t("saas.builder.s.remove")}
                </button>
              ) : null}
            </div>
            <input className={inputCls} value={s.subject} maxLength={200}
                   onChange={(e) => setStep(i, { subject: e.target.value })}
                   placeholder={t("saas.builder.s.subject")} />
            <textarea className={inputCls + " min-h-[84px] resize-y"} value={s.body} maxLength={4000}
                      onChange={(e) => setStep(i, { body: e.target.value })}
                      placeholder={t("saas.builder.s.body")} />
            <div className="flex flex-wrap gap-2">
              <input className={inputCls + " w-[180px]"} value={s.cta_label} maxLength={80}
                     onChange={(e) => setStep(i, { cta_label: e.target.value })}
                     placeholder={t("saas.builder.s.ctaLabel")} />
              <input className={inputCls + " min-w-[240px] flex-1"} value={s.cta_url} maxLength={500}
                     onChange={(e) => setStep(i, { cta_url: e.target.value })}
                     placeholder={t("saas.builder.s.ctaUrl")} />
            </div>
          </div>
        ))}
        {steps.length < 5 ? (
          <button onClick={() => setSteps([...steps, { ...EMPTY_STEP }])}
                  className="self-start text-[12.5px] font-medium text-primary hover:underline">
            + {t("saas.builder.s.add")}
          </button>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-[12.5px] text-slate">
          {t("saas.builder.holdout")}
          <input className={inputCls + " w-[70px]"} inputMode="numeric" value={controlPct}
                 onChange={(e) => setControlPct(e.target.value)} />%
        </label>
        <Button onClick={launch} disabled={busy || !title.trim() || !preview?.count}>
          {busy ? "…" : t("saas.builder.launch", { n: preview?.count ?? 0 })}
        </Button>
        {err ? <span className="text-[12.5px] text-neg">{err}</span> : null}
      </div>
      <p className="text-[12px] text-steel">{t("saas.builder.note")}</p>
    </Card>
  );
}
