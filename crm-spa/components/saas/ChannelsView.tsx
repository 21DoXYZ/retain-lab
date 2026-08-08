"use client";

import { useCallback, useEffect, useState } from "react";
import { FlaskApiError, flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Banner, Button, Card, Field, PageHeader } from "@/components/ui";
import { NoTenant, isNoTenant } from "./NoTenant";

/**
 * /channel-settings — клиентский флоу подключения каналов. Инфраструктура
 * (аккаунты Resend/DecisionTelecom) платформенная, клиент подключает только
 * идентичность бренда: поддомен отправки, альфа-имя, своего телеграм-бота.
 * GET/POST /api/v1/saas/channels*.
 */

interface DnsRecord {
  record: string;
  type: string;
  name: string;
  value: string;
  status: string;
  priority?: number;
}

interface ChannelRow {
  channel: string;
  provider: string;
  state: string;
  detail: string;
  contacts: number;
  consented: number;
  email?: {
    domain: string; from: string; own_account?: boolean;
    webhook_secret_set?: boolean; webhook_url?: string; dns_records: DnsRecord[];
  };
  telegram?: { bot_username: string; connect_link: string };
  whatsapp?: {
    phone_display: string; has_waba: boolean; has_app_secret: boolean;
    webhook_url: string; webhook_verify_token: string;
    templates: { name: string; status: string; campaign_id: string;
                 step_idx: number; category: string; reason: string }[];
  };
}

type Payload = { channels: ChannelRow[] };

const STATE_TONE: Record<string, string> = {
  active: "bg-[#ecfdf3] text-pos border-[#abefc6]",
  sender_needed: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  pending_dns: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  pending_approval: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  awaiting_provider: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  not_connected: "bg-surface text-steel border-hair2",
  coming_soon: "bg-surface text-steel border-hair2",
};

const ERR_KEYS = new Set([
  "invalid_domain", "email_not_on_domain", "no_domain", "telegram_invalid_token",
  "invalid_sms_sender", "invalid_viber_sender", "resend_not_configured",
  "invalid_resend_key",
  "invalid_webhook_secret",
]);

/** Готовая кнопка подписки: сниппет сам подставит ссылку с id юзера. */
const TG_BUTTON = '<a data-ra-telegram>Get updates in Telegram</a>';

/** Сверху то, что включается само и за минуты; внизу то, что ждёт операторов. */
const CHANNEL_ORDER = ["inapp", "telegram", "email", "sms", "viber", "whatsapp"];

const inputCls =
  "h-[42px] w-full rounded-ctl border border-hair2 bg-canvas px-[13px] text-sm " +
  "text-ink placeholder:text-steel/70 outline-none transition-[border-color] " +
  "duration-150 focus:border-primary";

