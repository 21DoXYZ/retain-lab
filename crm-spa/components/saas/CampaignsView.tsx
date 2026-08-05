"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Badge, Banner, Button, Card, PageHeader } from "@/components/ui";

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

export function CampaignsView() {
  const t = useT();
  const [data, setData] = useState<Payload | null>(null);
  const [state, setState] = useState<"loading" | "data" | "error">("loading");
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
      .catch(() => setState("error"));
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
                  <li key={i} className="flex gap-3 border-l-2 border-hair pl-4 pb-4 last:pb-0">
                    <span className="mt-0.5 w-9 flex-none font-mono text-[12px] text-steel">
                      {delayLabel(s.delay_h)}
                    </span>
                    <div className="min-w-0">
                      <div className="text-[13px] font-medium text-ink">
                        <span className="mr-2 inline-block rounded-md border border-hair2 bg-surface px-1.5 py-0.5 font-mono text-[11px] text-slate">
                          {s.action === "email" || s.action === "message" ? s.channel || "email" : s.action}
                        </span>
                        {s.subject || (s.offer_id ? `${t("saas.camp.offer")}: ${s.offer_id}` : "")}
                      </div>
                      {s.body && <p className="mt-0.5 text-[12.5px] leading-relaxed text-steel">{s.body}</p>}
                    </div>
                  </li>
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
