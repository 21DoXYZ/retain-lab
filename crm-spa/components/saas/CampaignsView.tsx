"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Badge, Banner, Button, Card, PageHeader } from "@/components/ui";
import { NoTenant, isNoTenant } from "./NoTenant";

/**
 * /campaigns — SaaS-кампании K1-K5: что именно автопилот шлёт юзерам (шаги,
 * тексты, каналы, цель) + статистика прохождения + рубильник автопилота.
 * GET /api/v1/saas/campaigns, POST /api/v1/saas/campaigns/autopilot.
 */

interface Step {
  delay_h: number;
  action: string;
  channel: string;
  subject: string;
  body: string;
  offer_id: string;
  cta_label: string;
  cta_url: string;
  edited: boolean;
}

interface Campaign {
  campaign_id: string;
  title: string;
  entry_stage: string;
  goal: { event_type?: string; window_days?: number };
  steps: Step[];
  stats: { enrolled: number; active: number; holdout: number; done: number; exited: number; touches: number };
}

interface Payload {
  autopilot: boolean;
  platform_dry_run: boolean;
  control_pct: number;
  campaigns: Campaign[];
}

const STAGE_TONE: Record<string, string> = {
  DUNNING: "bg-[#fef3f2] text-neg border-[#fecdca]",
  WINBACK: "bg-[#fef3f2] text-neg border-[#fecdca]",
  CONVERT: "bg-[#eff8ff] text-primary border-[#b2ddff]",
  SAVE: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  UPGRADE: "bg-[#ecfdf3] text-pos border-[#abefc6]",
  ACTIVATE: "bg-[#eff8ff] text-primary border-[#b2ddff]",
};

function delayLabel(h: number): string {
  if (h === 0) return "0h";
  if (h % 24 === 0) return `${h / 24}d`;
  return `${h}h`;
}

const inputCls =
  "h-[38px] w-full rounded-ctl border border-hair2 bg-canvas px-3 text-[13px] " +
  "text-ink outline-none transition-[border-color] duration-150 focus:border-primary";

