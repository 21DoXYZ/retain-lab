"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Banner, ErrorState, PageHeader, SCard, SCardGrid } from "@/components/ui";

/**
 * /leak-audit — отчёт «где утекает выручка» (REBUILD §Phase 5) поверх
 * GET /api/v1/saas/leak-audit (api/saas.py, витрины saas_schema.sql).
 * Числа в долларах: SaaS-контур считает MRR в валюте Stripe-планов (usd).
 */

interface LeakBlock {
  count: number;
  mrr?: number;
  potential_mrr?: number;
  expansion_potential?: number;
}

interface LeakAudit {
  tenant: string;
  headline_monthly_leak: number;
  upgrade_estimate_known: boolean;
  blocks: {
    dunning: LeakBlock;
    dead_trials: LeakBlock;
    silent_cancels_30d: LeakBlock;
    under_upgrades: LeakBlock;
  };
}

function usd(n: number | undefined): string {
  return "$" + (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** Ноль людей в блоке - это «нечего показывать», а не «ноль долларов утечки». */
function money(amount: number | undefined, count: number | undefined): string {
  return count ? usd(amount) : "-";
}

export function LeakAuditView() {
  const t = useT();
  const [data, setData] = useState<LeakAudit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    flaskFetch<LeakAudit>("/api/v1/saas/leak-audit")
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.leak.title")} lead={t("saas.leak.lead")} />

      {error ? (
        <ErrorState onRetry={load} />
      ) : (
        <>
          {data ? (
            <Banner>
              <span className="text-[15px] font-semibold">
                {data.headline_monthly_leak > 0
                  ? t("saas.leak.headline", { amount: usd(data.headline_monthly_leak) })
                  : t("saas.leak.noData")}
              </span>
              {data.headline_monthly_leak > 0 && (
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-steel">
                  {t("saas.leak.headlineNote")}
                </p>
              )}
            </Banner>
          ) : null}

          <SCardGrid>
            <SCard
              loading={loading}
              label={t("saas.leak.dunning")}
              value={money(data?.blocks.dunning.mrr, data?.blocks.dunning.count)}
              sub={t("saas.leak.dunningSub", { count: data?.blocks.dunning.count ?? 0 })}
              valueTone="neg"
            />
            <SCard
              loading={loading}
              label={t("saas.leak.silent")}
              value={money(data?.blocks.silent_cancels_30d.mrr, data?.blocks.silent_cancels_30d.count)}
              sub={t("saas.leak.silentSub", { count: data?.blocks.silent_cancels_30d.count ?? 0 })}
              valueTone="neg"
            />
            <SCard
              loading={loading}
              label={t("saas.leak.upgrades")}
              value={money(data?.blocks.under_upgrades.expansion_potential, data?.blocks.under_upgrades.count)}
              sub={t(data?.upgrade_estimate_known
                ? "saas.leak.upgradesSub"
                : "saas.leak.upgradesSubUnknown",
                { count: data?.blocks.under_upgrades.count ?? 0 })}
            />
            <SCard
              loading={loading}
              label={t("saas.leak.deadTrials")}
              value={money(data?.blocks.dead_trials.potential_mrr, data?.blocks.dead_trials.count)}
              sub={t("saas.leak.deadTrialsSub", { count: data?.blocks.dead_trials.count ?? 0 })}
            />
          </SCardGrid>
        </>
      )}
    </div>
  );
}
