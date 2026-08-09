"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Banner, PageHeader } from "@/components/ui";
import { NoTenant, isNoTenant } from "./NoTenant";

/**
 * /pipeline — здоровье конвейера: дирижёр сверху видим владельцу. Последний
 * прогон каждой стадии (сбор->ститч->фичи->скоринг->офферы/кампании->замер) +
 * свежесть. Красный = стадия встала или считает на протухших данных.
 * GET /api/v1/saas/pipeline.
 */

interface Stage {
  stage: string;
  label: string;
  status: string;              // ok | error | timeout | skipped | never
  detail?: string;
  skipped_reason?: string;
  rows?: number;
  duration_s?: number;
  last_run?: string;
  age_min?: number;
  ok_age_min?: number;
  fresh_h?: number;
  fresh: boolean;
}

interface PipelineData {
  stages: Stage[];
  healthy: boolean;
  ran: number;
  total: number;
}

const STATUS_TONE: Record<string, string> = {
  ok: "bg-[#ecfdf3] text-pos border-[#abefc6]",
  error: "bg-[#fef3f2] text-neg border-[#fecdca]",
  timeout: "bg-[#fef3f2] text-neg border-[#fecdca]",
  skipped: "bg-[#fffaeb] text-[#b54708] border-[#fedf89]",
  never: "bg-surface text-steel border-hair2",
};

function ageLabel(min: number | undefined): string {
  if (min == null || min < 0) return "-";
  if (min < 60) return `${min}m`;
  if (min < 1440) return `${Math.round(min / 60)}h`;
  return `${Math.round(min / 1440)}d`;
}

export function PipelineView() {
  const t = useT();
  const [data, setData] = useState<PipelineData | null>(null);
  const [error, setError] = useState("");
  const [noTenant, setNoTenant] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    flaskFetch<PipelineData>("/api/v1/saas/pipeline")
      .then((d) => { setData(d); setError(""); })
      .catch((e: unknown) => {
        setNoTenant(isNoTenant(e));
        setError(flaskErrorText(e, t, "common.loadFailed"));
      })
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 60_000);   // живое здоровье
    return () => window.clearInterval(id);
  }, [load]);

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <div className="h-8 w-64 animate-pulse rounded-ctl bg-surface" />
        <div className="h-64 animate-pulse rounded-ctl bg-surface" />
      </div>
    );
  }
  if (noTenant) return <NoTenant />;
  if (error || !data) return <Banner className="mt-0">{error}</Banner>;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.pipeline.title")} lead={t("saas.pipeline.lead")} />

      <div className={"rounded-ctl border p-4 " + (data.healthy
        ? "border-[#abefc6] bg-[#ecfdf3]" : "border-[#fecdca] bg-[#fef3f2]")}>
        <div className={"text-[14px] font-semibold " + (data.healthy ? "text-pos" : "text-neg")}>
          {data.healthy ? t("saas.pipeline.healthy") : t("saas.pipeline.degraded")}
        </div>
        <div className="mt-0.5 text-[12.5px] text-slate">
          {t("saas.pipeline.ranOf", { ran: String(data.ran), total: String(data.total) })}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {data.stages.map((s, i) => (
          <div key={s.stage}
               className={"flex items-center gap-3 rounded-ctl border bg-surface p-3 "
                 + (s.status !== "never" && !s.fresh ? "border-[#fecdca]" : "border-hair")}>
            <span className="w-5 shrink-0 text-center font-mono text-[11px] text-steel">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium text-ink">
                  {t(`saas.pipeline.stage.${s.label}` as MessageKey)}
                </span>
                <span className={"rounded-full border px-2 py-0.5 text-[10.5px] font-semibold "
                  + (STATUS_TONE[s.status] ?? STATUS_TONE.never)}>
                  {t(`saas.pipeline.status.${s.status}` as MessageKey)}
                </span>
                {s.status !== "never" && !s.fresh ? (
                  <span className="rounded-full border border-[#fecdca] bg-[#fef3f2] px-2 py-0.5 text-[10.5px] font-semibold text-neg">
                    {t("saas.pipeline.stale")}
                  </span>
                ) : null}
              </div>
              {s.skipped_reason ? (
                <div className="mt-0.5 font-mono text-[11px] text-[#b54708]">{s.skipped_reason}</div>
              ) : s.detail ? (
                <div className="mt-0.5 truncate font-mono text-[11px] text-steel" title={s.detail}>{s.detail}</div>
              ) : null}
            </div>
            <div className="shrink-0 text-right text-[11.5px] text-steel">
              {s.status === "never" ? (
                <span>{t("saas.pipeline.notYet")}</span>
              ) : (
                <>
                  <div className="font-mono text-slate">{ageLabel(s.age_min)} {t("saas.pipeline.ago")}</div>
                  {s.rows ? <div className="font-mono">{s.rows.toLocaleString("en-US")}</div> : null}
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