function StepRow({
  campaignId,
  index,
  step,
  refresh,
}: {
  campaignId: string;
  index: number;
  step: Step;
  refresh: (p: Payload) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [subject, setSubject] = useState(step.subject);
  const [body, setBody] = useState(step.body);
  const [ctaLabel, setCtaLabel] = useState(step.cta_label);
  const [ctaUrl, setCtaUrl] = useState(step.cta_url);
  const [delay, setDelay] = useState(String(step.delay_h));

  const isOffer = step.action === "offer";
  const isInapp = step.action === "inapp";

  const post = (payload: Record<string, unknown>) => {
    setBusy(true);
    setErr("");
    flaskFetch<Payload>("/api/v1/saas/campaigns/step", {
      method: "POST",
      body: { campaign_id: campaignId, step_idx: index, ...payload },
    })
      .then((p) => {
        refresh(p);
        setEditing(false);
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : t("saas.channels.err.generic")))
      .finally(() => setBusy(false));
  };

  return (
    <li className="flex gap-3 border-l-2 border-hair pl-4 pb-4 last:pb-0">
      <span className="mt-0.5 w-9 flex-none font-mono text-[12px] text-steel">
        {delayLabel(step.delay_h)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="text-[13px] font-medium text-ink">
            <span className="mr-2 inline-block rounded-md border border-hair2 bg-surface px-1.5 py-0.5 font-mono text-[11px] text-slate">
              {step.action === "email" || step.action === "message" ? step.channel || "email" : step.action}
            </span>
            {step.subject || (step.offer_id ? `${t("saas.camp.offer")}: ${step.offer_id}` : "")}
            {step.edited && (
              <span className="ml-2 inline-block rounded-full border border-[#b2ddff] bg-[#eff8ff] px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                {t("saas.camp.edited")}
              </span>
            )}
          </div>
          {!editing && (
            <button
              type="button"
              className="flex-none cursor-pointer rounded-md border border-hair2 px-2 py-0.5 text-[11.5px] text-steel transition-[color,border-color] duration-150 hover:border-primary hover:text-primary"
              onClick={() => {
                setSubject(step.subject);
                setBody(step.body);
                setCtaLabel(step.cta_label);
                setCtaUrl(step.cta_url);
                setDelay(String(step.delay_h));
                setEditing(true);
              }}
            >
              {t("saas.camp.edit")}
            </button>
          )}
        </div>

        {!editing && step.body && (
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-steel">{step.body}</p>
        )}

        {editing && (
          <div className="mt-2 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <label className="w-20 flex-none text-[12px] text-steel">{t("saas.camp.f.delay")}</label>
              <input className={inputCls + " max-w-[110px]"} value={delay}
                     onChange={(e) => setDelay(e.target.value)} inputMode="decimal" />
              <span className="text-[12px] text-steel">{t("saas.camp.f.hours")}</span>
            </div>
            {!isOffer && (
              <>
                <input className={inputCls} placeholder={t("saas.camp.f.subject")}
                       value={subject} onChange={(e) => setSubject(e.target.value)} />
                <textarea
                  className="min-h-[84px] w-full rounded-ctl border border-hair2 bg-canvas p-3 text-[13px] leading-relaxed text-ink outline-none transition-[border-color] duration-150 focus:border-primary"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                />
                <p className="text-[11.5px] text-steel">{t("saas.camp.f.placeholders")}</p>
              </>
            )}
            {isInapp && (
              <div className="flex flex-col gap-2 sm:flex-row">
                <input className={inputCls} placeholder={t("saas.camp.f.ctaLabel")}
                       value={ctaLabel} onChange={(e) => setCtaLabel(e.target.value)} />
                <input className={inputCls} placeholder={t("saas.camp.f.ctaUrl")}
                       value={ctaUrl} onChange={(e) => setCtaUrl(e.target.value)} />
              </div>
            )}
            {err && <p className="text-[12px] text-neg">{err}</p>}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="brand" size="sm" loading={busy}
                onClick={() => {
                  const payload: Record<string, unknown> = { delay_h: Number(delay) };
                  if (!isOffer) {
                    payload.subject = subject;
                    payload.body = body;
                  }
                  if (isInapp) {
                    payload.cta_label = ctaLabel;
                    payload.cta_url = ctaUrl;
                  }
                  post(payload);
                }}
              >
                {t("saas.camp.save")}
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => setEditing(false)}>
                {t("saas.camp.cancel")}
              </Button>
              {step.edited && (
                <Button variant="ghost" size="sm" loading={busy} onClick={() => post({ reset: true })}>
                  {t("saas.camp.resetDefault")}
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </li>
  );
}

export function CampaignsView() {
  const t = useT();
  const [data, setData] = useState<Payload | null>(null);
  const [state, setState] = useState<"loading" | "data" | "error" | "no_tenant">("loading");
  const [busy, setBusy] = useState(false);
  const [arm, setArm] = useState(false);
  const armTimer = useRef<number | undefined>(undefined);

  const load = useCallback(() => {
    setState("loading");
    flaskFetch<Payload>("/api/v1/saas/campaigns")
      .then((d) => {
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => setState(isNoTenant(e) ? "no_tenant" : "error"));
  }, []);

  useEffect(load, [load]);
  useEffect(() => () => window.clearTimeout(armTimer.current), []);

  const toggle = () => {
    if (!data) return;
    if (!data.autopilot && !arm) {
      setArm(true);
      armTimer.current = window.setTimeout(() => setArm(false), 4000);
      return;
    }
    window.clearTimeout(armTimer.current);
    setArm(false);
    setBusy(true);
    flaskFetch<Payload>("/api/v1/saas/campaigns/autopilot", {
      method: "POST",
      body: { enabled: !data.autopilot },
    })
      .then(setData)
      .catch(() => {})
      .finally(() => setBusy(false));
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.camp.title")} lead={t("saas.camp.lead")} />

      {state === "loading" && (
        <div className="flex flex-col gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-36 animate-pulse rounded-lg border border-hair bg-surface" />
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
        <>
          <Card className="p-5">
            <div className="mb-3 text-[15px] font-semibold text-ink">{t("saas.camp.how.title")}</div>
            <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-[13.5px] leading-relaxed text-slate">
              <li>{t("saas.camp.how.1")}</li>
              <li>{t("saas.camp.how.2", { pct: data.control_pct })}</li>
              <li>{t("saas.camp.how.3")}</li>
              <li>{t("saas.camp.how.4")}</li>
            </ol>
            <div className="mt-4 mb-2 text-[12px] font-semibold uppercase tracking-[0.5px] text-steel">
              {t("saas.camp.rules.title")}
            </div>
            <div className="flex flex-col">
              {(["DUNNING", "WINBACK", "CONVERT", "SAVE", "UPGRADE", "ACTIVATE", "MONITOR"] as const).map((st) => (
                <div key={st} className="flex items-start gap-3 border-b border-hair py-2 last:border-0">
                  <span
                    className={
                      "mt-0.5 inline-block w-[86px] flex-none rounded-full border px-2 py-0.5 text-center text-[10.5px] font-semibold " +
                      (STAGE_TONE[st] ?? "bg-surface text-steel border-hair2")
                    }
                  >
                    {st}
                  </span>
                  <span className="text-[13px] leading-relaxed text-slate">
                    {t(`saas.camp.rule.${st}`)}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          <Card className="flex flex-wrap items-center justify-between gap-3 p-5">
            <div className="min-w-0">
              <div className="text-[15px] font-semibold text-ink">{t("saas.camp.autopilot")}</div>
              <p className="text-[13px] text-steel">
                {data.autopilot ? t("saas.camp.autopilot.onDesc") : t("saas.camp.autopilot.offDesc", { pct: data.control_pct })}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span
                className={
                  "inline-block rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold " +
                  (data.autopilot
                    ? "bg-[#ecfdf3] text-pos border-[#abefc6]"
                    : "bg-surface text-steel border-hair2")
                }
              >
                {data.autopilot ? t("saas.camp.autopilot.on") : t("saas.camp.autopilot.off")}
              </span>
              <Button
                variant={data.autopilot ? "ghost" : arm ? "primary" : "brand"}
                size="sm"
                loading={busy}
                onClick={toggle}
              >
                {data.autopilot
                  ? t("saas.camp.autopilot.disable")
                  : arm
                    ? t("saas.camp.autopilot.confirm")
                    : t("saas.camp.autopilot.enable")}
              </Button>
            </div>
          </Card>

          {data.autopilot && data.platform_dry_run && (
            <Banner>{t("saas.camp.platformDry")}</Banner>
          )}

          {data.campaigns.map((c) => (
            <Card key={c.campaign_id} className="flex flex-col gap-4 p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold text-ink">{c.title}</div>
                  <div className="font-mono text-[12px] text-steel">{c.campaign_id}</div>
                </div>
                <span
                  className={
                    "inline-block rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold " +
                    (STAGE_TONE[c.entry_stage] ?? "bg-surface text-steel border-hair2")
                  }
                >
                  {c.entry_stage}
                </span>
              </div>

              <ol className="flex flex-col">
                {c.steps.map((s, i) => (
                  <StepRow
                    key={`${c.campaign_id}:${i}:${s.edited ? "e" : "b"}`}
                    campaignId={c.campaign_id}
                    index={i}
                    step={s}
                    refresh={setData}
                  />
                ))}
              </ol>

              <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-hair pt-3 text-[12.5px] text-steel">
                {c.goal.event_type && (
                  <span>
                    {t("saas.camp.goal")}: <span className="font-mono text-ink">{c.goal.event_type}</span>
                    {c.goal.window_days ? ` / ${c.goal.window_days}d` : ""}
                  </span>
                )}
                <span>
                  {t("saas.camp.enrolled")}: <span className="font-mono text-ink">{c.stats.enrolled}</span>
                </span>
                <span>
                  {t("saas.camp.active")}: <span className="font-mono text-ink">{c.stats.active}</span>
                </span>
                <span>
                  {t("saas.camp.holdout")}: <span className="font-mono text-ink">{c.stats.holdout}</span>
                </span>
                <span>
                  {t("saas.camp.touches")}: <span className="font-mono text-ink">{c.stats.touches}</span>
                </span>
              </div>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}