function StateBadge({ state }: { state: string }) {
  const t = useT();
  return (
    <span
      className={
        "inline-block rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold " +
        (STATE_TONE[state] ?? STATE_TONE.not_connected)
      }
    >
      {t(`saas.channels.state.${state}` as MessageKey)}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="cursor-pointer rounded-md border border-hair2 px-2 py-0.5 text-[11px] text-steel transition-[color,border-color] duration-150 hover:border-primary hover:text-primary active:scale-[.97]"
      onClick={() => {
        void navigator.clipboard.writeText(text);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? t("saas.channels.copied") : t("saas.channels.copy")}
    </button>
  );
}

/**
 * Шаг настройки. Сделанный сворачивается в одну строку с галочкой, текущий
 * раскрыт, будущий приглушён и не кликается: нетехнический человек должен
 * видеть ровно одно действие, а не пять полей сразу.
 */
function Step({
  n, title, state, summary, children,
}: {
  n: number;
  title: string;
  state: "done" | "current" | "locked";
  summary?: string;
  children?: React.ReactNode;
}) {
  const done = state === "done";
  return (
    <div className={"rounded-ctl border p-3.5 " + (state === "current"
      ? "border-hair2 bg-canvas"
      : "border-hair bg-surface")}>
      <div className="flex items-center gap-2">
        <span className={"flex h-5 w-5 flex-none items-center justify-center rounded-full text-[11px] font-semibold "
          + (done ? "bg-[#ecfdf3] text-pos" : state === "current" ? "bg-primary text-white" : "bg-hair2 text-steel")}>
          {done ? "✓" : n}
        </span>
        <span className={"text-[13px] font-medium " + (state === "locked" ? "text-steel" : "text-ink")}>
          {title}
        </span>
      </div>
      {done && summary ? (
        <div className="mt-1.5 pl-7 font-mono text-[12.5px] text-slate">{summary}</div>
      ) : null}
      {state === "current" ? <div className="mt-2.5 pl-7">{children}</div> : null}
    </div>
  );
}

function ChannelCard({
  row,
  refresh,
}: {
  row: ChannelRow;
  refresh: (p: Payload) => void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [domain, setDomain] = useState("");
  const [fromName, setFromName] = useState("");
  const [fromEmail, setFromEmail] = useState("");
  const [sender, setSender] = useState("");
  const [token, setToken] = useState("");
  const [resendKey, setResendKey] = useState("");
  const [whSecret, setWhSecret] = useState("");

  const post = useCallback(
    (path: string, body: Record<string, unknown>) => {
      setBusy(true);
      setErr("");
      flaskFetch<Payload>(`/api/v1/saas/channels/${path}`, { method: "POST", body })
        .then(refresh)
        .catch((e: unknown) => {
          const code = e instanceof FlaskApiError ? e.message : "";
          setErr(ERR_KEYS.has(code) ? t(`saas.channels.err.${code}` as MessageKey) : code || t("saas.channels.err.generic"));
        })
        .finally(() => setBusy(false));
    },
    [refresh, t],
  );

  const name = t(`saas.channels.name.${row.channel}` as MessageKey);
  const st = row.state;

  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[15px] font-semibold text-ink">{name}</div>
          <p className="mt-0.5 max-w-[560px] text-[13px] leading-relaxed text-slate">
            {t(`saas.channels.payoff.${row.channel}` as MessageKey)}
          </p>
        </div>
        <div className="flex flex-none flex-col items-end gap-1.5">
          <StateBadge state={st} />
          <span className="text-[11.5px] text-steel">
            {t(`saas.channels.effort.${row.channel}` as MessageKey)}
          </span>
        </div>
      </div>

      {/* ── Email: один шаг за раз, остальное скрыто ── */}
      {row.channel === "email" && (() => {
        const own = !!row.email?.own_account;
        const hasDomain = !!row.email?.domain;
        const verified = st === "sender_needed" || st === "active";
        // текущий шаг = первый незакрытый: так на экране всегда ровно одно дело
        const current = !own ? 1 : !hasDomain ? 2 : !verified ? 3 : st !== "active" ? 4 : 0;
        const at = (n: number): "done" | "current" | "locked" =>
          current === 0 || n < current ? "done" : n === current ? "current" : "locked";

        return (
          <div className="flex flex-col gap-2.5">
            <Step n={1} title={t("saas.channels.email.acct.title")} state={at(1)}
                  summary={own ? t("saas.channels.email.acct.ownShort") : undefined}>
              <p className="text-[12.5px] leading-relaxed text-steel">
                {t("saas.channels.email.acct.platform")}
              </p>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <input className={inputCls + " font-mono"} placeholder="re_..."
                       value={resendKey} onChange={(e) => setResendKey(e.target.value)} />
                <Button variant="brand" size="sm" loading={busy} disabled={!resendKey.trim()}
                        onClick={() => post("email/key", { api_key: resendKey.trim() })}>
                  {t("saas.channels.email.acct.connect")}
                </Button>
              </div>
            </Step>

            <Step n={2} title={t("saas.channels.email.domainLabel")} state={at(2)}
                  summary={row.email?.domain}>
              <p className="text-[12.5px] leading-relaxed text-steel">
                {t("saas.channels.email.domainHint")}
              </p>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <input className={inputCls} placeholder="mail.yourbrand.com"
                       value={domain} onChange={(e) => setDomain(e.target.value)} />
                <Button variant="brand" size="sm" loading={busy} disabled={!domain.trim()}
                        onClick={() => post("email/domain", { domain: domain.trim() })}>
                  {t("saas.channels.email.connect")}
                </Button>
              </div>
            </Step>

            <Step n={3} title={t("saas.channels.email.dnsTitle")} state={at(3)}
                  summary={verified ? t("saas.channels.email.dnsDone") : undefined}>
              {st === "awaiting_provider" ? (
                <p className="text-[12.5px] leading-relaxed text-steel">
                  {t("saas.channels.email.awaitingNote")}
                </p>
              ) : (
                <>
                  <p className="text-[12.5px] leading-relaxed text-steel">
                    {t("saas.channels.email.dnsLead")}
                  </p>
                  {(row.email?.dns_records?.length ?? 0) > 0 && (
                    <div className="mt-2 overflow-x-auto rounded-ctl border border-hair">
                      <table className="w-full text-[12.5px]">
                        <thead>
                          <tr className="border-b border-hair bg-surface text-left text-steel">
                            <th className="px-3 py-2 font-medium">{t("saas.channels.email.dns.type")}</th>
                            <th className="px-3 py-2 font-medium">{t("saas.channels.email.dns.name")}</th>
                            <th className="px-3 py-2 font-medium">{t("saas.channels.email.dns.value")}</th>
                            <th className="px-3 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {row.email?.dns_records?.map((r, i) => (
                            <tr key={i} className="border-b border-hair last:border-0">
                              <td className="px-3 py-2 font-mono whitespace-nowrap">
                                {r.type}{r.priority != null ? ` ·${r.priority}` : ""}
                              </td>
                              <td className="max-w-[180px] truncate px-3 py-2 font-mono" title={r.name}>{r.name}</td>
                              <td className="max-w-[220px] truncate px-3 py-2 font-mono" title={r.value}>{r.value}</td>
                              <td className="px-3 py-2 text-right"><CopyButton text={r.value} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <div className="mt-2">
                    <Button variant="brand" size="sm" loading={busy} onClick={() => post("email/verify", {})}>
                      {t("saas.channels.email.check")}
                    </Button>
                  </div>
                </>
              )}
            </Step>

            <Step n={4} title={t("saas.channels.email.fromLabel")} state={at(4)}
                  summary={row.email?.from}>
              <p className="text-[12.5px] leading-relaxed text-steel">
                {t("saas.channels.email.verifiedNote")}
              </p>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <input className={inputCls} placeholder={t("saas.channels.email.senderName")}
                       value={fromName} onChange={(e) => setFromName(e.target.value)} />
                <input className={inputCls} placeholder={`care@${row.email?.domain ?? ""}`}
                       value={fromEmail} onChange={(e) => setFromEmail(e.target.value)} />
                <Button variant="brand" size="sm" loading={busy} disabled={!fromEmail.trim()}
                        onClick={() => post("email/sender", { from_name: fromName.trim(), from_email: fromEmail.trim() })}>
                  {t("saas.channels.email.saveSender")}
                </Button>
              </div>
            </Step>

            {/* Отчёты о доставке: важно, но не на первом экране - прячем в раскрывашку */}
            {own && row.email?.webhook_url && (
              <details className="rounded-ctl border border-hair bg-surface p-3.5">
                <summary className="cursor-pointer list-none text-[13px] font-medium text-ink">
                  {t("saas.channels.email.hook.title")}
                  <span className={"ml-2 text-[11.5px] font-normal " + (row.email.webhook_secret_set ? "text-pos" : "text-steel")}>
                    {row.email.webhook_secret_set
                      ? t("saas.channels.email.hook.okShort")
                      : t("saas.channels.email.hook.missingShort")}
                  </span>
                </summary>
                <p className="mt-2 text-[12.5px] leading-relaxed text-steel">
                  {t("saas.channels.email.hook.desc")}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-ctl border border-hair2 bg-canvas px-[11px] py-[7px] font-mono text-[12px] text-slate">
                    {row.email.webhook_url}
                  </code>
                  <CopyButton text={row.email.webhook_url} />
                </div>
                <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                  <input className={inputCls + " font-mono"} placeholder="whsec_..."
                         value={whSecret} onChange={(e) => setWhSecret(e.target.value)} />
                  <Button variant="brand" size="sm" loading={busy} disabled={!whSecret.trim()}
                          onClick={() => post("email/webhook-secret", { secret: whSecret.trim() })}>
                    {t("saas.ob.stripe.save")}
                  </Button>
                </div>
              </details>
            )}

            {own && (
              <div>
                <Button variant="ghost" size="sm" loading={busy}
                        onClick={() => post("email/key", { api_key: "" })}>
                  {t("saas.channels.email.acct.detach")}
                </Button>
              </div>
            )}
          </div>
        );
      })()}

      {/* ── SMS / Viber: заявка на альфа-имя ── */}
      {(row.channel === "sms" || row.channel === "viber") && (
        <>
          {st === "not_connected" && (
            <div className="flex flex-col gap-2">
              <label className="text-[13px] text-slate">{t("saas.channels.msg.label")}</label>
              <div className="flex gap-2.5">
                <input
                  className={inputCls}
                  placeholder="YourBrand"
                  maxLength={11}
                  value={sender}
                  onChange={(e) => setSender(e.target.value)}
                />
                <Button
                  variant="brand"
                  loading={busy}
                  disabled={!sender.trim()}
                  onClick={() => post("messaging", { [`${row.channel}_sender`]: sender.trim() })}
                >
                  {t("saas.channels.msg.request")}
                </Button>
              </div>
              <p className="text-[12.5px] text-steel">{t("saas.channels.msg.hint")}</p>
            </div>
          )}
          {st === "pending_approval" && (
            <>
              <Field label={t("saas.channels.msg.label")} value={row.detail} />
              <p className="text-[13px] text-steel">{t("saas.channels.msg.pendingNote")}</p>
            </>
          )}
          {st === "awaiting_provider" && (
            <>
              <Field label={t("saas.channels.msg.label")} value={row.detail} />
              <p className="text-[13px] text-steel">{t("saas.channels.msg.awaitingNote")}</p>
            </>
          )}
          {st === "active" && <Field label={t("saas.channels.msg.label")} value={row.detail} />}
        </>
      )}

      {/* ── Telegram: бот клиента ── */}
      {row.channel === "telegram" && (
        <>
          {st === "not_connected" && (
            <div className="flex flex-col gap-2">
              <ol className="flex list-decimal flex-col gap-1 pl-5 text-[13px] text-slate">
                <li>{t("saas.channels.tg.step1")}</li>
                <li>{t("saas.channels.tg.step2")}</li>
                <li>{t("saas.channels.tg.step3")}</li>
              </ol>
              <div className="flex gap-2.5">
                <input
                  className={inputCls + " font-mono"}
                  placeholder="123456789:AAF..."
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
                <Button
                  variant="brand"
                  loading={busy}
                  disabled={!token.trim()}
                  onClick={() => post("telegram", { bot_token: token.trim() })}
                >
                  {t("saas.channels.tg.connect")}
                </Button>
              </div>
            </div>
          )}
          {st === "active" && (
            <>
              <Field label="Bot" value={`@${row.telegram?.bot_username ?? ""}`} />

              {/* Бот подключён - дальше вся работа в том, чтобы юзеры нажали
                  Start по ссылке СО СВОИМ id: без него чат не с кем связать. */}
              <div className="rounded-ctl border border-hair bg-surface p-3.5">
                <div className="text-[13px] font-medium text-ink">{t("saas.channels.tg.subs.title")}</div>
                <p className="mt-1 text-[12.5px] leading-relaxed text-steel">
                  {t("saas.channels.tg.subs.lead")}
                </p>

                <div className="mt-3 text-[12.5px] font-medium text-slate">
                  {t("saas.channels.tg.subs.wayA")}
                </div>
                <p className="mt-1 text-[12.5px] leading-relaxed text-steel">
                  {t("saas.channels.tg.subs.wayAdesc")}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-ctl border border-hair2 bg-canvas px-[11px] py-[7px] font-mono text-[12px] text-slate">
                    {TG_BUTTON}
                  </code>
                  <CopyButton text={TG_BUTTON} />
                </div>

                <div className="mt-3.5 text-[12.5px] font-medium text-slate">
                  {t("saas.channels.tg.subs.wayB")}
                </div>
                <p className="mt-1 text-[12.5px] leading-relaxed text-steel">
                  {t("saas.channels.tg.subs.wayBdesc")}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-ctl border border-hair2 bg-canvas px-[11px] py-[7px] font-mono text-[12px] text-slate">
                    {"{{telegram_connect_url}}"}
                  </code>
                  <CopyButton text="{{telegram_connect_url}}" />
                </div>

                <p className="mt-3.5 text-[12.5px] leading-relaxed text-steel">
                  {t("saas.channels.tg.subs.consent")}
                </p>
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-steel">
                  {t("saas.channels.tg.subs.tip")}
                </p>
                <p className="mt-2.5 text-[12.5px] text-slate">
                  {t("saas.channels.tg.subs.coverage", { n: row.consented })}
                </p>
              </div>

              <div>
                <Button variant="ghost" size="sm" loading={busy} onClick={() => post("telegram", { bot_token: "" })}>
                  {t("saas.channels.tg.disconnect")}
                </Button>
              </div>
            </>
          )}
        </>
      )}

      {/* ── In-app: живёт на сниппете, отдельной настройки нет ── */}
      {row.channel === "inapp" && (
        <p className="text-[13px] text-steel">
          {t(st === "active" ? "saas.channels.inapp.activeNote" : "saas.channels.inapp.setupNote")}
        </p>
      )}

      {/* ── WhatsApp: Cloud API, WABA клиента ── */}
      {row.channel === "whatsapp" && (
        <WhatsappBody
          row={row}
          onSaved={() => {
            void flaskFetch<Payload>("/api/v1/saas/channels")
              .then(refresh)
              .catch(() => {});
          }}
        />
      )}

      {err && <p className="text-[13px] text-neg">{err}</p>}

      <div className="mt-auto border-t border-hair pt-3 text-[12.5px] text-steel">
        {t("saas.channels.reach", { n: row.consented })}
      </div>
    </Card>
  );
}

/**
 * WhatsApp: официальный Cloud API, WABA и номер принадлежат КЛИЕНТУ.
 * Подключение (трек A) делает оператор платформы в Business Manager клиента -
 * форма здесь для него; владелец видит статус, шаблоны и способы сбора
 * подписчиков. Тексты касаний шлются ТОЛЬКО одобренными шаблонами Meta.
 */
function WhatsappBody({ row, onSaved }: { row: ChannelRow; onSaved: () => void }) {
  const t = useT();
  const wa = row.whatsapp;
  const [form, setForm] = useState({ wa_token: "", wa_phone_number_id: "",
    wa_phone_display: "", wa_waba_id: "", wa_app_secret: "" });
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const post = (path: string, body: Record<string, unknown>, done: (d: unknown) => void) => {
    setBusy(true);
    setNote("");
    flaskFetch(path, { method: "POST", body })
      .then((d) => { done(d); onSaved(); })
      .catch((e: unknown) => setNote(e instanceof Error ? e.message : t("saas.channels.err.generic")))
      .finally(() => setBusy(false));
  };

  if (row.state !== "active") {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-[13px] leading-relaxed text-steel">{t("saas.channels.wa.lead")}</p>
        {([["wa_token", true], ["wa_phone_number_id", true], ["wa_phone_display", false],
           ["wa_waba_id", false], ["wa_app_secret", false]] as const).map(([k]) => (
          <input key={k} className={inputCls + " font-mono text-[12.5px]"}
                 placeholder={t(`saas.channels.wa.${k}` as MessageKey)}
                 value={form[k]}
                 onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
        ))}
        <div>
          <Button variant="brand" size="sm" loading={busy}
                  disabled={!form.wa_token.trim() || !form.wa_phone_number_id.trim()}
                  onClick={() => post("/api/v1/saas/channels/whatsapp", { ...form },
                                      () => setNote(""))}>
            {t("saas.channels.wa.connect")}
          </Button>
        </div>
        {note && <p className="text-[12.5px] text-neg">{note}</p>}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* вебхук: адрес и verify token для приложения Meta */}
      {wa?.webhook_url && (
        <div className="rounded-ctl border border-hair bg-surface p-3">
          <div className="text-[12.5px] font-medium text-ink">{t("saas.channels.wa.webhook")}</div>
          <div className="mt-1.5 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-ctl border border-hair2 bg-canvas px-[11px] py-[7px] font-mono text-[12px] text-slate">{wa.webhook_url}</code>
            <CopyButton text={wa.webhook_url} />
          </div>
          {wa.webhook_verify_token && (
            <div className="mt-1.5 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-ctl border border-hair2 bg-canvas px-[11px] py-[7px] font-mono text-[12px] text-slate">{wa.webhook_verify_token}</code>
              <CopyButton text={wa.webhook_verify_token} />
            </div>
          )}
        </div>
      )}

      {/* шаблоны: только APPROVED реально шлётся */}
      <div className="rounded-ctl border border-hair bg-surface p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[12.5px] font-medium text-ink">{t("saas.channels.wa.templates")}</div>
          <Button variant="ghost" size="sm" loading={busy}
                  disabled={!wa?.has_waba}
                  onClick={() => post("/api/v1/saas/channels/whatsapp/templates", {},
                                      () => setNote(t("saas.channels.wa.submitted")))}>
            {t("saas.channels.wa.submit")}
          </Button>
        </div>
        {!wa?.templates?.length && (
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-steel">
            {t(wa?.has_waba ? "saas.channels.wa.noTemplates" : "saas.channels.wa.noWaba")}
          </p>
        )}
        {(wa?.templates ?? []).map((tp) => (
          <div key={tp.name} className="mt-1.5 flex items-center gap-2 text-[12px]">
            <span className={"rounded-full border px-2 py-0.5 text-[10.5px] font-semibold " +
              (tp.status === "APPROVED" ? "border-[#abefc6] bg-[#ecfdf3] text-pos"
                : tp.status === "REJECTED" ? "border-[#fecdca] bg-[#fffbfa] text-neg"
                : "border-[#fedf89] bg-[#fffaeb] text-[#b54708]")}>
              {tp.status || "PENDING"}
            </span>
            <span className="font-mono text-slate">{tp.campaign_id} · {t("saas.camp.step")} {tp.step_idx + 1}</span>
            <span className="text-steel">{tp.category}</span>
            {tp.reason && <span className="text-neg">{tp.reason}</span>}
          </div>
        ))}
      </div>

      {/* сбор подписчиков: человек пишет первым */}
      <div className="rounded-ctl border border-hair bg-surface p-3">
        <div className="text-[12.5px] font-medium text-ink">{t("saas.channels.wa.collect")}</div>
        <p className="mt-1 text-[12.5px] leading-relaxed text-steel">{t("saas.channels.wa.collectDesc")}</p>
        <div className="mt-2 flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-ctl border border-hair2 bg-canvas px-[11px] py-[7px] font-mono text-[12px] text-slate">{"{{whatsapp_connect_url}}"}</code>
          <CopyButton text="{{whatsapp_connect_url}}" />
        </div>
        <div className="mt-1.5 flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-ctl border border-hair2 bg-canvas px-[11px] py-[7px] font-mono text-[12px] text-slate">{'<a data-ra-whatsapp>Get updates on WhatsApp</a>'}</code>
          <CopyButton text='<a data-ra-whatsapp>Get updates on WhatsApp</a>' />
        </div>
      </div>
      {note && <p className="text-[12.5px] text-slate">{note}</p>}
    </div>
  );
}

export function ChannelsView() {
  const t = useT();
  const [data, setData] = useState<Payload | null>(null);
  const [state, setState] = useState<"loading" | "data" | "error" | "no_tenant">("loading");

  const load = useCallback(() => {
    setState("loading");
    flaskFetch<Payload>("/api/v1/saas/channels")
      .then((d) => {
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => setState(isNoTenant(e) ? "no_tenant" : "error"));
  }, []);

  useEffect(load, [load]);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.channels.title")} lead={t("saas.channels.lead")} />

      {state === "loading" && (
        <div className="flex max-w-[860px] flex-col gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-40 animate-pulse rounded-lg border border-hair bg-surface" />
          ))}
        </div>
      )}

      {state === "no_tenant" && <NoTenant />}

      {state === "error" && (
        <Banner>
          {t("saas.channels.err.generic")}{" "}
          <Button variant="ghost" size="sm" onClick={load}>
            {t("common.retry")}
          </Button>
        </Banner>
      )}

      {state === "data" && data && (
        <div className="flex max-w-[860px] flex-col gap-4">
          {[...data.channels]
            .sort((a, b) => CHANNEL_ORDER.indexOf(a.channel) - CHANNEL_ORDER.indexOf(b.channel))
            .map((row) => (
            <ChannelCard
              key={row.channel}
              row={row}
              refresh={(p) => {
                setData(p);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
