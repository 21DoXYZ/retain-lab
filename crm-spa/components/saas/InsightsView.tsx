"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Banner, Button, Card, PageHeader } from "@/components/ui";
import { NoTenant, isNoTenant } from "./NoTenant";

/**
 * /insights — что ИИ-аналитик увидел в результатах недели и что предлагает
 * поменять, плюс причины отмен словами юзеров. Рекомендации применяет владелец
 * кнопкой: GET /api/v1/saas/insights, POST /api/v1/saas/insights/act.
 */

interface Insight {
  insight_id: string;
  campaign_id: string;
  step_idx: number;
  kind: string;
  title: string;
  rationale: string;
  suggestion: Record<string, unknown>;
  status: string;
  period: string;
}

interface ReasonRow {
  category: string;
  count: number;
  mrr: number;
  examples: string[];
}

interface Payload {
  insights: Insight[];
  cancel_reasons: ReasonRow[];
}

/** Виды, которые платформа умеет применить сама (остальное - руками). */
const AUTO_KINDS = new Set(["change_delay", "rewrite_copy", "cut_offer"]);

const KIND_TONE: Record<string, string> = {
  drop_step: "bg-[#fef3f2] text-neg border-[#fecdca]",
  cut_offer: "bg-[#fef3f2] text-neg border-[#fecdca]",
  change_delay: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  rewrite_copy: "bg-[#eff8ff] text-primary border-[#b2ddff]",
  raise_cap: "bg-[#eff8ff] text-primary border-[#b2ddff]",
  scale_up: "bg-[#ecfdf3] text-pos border-[#abefc6]",
  no_action: "bg-surface text-steel border-hair2",
};

export function InsightsView() {
  const t = useT();
  const [data, setData] = useState<Payload | null>(null);
  const [state, setState] = useState<"loading" | "data" | "error" | "no_tenant">("loading");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    flaskFetch<Payload>("/api/v1/saas/insights")
      .then((d) => {
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => setState(isNoTenant(e) ? "no_tenant" : "error"));
  }, []);

  useEffect(load, [load]);

  const act = (id: string, action: "apply" | "dismiss") => {
    setBusy(id);
    flaskFetch("/api/v1/saas/insights/act", { method: "POST", body: { insight_id: id, action } })
      .then(() => load())
      .catch(() => {})
      .finally(() => setBusy(null));
  };

  const totalLost = (data?.cancel_reasons ?? []).reduce((a, r) => a + r.mrr, 0);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("saas.insights.title")}
        lead={t("saas.insights.lead")}
        right={
          <Button variant="ghost" size="sm" onClick={load}>
            {t("saas.ob.refresh")}
          </Button>
        }
      />

      {state === "loading" && (
        <div className="flex flex-col gap-4">
          {[0, 1].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-lg border border-hair bg-surface" />
          ))}
        </div>
      )}

      {state === "data" && data && data.insights.length === 0 && (
        <Banner>{t("saas.insights.empty")}</Banner>
      )}

      {state === "data" &&
        data?.insights.map((i) => (
          <Card key={i.insight_id} className="flex flex-col gap-3 p-5">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[15px] font-semibold text-ink">{i.title}</div>
                <div className="mt-0.5 font-mono text-[11.5px] text-steel">
                  {i.campaign_id}
                  {i.step_idx >= 0 ? ` · шаг ${i.step_idx + 1}` : ""} · {i.period}
                </div>
              </div>
              <span
                className={
                  "inline-block rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold " +
                  (KIND_TONE[i.kind] ?? KIND_TONE.no_action)
                }
              >
                {t(`saas.insights.kind.${i.kind}` as MessageKey)}
              </span>
            </div>

            <p className="text-[13.5px] leading-relaxed text-slate">{i.rationale}</p>

            {i.kind === "rewrite_copy" && typeof i.suggestion.body === "string" && (
              <div className="rounded-ctl border border-hair bg-surface p-3">
                {typeof i.suggestion.subject === "string" && i.suggestion.subject && (
                  <div className="text-[13px] font-medium text-ink">{i.suggestion.subject}</div>
                )}
                <p className="mt-1 text-[12.5px] leading-relaxed text-steel">
                  {i.suggestion.body as string}
                </p>
              </div>
            )}
            {i.kind === "change_delay" && (
              <div className="font-mono text-[12.5px] text-slate">
                {t("saas.camp.f.delay")}: {String(i.suggestion.delay_h)}h
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              {AUTO_KINDS.has(i.kind) ? (
                <Button
                  variant="brand"
                  size="sm"
                  loading={busy === i.insight_id}
                  onClick={() => act(i.insight_id, "apply")}
                >
                  {t("saas.insights.apply")}
                </Button>
              ) : (
                <span className="text-[12.5px] text-steel">{t("saas.insights.manual")}</span>
              )}
              <Button
                variant="ghost"
                size="sm"
                disabled={busy === i.insight_id}
                onClick={() => act(i.insight_id, "dismiss")}
              >
                {t("saas.insights.dismiss")}
              </Button>
            </div>
          </Card>
        ))}

      {state === "data" && (data?.cancel_reasons.length ?? 0) > 0 && (
        <Card className="flex flex-col gap-3 p-5">
          <div className="flex items-baseline justify-between gap-3">
            <div className="text-[15px] font-semibold text-ink">{t("saas.insights.reasons")}</div>
            <span className="font-mono text-[12.5px] text-neg">
              -${totalLost.toLocaleString("en-US", { maximumFractionDigits: 0 })}/mo
            </span>
          </div>
          <div className="flex flex-col">
            {data?.cancel_reasons.map((r) => (
              <div key={r.category} className="border-b border-hair py-2 last:border-0">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[13.5px] font-medium text-ink">
                    {t(`saas.insights.reason.${r.category}` as MessageKey)}
                  </span>
                  <span className="font-mono text-[12.5px] text-steel">
                    {r.count} · ${r.mrr.toFixed(0)}
                  </span>
                </div>
                {r.examples.length > 0 && (
                  <p className="mt-0.5 text-[12px] italic text-steel">
                    {r.examples.slice(0, 2).join(" · ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Card>
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
    </div>
  );
}
