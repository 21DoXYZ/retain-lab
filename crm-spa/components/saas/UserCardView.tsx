"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Banner, PageHeader } from "@/components/ui";

/**
 * /users/[id] — карточка юзера: система юзероцентрична, и это её центр.
 * Всё о человеке (стадия, деньги, контакты, касания, офферы, события) плюс
 * ручные действия владельца: добавить контакт, написать в любой канал,
 * зачислить в кампанию или снять с неё. GET /api/v1/saas/user?identity=.
 */

interface CardUser {
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

interface Contact { channel: string; address: string; consent: number; consent_ts: string }
interface Enrollment { campaign_id: string; status: string; step_idx: number; next_step_at: string; control: number; enrolled_at: string }
interface Touch { campaign_id: string; step_idx: number; action: string; detail: string; status: string; reason: string; ts: string }
interface OfferRow { offer_id: string; campaign_id: string; status: string; reason: string; cost_estimate: number; issued_at: string }
interface EventRow { event_type: string; ts: string; amount: number; plan_id: string; page: string }

interface CardData {
  user: CardUser;
  contacts: Contact[];
  email_suppressed: boolean;
  enrollments: Enrollment[];
  touches: Touch[];
  offers: OfferRow[];
  events: EventRow[];
  campaigns: { id: string; title: string }[];
  wa_chat: string;
  autopilot: boolean;
}

const STAGE_TONE: Record<string, string> = {
  DUNNING: "bg-[#fef3f2] text-neg border-[#fecdca]",
  SAVE: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  CONVERT: "bg-cream text-primary border-beige",
  UPGRADE: "bg-[#ecfdf3] text-pos border-[#abefc6]",
  ACTIVATE: "bg-surface text-slate border-hair2",
  WINBACK: "bg-surface text-slate border-hair2",
  MONITOR: "bg-surface text-steel border-hair2",
};

const SEND_STATUS_TONE: Record<string, string> = {
  sent: "text-pos", queued: "text-pos", issued: "text-pos",
  dry_run: "text-steel", holdout: "text-steel",
  rejected: "text-neg", retry: "text-[#b54708]",
};

function usd(n: number): string {
  return "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

const ADD_CHANNELS = ["whatsapp", "sms", "viber", "telegram"];

const inputCls =
  "w-full rounded-ctl border border-hair2 bg-canvas px-3 py-2 text-[13px] text-ink " +
  "placeholder:text-steel focus:border-primary focus:outline-none";

const btnPrimary =
  "rounded-full bg-primary px-4 py-1.5 text-[12.5px] font-semibold text-white " +
  "transition-opacity hover:opacity-90 disabled:opacity-40";

const btnGhost =
  "rounded-full border border-hair2 bg-canvas px-3.5 py-1.5 text-[12.5px] font-semibold " +
  "text-slate transition-colors hover:border-primary disabled:opacity-40";

export function UserCardView({ identity }: { identity: string }) {
  const t = useT();
  const [data, setData] = useState<CardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    flaskFetch<CardData>(`/api/v1/saas/user?identity=${encodeURIComponent(identity)}`)
      .then((d) => { setData(d); setError(""); })
      .catch((e: unknown) => setError(flaskErrorText(e, t, "common.loadFailed")))
      .finally(() => setLoading(false));
  }, [identity, t]);

  useEffect(() => load(), [load]);

  // ── добавить контакт ──
  const [addOpen, setAddOpen] = useState(false);
  const [addChannel, setAddChannel] = useState("whatsapp");
  const [addAddress, setAddAddress] = useState("");
  const [addConsent, setAddConsent] = useState(true);
  const [addBusy, setAddBusy] = useState(false);
  const [addErr, setAddErr] = useState("");

  const saveContact = () => {
    setAddBusy(true); setAddErr("");
    flaskFetch("/api/v1/saas/user/contact", {
      method: "POST",
      body: { identity, channel: addChannel, address: addAddress, consent: addConsent },
    })
      .then(() => { setAddOpen(false); setAddAddress(""); load(); })
      .catch((e: unknown) => setAddErr(flaskErrorText(e, t, "common.saveFailed")))
      .finally(() => setAddBusy(false));
  };

