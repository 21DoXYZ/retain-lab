"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Card } from "@/components/ui";

/**
 * Домашний дашборд владельца. Отвечает РОВНО на четыре вопроса, в порядке
 * важности, и больше ни на что:
 *   1. Сколько денег?            (hero: MRR, утечка, платящие, онлайн)
 *   2. Что требует МЕНЯ?         (очередь решений + деньги под риском, вместе)
 *   3. Что происходит в продукте? (один график 30д + дайджест суток строкой)
 *   4. Что делает машина?        (одна строка автопилота)
 * Всё остальное (воронка, экономика, стадии, гео) живёт в «Аналитике» -
 * дашборд не витрина, а пульт. Один вызов GET /api/v1/saas/home (+ leak-audit).
 *
 * Типографика фиксированной шкалой: 32 (hero) / 22 (числа) / 15 (заголовки
 * секций) / 13 (текст) / 12 (подписи). Один размер кнопок. Без эмодзи-иконок.
 */

interface HomeData extends HomeExtras {
  mrr: number;
  users_total: number;
  stages: Record<string, number>;
  at_risk_now: number;
  dunning_mrr: number;
  pulse?: {
    online_now: number; active_today: number; active_7d: number;
    paying: number; trialing: number; signups_7d: number;
    generations_today: number; generations_7d: number;
  };
  measured?: {
    revenue_usd: number | null; provider_cost_usd: number | null;
    margin_pct: number | null; unit_cost_usd: number | null;
    window_days: number | null;
  } | null;
  campaigns: { active_enrollments: number; holdout: number; touches_7d: number };
  setup: { stripe_connected: boolean; snippet_connected: boolean; channels_connected: boolean; offers_ready: boolean; autopilot: boolean };
}

interface LeakData {
  headline_monthly_leak: number;
}

interface HomeExtras {
  digest?: {
    signups: number; new_paying: number; cancels: number; bug_reports: number;
    tickets: number; creators: number; generations: number; checkouts: number;
  } | null;
  series?: { days: string[]; active: number[]; generations: number[]; signups: number[] } | null;
  funnel?: { steps: number[]; worst_gap: number } | null;
  actions?: { key: string; count: number; href: string }[] | null;
  machine_week?: {
    sent: number; dry_run: number; rejected: number; inapp_shown: number;
    offers_issued: number; offers_rejected: number; uplift_usd: number;
  } | null;
  people?: {
    at_risk: { identity_id: string; email: string; mrr: number; score: number }[];
    hot: { identity_id: string; email: string; mrr: number; score: number }[];
  } | null;
}

