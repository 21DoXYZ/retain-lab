"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Button, Card, PageHeader } from "@/components/ui";

/**
 * /onboarding — визард «Get started»: 4 шага с живыми статусами и ГОТОВЫМИ
 * артефактами (сниппет уже с токеном - копируй и вставляй, ничего
 * пересоздавать не нужно). GET /api/v1/saas/onboarding.
 */

interface Payload {
  steps: { snippet: boolean; stripe: boolean; channels: boolean; offers: boolean; autopilot: boolean };
  snippet: { token: string; html: string; ingest_url: string };
  stripe: { webhook_url: string; events: string[]; secret_set: boolean };
  channels: { channel: string; state: string }[];
  offers: { offer_id: string; title: string; max_per_user_30d: number; edited: boolean }[];
}

const STEP_ORDER = ["snippet", "stripe", "channels", "offers", "autopilot"] as const;

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

export function OnboardingView() {
  const t = useT();
  const [data, setData] = useState<Payload | null>(null);
  const [state, setState] = useState<"loading" | "data" | "error">("loading");

  const load = useCallback(() => {
    flaskFetch<Payload>("/api/v1/saas/onboarding")
      .then((d) => {
        setData(d);
        setState("data");
      })
      .catch(() => setState("error"));
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
            <pre className="overflow-x-auto rounded-ctl bg-sb p-3.5 font-mono text-[12px] leading-relaxed text-sb-text2 whitespace-pre">
              {data.snippet.html || "-"}
            </pre>
            <div className="flex items-center gap-3">
              <CopyBtn text={data.snippet.html} label={t("saas.ob.copyCode")} copied={t("saas.channels.copied")} />
              <span className="text-[12.5px] text-steel">{t("saas.ob.snippet.identify")}</span>
            </div>
            <p className="text-[12.5px] text-steel">
              {data.steps.snippet ? t("saas.ob.snippet.okNote") : t("saas.ob.snippet.checkNote")}
            </p>
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
            <p className="text-[12.5px] text-steel">
              {data.stripe.secret_set ? t("saas.ob.stripe.secretOk") : t("saas.ob.stripe.secretNote")}
            </p>
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
            <p className="text-[13.5px] leading-relaxed text-slate">{t("saas.ob.offers.desc")}</p>
            <div className="flex flex-col">
              {data.offers.map((o) => (
                <div key={o.offer_id} className="flex items-center justify-between gap-3 border-b border-hair py-1.5 text-[13px] last:border-0">
                  <span className="min-w-0 truncate text-ink">
                    {o.title}
                    {o.edited && (
                      <span className="ml-2 inline-block rounded-full border border-[#b2ddff] bg-[#eff8ff] px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                        {t("saas.camp.edited")}
                      </span>
                    )}
                  </span>
                  <span className="flex-none font-mono text-[12px] text-steel">
                    {t("saas.ob.offers.cap", { n: o.max_per_user_30d })}
                  </span>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <Link href="/offers">
                <Button variant="brand" size="sm">{t("saas.ob.offers.cta")}</Button>
              </Link>
              {!data.steps.offers && (
                <Button
                  variant="ghost" size="sm"
                  onClick={() => {
                    flaskFetch<Payload>("/api/v1/saas/onboarding/offers-reviewed", { method: "POST", body: {} })
                      .then(setData)
                      .catch(() => {});
                  }}
                >
                  {t("saas.ob.offers.review")}
                </Button>
              )}
            </div>
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
