"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Card, PageHeader, Spinner, ErrorState } from "@/components/ui";

/**
 * «Запуски» - экран маркетолога (JTBD): что дал каждый день трафика и где
 * люди застревают. Правило №3 в силе: каждый сегмент заканчивается кнопкой
 * «Сделать кампанию» - audience уходит в конструктор КАК ЕСТЬ, поэтому
 * обещанное на этом экране равно зачисленному в кампанию.
 */

interface Cohort { day: string; signups: number; activated: number; paying: number; cash: number }
interface Segment { key: string; count: number; reachable_email: number; audience?: Record<string, unknown> }
interface LaunchesData { cohorts: Cohort[] | null; segments: Segment[] | null }

const usd = (n: number) => "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });

export function LaunchesView({ preset, publicMode }: { preset?: LaunchesData; publicMode?: boolean } = {}) {
  const t = useT();
  const [data, setData] = useState<LaunchesData | null>(preset ?? null);
  const [state, setState] = useState<"loading" | "ok" | "err">(preset ? "ok" : "loading");

  useEffect(() => {
    if (preset) return;
    flaskFetch<LaunchesData>("/api/v1/saas/launches")
      .then((d) => { setData(d); setState("ok"); })
      .catch(() => setState("err"));
  }, [preset]);

  if (state === "loading") return <div className="py-16 flex justify-center"><Spinner /></div>;
  if (state === "err" || !data) return <ErrorState />;

  const cohorts = data.cohorts ?? [];
  const maxSignups = Math.max(...cohorts.map((c) => c.signups), 1);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.launch2.title")} lead={t("saas.launch2.lead")} />

      {/* Где застревают - выше когорт: это то, с чем можно что-то СДЕЛАТЬ */}
      <Card className="p-5">
        <h2 className="text-[15px] font-semibold text-ink">{t("saas.launch2.stuck")}</h2>
        <p className="mt-1 text-[13px] text-steel">{t("saas.launch2.stuckLead")}</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {(data.segments ?? []).map((s) => (
            <div key={s.key} className="flex flex-col rounded-ctl border border-hair bg-surface p-4">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[14px] font-semibold text-ink">
                  {t(`saas.launch2.seg.${s.key}` as MessageKey)}
                </span>
                <span className="text-[22px] font-semibold text-ink tabular-nums">{s.count}</span>
              </div>
              <p className="mt-1 flex-1 text-[12.5px] text-steel">
                {t(`saas.launch2.seg.${s.key}.desc` as MessageKey)}
              </p>
              <div className="mt-3 flex items-center justify-between gap-3">
                <span className="text-[12px] text-steel tabular-nums">
                  {s.reachable_email} {t("saas.launch2.reachable")}
                </span>
                {!publicMode && s.audience ? (
                  <Link
                    href={`/campaigns?preset=${s.key}&audience=${encodeURIComponent(JSON.stringify(s.audience))}`}
                    className={"rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-opacity " +
                      (s.count > 0 ? "bg-primary text-white hover:opacity-90" : "pointer-events-none bg-surface text-steel border border-hair2")}>
                    {t("saas.launch2.makeCampaign")}
                  </Link>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Когорты по дню регистрации */}
      <Card className="p-5">
        <h2 className="text-[15px] font-semibold text-ink">{t("saas.launch2.cohorts")}</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-[13px]" style={{ minWidth: 560 }}>
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-steel">
                <th className="py-2 pr-3 font-medium">{t("saas.launch2.col.day")}</th>
                <th className="py-2 pr-3 font-medium">{t("saas.launch2.col.signups")}</th>
                <th className="py-2 pr-3 font-medium">{t("saas.launch2.col.activated")}</th>
                <th className="py-2 pr-3 font-medium">{t("saas.launch2.col.paying")}</th>
                <th className="py-2 text-right font-medium">{t("saas.launch2.col.cash")}</th>
              </tr>
            </thead>
            <tbody>
              {cohorts.map((c) => (
                <tr key={c.day} className="border-t border-hair">
                  <td className="py-2 pr-3 tabular-nums text-ink">{c.day.slice(5)}</td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <span className="w-8 text-right tabular-nums text-ink">{c.signups}</span>
                      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface">
                        <div className="h-full rounded-full bg-primary"
                             style={{ width: `${(c.signups / maxSignups) * 100}%` }} />
                      </div>
                    </div>
                  </td>
                  <td className="py-2 pr-3 tabular-nums text-ink">
                    {c.activated}
                    <span className="ml-1 text-steel">
                      {c.signups ? `· ${Math.round((c.activated / c.signups) * 100)}%` : ""}
                    </span>
                  </td>
                  <td className="py-2 pr-3 tabular-nums text-ink">{c.paying}</td>
                  <td className={"py-2 text-right tabular-nums font-semibold " + (c.cash > 0 ? "text-pos" : "text-steel")}>
                    {c.cash > 0 ? usd(c.cash) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[12px] text-steel">{t("saas.launch2.cashHint")}</p>
      </Card>
    </div>
  );
}
