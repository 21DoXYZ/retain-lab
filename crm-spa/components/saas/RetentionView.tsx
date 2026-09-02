"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Card, PageHeader, Spinner, ErrorState } from "@/components/ui";

/**
 * «Удержание» (JTBD фаундера): кто уходит, ПОЧЕМУ, и возвращаются ли люди.
 * Каждая строка риска несёт причины и кликается в карточку человека -
 * скор без причины бесполезен.
 */

interface Risk {
  identity_id?: string; email: string; mrr: number; p_churn: number;
  stage: string; reasons: string[];
}
interface Weekly { week: string; cohort: number; d1: number; d7: number; d30: number }
interface Data {
  risk: Risk[] | null;
  weekly: Weekly[] | null;
  saved: { uplift_usd: number; campaigns: number } | null;
}

const usd = (n: number) => "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });

/** Тона причин: возврат/несписание - тревога, остальное - предупреждение. */
const REASON_TONE: Record<string, string> = {
  refund_talk: "border-neg text-neg",
  payment_failed: "border-neg text-neg",
  card_expiring: "border-[#b54708] text-[#b54708]",
  usage_drop: "border-[#b54708] text-[#b54708]",
  gone_quiet: "border-hair2 text-steel",
  friction: "border-[#b54708] text-[#b54708]",
  score_only: "border-hair2 text-steel",
};

function retCell(v: number): string {
  if (v >= 30) return "text-pos font-semibold";
  if (v >= 15) return "text-ink";
  return "text-neg font-semibold";
}

export function RetentionView({ preset, publicMode }: { preset?: Data; publicMode?: boolean } = {}) {
  const t = useT();
  const [data, setData] = useState<Data | null>(preset ?? null);
  const [state, setState] = useState<"loading" | "ok" | "err">(preset ? "ok" : "loading");

  useEffect(() => {
    if (preset) return;
    flaskFetch<Data>("/api/v1/saas/retention")
      .then((d) => { setData(d); setState("ok"); })
      .catch(() => setState("err"));
  }, [preset]);

  if (state === "loading") return <div className="py-16 flex justify-center"><Spinner /></div>;
  if (state === "err" || !data) return <ErrorState />;

  const risk = data.risk ?? [];
  const atStake = risk.reduce((a, r) => a + r.mrr, 0);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.ret.title")} lead={t("saas.ret.lead")} />

      {/* Риск-лист с причинами */}
      <Card className="p-5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-[15px] font-semibold text-ink">{t("saas.ret.risk")}</h2>
          <span className="text-[13px] text-steel tabular-nums">
            {t("saas.ret.atStake")}: <b className="font-semibold text-neg">{usd(atStake)}</b>/{t("saas.ret.mo")}
          </span>
        </div>
        {risk.length ? (
          <div className="mt-3 flex flex-col">
            {risk.map((r, ri) => (
              <Link key={r.identity_id ?? ri}
                href={r.identity_id && !publicMode ? `/users/${encodeURIComponent(r.identity_id)}` : "#"}
                onClick={r.identity_id && !publicMode ? undefined : (e) => e.preventDefault()}
                className="group flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-hair py-2.5 last:border-0">
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink group-hover:text-primary">
                  {r.email}
                </span>
                <span className="flex flex-wrap gap-1.5">
                  {r.reasons.map((k) => (
                    <span key={k}
                      className={"rounded-full border px-2 py-0.5 text-[11px] font-medium " + (REASON_TONE[k] ?? REASON_TONE.score_only)}>
                      {t(`saas.ret.r.${k}` as MessageKey)}
                    </span>
                  ))}
                </span>
                <span className="flex-none text-[13px] text-steel tabular-nums">
                  {r.mrr > 0 ? `${usd(r.mrr)}/${t("saas.ret.mo")} · ` : ""}{Math.round(r.p_churn * 100)}%
                </span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-[13px] text-steel">{t("saas.ret.noRisk")}</p>
        )}
      </Card>

      {/* Недельный возврат */}
      <Card className="p-5">
        <h2 className="text-[15px] font-semibold text-ink">{t("saas.ret.weekly")}</h2>
        <p className="mt-1 text-[13px] text-steel">{t("saas.ret.weeklyLead")}</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-[13px]" style={{ minWidth: 480 }}>
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-steel">
                <th className="py-2 pr-3 font-medium">{t("saas.ret.col.week")}</th>
                <th className="py-2 pr-3 font-medium">{t("saas.ret.col.cohort")}</th>
                <th className="py-2 pr-3 font-medium">{t("saas.ret.col.d1")}</th>
                <th className="py-2 pr-3 font-medium">{t("saas.ret.col.d7")}</th>
                <th className="py-2 font-medium">{t("saas.ret.col.d30")}</th>
              </tr>
            </thead>
            <tbody>
              {(data.weekly ?? []).map((w) => (
                <tr key={w.week} className="border-t border-hair">
                  <td className="py-2 pr-3 tabular-nums text-ink">{w.week.slice(5)}</td>
                  <td className="py-2 pr-3 tabular-nums text-steel">{w.cohort}</td>
                  <td className={"py-2 pr-3 tabular-nums " + retCell(w.d1)}>{w.d1}%</td>
                  <td className={"py-2 pr-3 tabular-nums " + retCell(w.d7)}>{w.d7}%</td>
                  <td className={"py-2 tabular-nums " + retCell(w.d30)}>
                    {/* D30 у свежих когорт ещё не мог случиться - не пугаем нулём */}
                    {Date.now() - new Date(w.week).getTime() < 31 * 86400000 ? "…" : `${w.d30}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Спасено кампаниями */}
      {data.saved && data.saved.uplift_usd > 0 ? (
        <div className="flex items-center gap-3 rounded-card border border-hair2 bg-surface px-5 py-3.5 text-[13px] text-steel">
          <span className="font-semibold text-ink">{t("saas.ret.saved")}</span>
          <span className="font-semibold text-pos tabular-nums">+{usd(data.saved.uplift_usd)}</span>
          <span>{t("saas.ret.savedBy", { n: data.saved.campaigns })}</span>
          <Link href="/campaigns" className="ml-auto font-medium text-primary hover:underline">
            {t("saas.home.act.open")} &rarr;
          </Link>
        </div>
      ) : null}
    </div>
  );
}