  // ── ручное касание ──
  const [chan, setChan] = useState("");
  const [subject, setSubject] = useState("");
  const [msg, setMsg] = useState("");
  const [sendBusy, setSendBusy] = useState(false);
  const [sendErr, setSendErr] = useState("");
  const [sendOk, setSendOk] = useState("");

  const sendChannels = useMemo(() => {
    if (!data) return [];
    const out: string[] = [];
    if (data.user.email) out.push("email");
    if (data.user.client_user_id) out.push("inapp");
    for (const c of data.contacts) if (c.consent && !out.includes(c.channel)) out.push(c.channel);
    return out;
  }, [data]);

  useEffect(() => {
    if (sendChannels.length && !sendChannels.includes(chan)) setChan(sendChannels[0]);
  }, [sendChannels, chan]);

  const needSubject = chan === "email" || chan === "inapp";

  const sendTouch = () => {
    setSendBusy(true); setSendErr(""); setSendOk("");
    flaskFetch<{ status: string }>("/api/v1/saas/user/touch", {
      method: "POST",
      body: { identity, channel: chan, subject, body: msg },
    })
      .then((r) => {
        setMsg(""); setSubject("");
        setSendOk(r.status === "dry_run" ? t("saas.ucard.send.dryRun") : t("saas.ucard.send.done"));
        load();
      })
      .catch((e: unknown) => setSendErr(flaskErrorText(e, t, "common.saveFailed")))
      .finally(() => setSendBusy(false));
  };

  // ── кампании ──
  const [enrollId, setEnrollId] = useState("");
  const [campBusy, setCampBusy] = useState(false);
  const [campErr, setCampErr] = useState("");