/** Площадной график на всю ширину карточки: главный тренд продукта. */
function AreaChart({ data, height = 72 }: { data: number[]; height?: number }) {
  const w = 640, h = height, pad = 3;
  if (!data.length) return null;
  const max = Math.max(...data, 1);
  const x = (i: number) => (i / Math.max(data.length - 1, 1)) * w;
  const y = (v: number) => h - pad - (v / max) * (h - pad * 2);
  const line = data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none" className="block" aria-hidden>
      <polygon points={`0,${h} ${line} ${w},${h}`} className="fill-primary" opacity={0.07} />
      <polyline points={line} fill="none" className="stroke-primary" strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Галочка выполненного шага - рисованная, не эмодзи. */
function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
      <path d="M2.5 6.5L5 9L9.5 3.5" className="stroke-pos" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function usd(n: number | undefined): string {
  return "$" + (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function HomeView() {
  const t = useT();
  const [data, setData] = useState<HomeData | null>(null);
  const [leak, setLeak] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      flaskFetch<HomeData>("/api/v1/saas/home"),
      flaskFetch<LeakData>("/api/v1/saas/leak-audit"),
    ]).then(([h, l]) => {
      if (h.status === "fulfilled") setData(h.value);
      if (l.status === "fulfilled") setLeak(l.value.headline_monthly_leak);
      setLoading(false);
    });
  }, []);

  const golive = [
    { key: "stripe", ok: data?.setup.stripe_connected ?? false, href: "/onboarding" },
    { key: "snippet", ok: data?.setup.snippet_connected ?? false, href: "/onboarding" },
    { key: "channels", ok: data?.setup.channels_connected ?? false, href: "/channel-settings" },
    { key: "offers", ok: data?.setup.offers_ready ?? false, href: "/onboarding" },
    { key: "autopilot", ok: data?.setup.autopilot ?? false, href: "/campaigns" },
  ] as const;
  const goliveDone = golive.filter((s) => s.ok).length;
  const noData = !loading && (data?.users_total ?? 0) === 0;
  const atRisk = data?.people?.at_risk ?? [];
  const hot = data?.people?.hot ?? [];
  const dg = data?.digest;
  const mw = data?.machine_week;

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <div className="h-[120px] rounded-card border border-hair2 bg-surface animate-pulse" />
        <div className="h-[200px] rounded-card border border-hair2 bg-surface animate-pulse" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">

      {/* 1 ── ДЕНЬГИ. Одна карточка, MRR доминирует, остальное подчинено. */}
      <Card className="p-6">
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
          <div>
            <div className="text-[12px] font-medium text-steel">{t("saas.home.kpi.mrr")}</div>
            <div className="mt-1 text-[32px] leading-none font-bold tracking-[-0.5px] text-ink tabular-nums">
              {noData ? "-" : usd(data?.mrr)}
            </div>
          </div>
          <div className="md:pt-[3px]">
            <div className="text-[12px] font-medium text-steel">{t("saas.home.kpi.leak")}</div>
            <div className={"mt-1 text-[22px] leading-none font-semibold tabular-nums " + (noData || !leak ? "text-ink" : "text-neg")}>
              {noData ? "-" : usd(leak ?? 0)}
            </div>
          </div>
          <div className="md:pt-[3px]">
            <div className="text-[12px] font-medium text-steel">{t("saas.home.hero.paying")}</div>
            <div className="mt-1 text-[22px] leading-none font-semibold text-ink tabular-nums">
              {data?.pulse?.paying ?? 0}
              <span className="ml-2 text-[13px] font-normal text-steel">/ {data?.users_total ?? 0}</span>
            </div>
          </div>
          <Link href="/users" className="group md:pt-[3px]">
            <div className="text-[12px] font-medium text-steel">{t("saas.home.pulse.online")}</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="inline-flex items-center gap-2 text-[22px] leading-none font-semibold text-ink tabular-nums group-hover:text-primary transition-colors">
                <span className="h-2 w-2 rounded-full bg-pos animate-pulse" />
                {data?.pulse?.online_now ?? 0}
              </span>
              <span className="text-[13px] text-steel">{t("saas.home.pulse.active7d", { n: data?.pulse?.active_7d ?? 0 })}</span>
            </div>
          </Link>
        </div>
        {noData ? <p className="mt-4 text-[13px] text-steel">{t("saas.home.noData")}</p> : null}
      </Card>

      {/* 2 ── ТРЕБУЕТ ВАС. Решения и деньги под риском - одно место. */}
      {(data?.actions?.length || atRisk.length) ? (
        <Card className="p-5">
          <h2 className="text-[15px] font-semibold text-ink">
            {t("saas.home.act.title", { n: (data?.actions?.length ?? 0) + (atRisk.length ? 1 : 0) })}
          </h2>
          <div className="mt-3 flex flex-col">
            {data?.actions?.map((a) => (
              <Link key={a.key} href={a.href}
                className="group flex items-center justify-between gap-3 border-b border-hair py-2.5 last:border-0">
                <span className="text-[13px] text-ink">
                  {t(`saas.home.act.${a.key}` as MessageKey, { n: a.count })}
                </span>
                <span className="flex-none text-[13px] font-medium text-primary opacity-60 transition-opacity group-hover:opacity-100">
                  {t("saas.home.act.open")} &rarr;
                </span>
              </Link>
            ))}
            {atRisk.slice(0, 3).map((p) => (
              <Link key={p.identity_id} href={`/users/${encodeURIComponent(p.identity_id)}`}
                className="group flex items-center justify-between gap-3 border-b border-hair py-2.5 last:border-0">
                <span className="min-w-0 truncate text-[13px] text-ink">
                  <span className="text-neg font-medium">{t("saas.home.pp.at_risk")}:</span>{" "}
                  {p.email}
                </span>
                <span className="flex-none text-[13px] text-steel tabular-nums">
                  {p.mrr > 0 ? `${usd(p.mrr)} · ` : ""}{Math.round(p.score * 100)}%
                </span>
              </Link>
            ))}
          </div>
        </Card>
      ) : null}

      {/* 3 ── ЖИВОЙ ПРОДУКТ. Один график + сутки одной строкой. */}
      <Card className="p-5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-[15px] font-semibold text-ink">{t("saas.home.pulse.activeToday")}</h2>
          <span className="text-[22px] font-semibold text-ink tabular-nums">{data?.pulse?.active_today ?? 0}</span>
        </div>
        {data?.series ? <div className="mt-3"><AreaChart data={data.series.active} /></div> : null}
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-steel">
          <span>{t("saas.home.pulse.signups7d")}: <b className="font-semibold text-ink tabular-nums">{data?.pulse?.signups_7d ?? 0}</b></span>
          <span>{t("saas.home.pulse.gens")}: <b className="font-semibold text-ink tabular-nums">{data?.pulse?.generations_today ?? 0}</b></span>
          {dg?.new_paying ? <span className="font-medium text-pos">{t("saas.home.dg.paying", { n: dg.new_paying })}</span> : null}
          {dg?.cancels ? <span className="font-medium text-neg">{t("saas.home.dg.cancels", { n: dg.cancels })}</span> : null}
          {dg && (dg.bug_reports || dg.tickets) ? (
            <span className="text-[#b54708]">{t("saas.home.dg.support", { b: dg.bug_reports, tk: dg.tickets })}</span>
          ) : null}
        </div>
        {hot.length ? (
          <div className="mt-3 border-t border-hair pt-3 text-[13px] text-steel">
            <span className="font-medium text-ink">{t("saas.home.pp.hot")}:</span>{" "}
            {hot.slice(0, 3).map((p, i) => (
              <span key={p.identity_id}>
                {i > 0 ? ", " : ""}
                <Link href={`/users/${encodeURIComponent(p.identity_id)}`} className="text-primary hover:underline">
                  {p.email}
                </Link>
              </span>
            ))}
          </div>
        ) : null}
      </Card>

      {/* 4 ── АВТОПИЛОТ. Одна строка о том, что машина делает сама. */}
      {mw ? (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-card border border-hair2 bg-surface px-5 py-3.5 text-[13px] text-steel">
          <span className="font-semibold text-ink">{t("saas.home.machine")}</span>
          <span>{t("saas.home.mw.touches", { n: mw.sent + mw.dry_run })}</span>
          {mw.inapp_shown ? <span>{t("saas.home.mw.inapp", { n: mw.inapp_shown })}</span> : null}
          {mw.uplift_usd > 0 ? (
            <span className="font-semibold text-pos">{t("saas.home.mw.uplift", { a: usd(mw.uplift_usd) })}</span>
          ) : null}
          {mw.sent === 0 && mw.dry_run > 0 ? (
            <span className="text-[#b54708]">{t("saas.home.mw.dryNote")}</span>
          ) : null}
          <Link href="/campaigns" className="ml-auto text-[13px] font-medium text-primary hover:underline">
            {t("saas.home.act.open")} &rarr;
          </Link>
        </div>
      ) : null}

      {/* 5 ── GO-LIVE. Только пока подключение не завершено. */}
      {goliveDone < golive.length ? (
        <Card className="p-5">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-[15px] font-semibold text-ink">{t("saas.home.golive.title")}</h2>
            <span className="text-[13px] text-steel tabular-nums">{goliveDone}/{golive.length}</span>
          </div>
          <ol className="mt-4 flex flex-col gap-3.5">
            {golive.map((s, i) => (
              <li key={s.key} className="flex items-center gap-3.5">
                <span className={"flex h-6 w-6 flex-none items-center justify-center rounded-full border text-[12px] font-semibold " +
                  (s.ok ? "border-pos/30 bg-pos/10" : "border-hair2 bg-surface text-slate")}>
                  {s.ok ? <CheckIcon /> : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <span className={"text-[13px] font-medium " + (s.ok ? "text-steel line-through decoration-hair2" : "text-ink")}>
                    {t(`saas.home.golive.${s.key}.title` as MessageKey)}
                  </span>
                  {!s.ok && (
                    <p className="mt-0.5 text-[12px] text-steel">
                      {t(`saas.home.golive.${s.key}.desc` as MessageKey)}
                    </p>
                  )}
                </div>
                {!s.ok && (
                  <Link href={s.href}
                    className="flex-none rounded-ctl border border-hair2 px-3 py-1.5 text-[13px] font-medium text-slate transition-colors hover:border-primary hover:text-primary">
                    {t("saas.home.golive.open")}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </Card>
      ) : null}
    </div>
  );
}