  const enrollAction = (campaign_id: string, action: "enroll" | "exit") => {
    setCampBusy(true); setCampErr("");
    flaskFetch("/api/v1/saas/user/enroll", {
      method: "POST", body: { identity, campaign_id, action },
    })
      .then(() => { setEnrollId(""); load(); })
      .catch((e: unknown) => setCampErr(flaskErrorText(e, t, "common.saveFailed")))
      .finally(() => setCampBusy(false));
  };

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <div className="h-8 w-64 animate-pulse rounded-ctl bg-surface" />
        <div className="h-24 animate-pulse rounded-ctl bg-surface" />
        <div className="h-64 animate-pulse rounded-ctl bg-surface" />
      </div>
    );
  }
  if (error || !data) {
    return <Banner className="mt-0">{error || t("saas.ucard.notFound")}</Banner>;
  }

  const u = data.user;
  const title = u.email || u.client_user_id || u.identity_id.slice(0, 12);
  const activeEnroll = data.enrollments.filter((e) => e.status === "active");
  const enrollable = data.campaigns.filter(
    (c) => !activeEnroll.some((e) => e.campaign_id === c.id));

  return (
    <div className="flex flex-col gap-5">
      <div>
        <a href="/users" className="text-[12.5px] font-medium text-steel hover:text-primary">
          &larr; {t("saas.ucard.back")}
        </a>
      </div>

      <PageHeader
        title={title}
        lead={u.client_user_id && u.client_user_id !== title ? u.client_user_id : ""}
      />

      {/* стадия + деньги */}
      <div className="flex flex-wrap items-center gap-2">
        <span className={"inline-block rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold " + (STAGE_TONE[u.stage] ?? STAGE_TONE.MONITOR)}>
          {u.stage_note === "post_cancel_cooldown"
            ? t("saas.users.stage.justCanceled")
            : t(`saas.stage.${u.stage}` as MessageKey)}
        </span>
        {u.action ? <span className="font-mono text-[12px] text-slate">{u.action}</span> : null}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {[
          { k: "saas.ucard.stat.plan", v: u.plan_id || "-" },
          { k: "saas.ucard.stat.mrr", v: usd(u.mrr) },
          { k: "saas.ucard.stat.atStake", v: u.value_at_stake > 0 ? usd(u.value_at_stake) : "-", neg: u.value_at_stake > 0 },
          { k: "saas.ucard.stat.churn", v: u.p_churn > 0 ? (u.p_churn * 100).toFixed(0) + "%" : "-" },
          { k: "saas.ucard.stat.ltv", v: usd(u.ltv) },
          { k: "saas.ucard.stat.lastSeen", v: u.last_seen ? u.last_seen.slice(0, 10) : "-" },
        ].map((s) => (
          <div key={s.k} className="rounded-ctl border border-hair bg-surface p-3">
            <div className="text-[11px] font-medium uppercase tracking-wide text-steel">
              {t(s.k as MessageKey)}
            </div>
            <div className={"mt-1 font-mono text-[15px] font-semibold " + (s.neg ? "text-neg" : "text-ink")}>
              {s.v}
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        {/* ── левая колонка: написать + история ── */}
        <div className="flex min-w-0 flex-col gap-5">
          <section className="rounded-ctl border border-hair bg-surface p-4">
            <h2 className="text-[13.5px] font-semibold text-ink">{t("saas.ucard.send.title")}</h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-steel">{t("saas.ucard.send.lead")}</p>
            {sendChannels.length === 0 ? (
              <p className="mt-3 text-[12.5px] text-steel">{t("saas.ucard.send.noChannels")}</p>
            ) : (
              <div className="mt-3 flex flex-col gap-2.5">
                <div className="flex flex-wrap gap-2">
                  {sendChannels.map((c) => (
                    <button key={c} onClick={() => setChan(c)}
                      className={"rounded-full border px-3 py-1 text-[12px] font-semibold transition-colors " +
                        (chan === c ? "border-primary bg-primary text-white" : "border-hair2 bg-canvas text-slate hover:border-primary")}>
                      {t(`saas.ucard.ch.${c}` as MessageKey)}
                    </button>
                  ))}
                </div>
                {needSubject ? (
                  <input value={subject} onChange={(e) => setSubject(e.target.value)}
                    placeholder={t("saas.ucard.send.subject")} className={inputCls} />
                ) : null}
                <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={4}
                  placeholder={t("saas.ucard.send.placeholder")} className={inputCls + " resize-y"} />
                <div className="flex items-center gap-3">
                  <button onClick={sendTouch} className={btnPrimary}
                    disabled={sendBusy || !msg.trim() || (needSubject && !subject.trim())}>
                    {sendBusy ? t("saas.ucard.send.sending") : t("saas.ucard.send.btn")}
                  </button>
                  {sendOk ? <span className="text-[12.5px] font-medium text-pos">{sendOk}</span> : null}
                  {sendErr ? <span className="text-[12.5px] text-neg">{sendErr}</span> : null}
                </div>
              </div>
            )}
          </section>

          <section className="rounded-ctl border border-hair bg-surface p-4">
            <h2 className="text-[13.5px] font-semibold text-ink">{t("saas.ucard.touches.title")}</h2>
            {data.touches.length === 0 ? (
              <p className="mt-2 text-[12.5px] text-steel">{t("saas.ucard.touches.empty")}</p>
            ) : (
              <ul className="mt-2 divide-y divide-hair">
                {data.touches.map((s, i) => (
                  <li key={i} className="flex items-baseline gap-3 py-2 text-[12.5px]">
                    <span className="w-[130px] shrink-0 font-mono text-[11.5px] text-steel">
                      {s.ts.slice(0, 16)}
                    </span>
                    <span className="w-[70px] shrink-0 font-mono text-[11.5px] text-slate">{s.action}</span>
                    <span className="min-w-0 flex-1 truncate text-slate" title={s.detail}>
                      {s.campaign_id === "manual" ? t("saas.ucard.touches.manual") + " " : ""}{s.detail}
                    </span>
                    <span className={"shrink-0 font-mono text-[11.5px] " + (SEND_STATUS_TONE[s.status] ?? "text-steel")}
                          title={s.reason || undefined}>
                      {s.status}{s.reason ? ` (${s.reason})` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-ctl border border-hair bg-surface p-4">
            <h2 className="text-[13.5px] font-semibold text-ink">{t("saas.ucard.events.title")}</h2>
            {data.events.length === 0 ? (
              <p className="mt-2 text-[12.5px] text-steel">{t("saas.ucard.events.empty")}</p>
            ) : (
              <ul className="mt-2 divide-y divide-hair">
                {data.events.map((e, i) => (
                  <li key={i} className="flex items-baseline gap-3 py-2 text-[12.5px]">
                    <span className="w-[130px] shrink-0 font-mono text-[11.5px] text-steel">
                      {e.ts.slice(0, 16)}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-slate">
                      {e.event_type}{e.page ? ` · ${e.page}` : ""}
                    </span>
                    {e.amount > 0 ? (
                      <span className="shrink-0 font-mono text-[11.5px] text-ink">{usd(e.amount)}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* ── правая колонка: контакты + кампании + офферы ── */}
        <div className="flex flex-col gap-5">
          <section className="rounded-ctl border border-hair bg-surface p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[13.5px] font-semibold text-ink">{t("saas.ucard.contacts.title")}</h2>
              <button onClick={() => { setAddOpen(!addOpen); setAddErr(""); }} className={btnGhost}>
                {addOpen ? t("ui.cancel") : t("saas.ucard.contacts.add")}
              </button>
            </div>

            <ul className="mt-2 flex flex-col gap-1.5 text-[12.5px]">
              {u.email ? (
                <li className="flex items-center justify-between gap-2">
                  <span className="text-steel">{t("saas.ucard.ch.email")}</span>
                  <span className="min-w-0 truncate font-mono text-[12px] text-slate">{u.email}</span>
                  {data.email_suppressed ? (
                    <span className="shrink-0 rounded-full border border-[#fecdca] bg-[#fef3f2] px-2 py-0.5 text-[10.5px] font-semibold text-neg">
                      {t("saas.ucard.contacts.suppressed")}
                    </span>
                  ) : null}
                </li>
              ) : null}
              {data.contacts.map((c) => (
                <li key={c.channel + c.address} className="flex items-center justify-between gap-2">
                  <span className="text-steel">{t(`saas.ucard.ch.${c.channel}` as MessageKey)}</span>
                  <span className="min-w-0 truncate font-mono text-[12px] text-slate">{c.address}</span>
                  {!c.consent ? (
                    <span className="shrink-0 rounded-full border border-hair2 bg-canvas px-2 py-0.5 text-[10.5px] font-semibold text-steel">
                      {t("saas.ucard.contacts.noConsent")}
                    </span>
                  ) : null}
                </li>
              ))}
              {!u.email && data.contacts.length === 0 ? (
                <li className="text-steel">{t("saas.ucard.contacts.empty")}</li>
              ) : null}
            </ul>

            {data.wa_chat ? (
              <a href={`/wa-inbox?chat=${encodeURIComponent(data.wa_chat)}`}
                 className="mt-2 inline-block text-[12.5px] font-medium text-primary hover:underline">
                {t("saas.ucard.contacts.openWa")}
              </a>
            ) : null}

            {addOpen ? (
              <div className="mt-3 flex flex-col gap-2 rounded-ctl border border-hair2 bg-canvas p-3">
                <select value={addChannel} onChange={(e) => setAddChannel(e.target.value)} className={inputCls}>
                  {ADD_CHANNELS.map((c) => (
                    <option key={c} value={c}>{t(`saas.ucard.ch.${c}` as MessageKey)}</option>
                  ))}
                </select>
                <input value={addAddress} onChange={(e) => setAddAddress(e.target.value)}
                  placeholder={addChannel === "telegram"
                    ? t("saas.ucard.contacts.chatIdPh")
                    : t("saas.ucard.contacts.phonePh")}
                  className={inputCls} />
                <label className="flex items-start gap-2 text-[12px] leading-snug text-slate">
                  <input type="checkbox" checked={addConsent}
                    onChange={(e) => setAddConsent(e.target.checked)} className="mt-0.5" />
                  {t("saas.ucard.contacts.consent")}
                </label>
                {addErr ? <div className="text-[12px] text-neg">{addErr}</div> : null}
                <button onClick={saveContact} disabled={addBusy || !addAddress.trim()} className={btnPrimary}>
                  {addBusy ? t("saas.ucard.send.sending") : t("ui.save")}
                </button>
              </div>
            ) : null}
          </section>

          <section className="rounded-ctl border border-hair bg-surface p-4">
            <h2 className="text-[13.5px] font-semibold text-ink">{t("saas.ucard.camp.title")}</h2>
            {!data.autopilot ? (
              <p className="mt-2 rounded-ctl border border-[#fedf89] bg-[#fffaeb] p-2.5 text-[12px] leading-snug text-[#b54708]">
                {t("saas.ucard.camp.autopilotOff")}
              </p>
            ) : null}
            {data.enrollments.length === 0 ? (
              <p className="mt-2 text-[12.5px] text-steel">{t("saas.ucard.camp.empty")}</p>
            ) : (
              <ul className="mt-2 flex flex-col gap-2">
                {data.enrollments.map((e) => (
                  <li key={e.campaign_id + e.enrolled_at}
                      className="rounded-ctl border border-hair2 bg-canvas p-2.5 text-[12.5px]">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[12px] text-ink">{e.campaign_id}</span>
                      <span className={"font-mono text-[11px] " +
                        (e.status === "active" ? "text-pos" : "text-steel")}>
                        {e.status}{e.control ? " · holdout" : ""}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-2 text-[11.5px] text-steel">
                      <span>{t("saas.ucard.camp.step", { n: String(e.step_idx) })}</span>
                      {e.status === "active" ? (
                        <button onClick={() => enrollAction(e.campaign_id, "exit")}
                                disabled={campBusy}
                                className="font-medium text-neg hover:underline disabled:opacity-40">
                          {t("saas.ucard.camp.exit")}
                        </button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {enrollable.length > 0 ? (
              <div className="mt-3 flex flex-col gap-2">
                <select value={enrollId} onChange={(e) => setEnrollId(e.target.value)} className={inputCls}>
                  <option value="">{t("saas.ucard.camp.pick")}</option>
                  {enrollable.map((c) => (
                    <option key={c.id} value={c.id}>{c.title}</option>
                  ))}
                </select>
                <button onClick={() => enrollAction(enrollId, "enroll")}
                        disabled={campBusy || !enrollId} className={btnGhost}>
                  {t("saas.ucard.camp.enroll")}
                </button>
                <p className="text-[11.5px] leading-snug text-steel">{t("saas.ucard.camp.hint")}</p>
              </div>
            ) : null}
            {campErr ? <div className="mt-2 text-[12px] text-neg">{campErr}</div> : null}
          </section>

          <section className="rounded-ctl border border-hair bg-surface p-4">
            <h2 className="text-[13.5px] font-semibold text-ink">{t("saas.ucard.offers.title")}</h2>
            {data.offers.length === 0 ? (
              <p className="mt-2 text-[12.5px] text-steel">{t("saas.ucard.offers.empty")}</p>
            ) : (
              <ul className="mt-2 flex flex-col gap-1.5 text-[12.5px]">
                {data.offers.map((o, i) => (
                  <li key={i} className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-[12px] text-slate">{o.offer_id}</span>
                    <span className={"shrink-0 font-mono text-[11px] " + (SEND_STATUS_TONE[o.status] ?? "text-steel")}>
                      {o.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
