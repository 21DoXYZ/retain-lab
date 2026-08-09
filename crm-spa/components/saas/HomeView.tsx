"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Banner, Card, Icon, SCard, SCardGrid } from "@/components/ui";

/**
 * Домашний дашборд владельца (ответ на «зашёл и ничего не понятно»):
 * 4 цифры -> 3 больших входа -> статус автопилота и подключения.
 * Данные - один вызов GET /api/v1/saas/home (+ leak-audit для headline).
 */

interface HomeData {
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

function usd(n: number | undefined): string {
  return "$" + (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

const STAGE_ORDER = ["ACTIVATE", "CONVERT", "UPGRADE", "SAVE", "DUNNING", "WINBACK", "MONITOR"];

const START_CARDS = [
  { href: "/leak-audit", icon: "leak-audit", title: "saas.home.start.leak.title", desc: "saas.home.start.leak.desc" },
  { href: "/users", icon: "users", title: "saas.home.start.users.title", desc: "saas.home.start.users.desc" },
  { href: "/uplift", icon: "uplift", title: "saas.home.start.uplift.title", desc: "saas.home.start.uplift.desc" },
] as const;

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

  // Go-live чеклист: 4 шага онбординга, статусы из живых данных.
  const golive = [
    { key: "stripe", ok: data?.setup.stripe_connected ?? false, href: "/onboarding" },
    { key: "snippet", ok: data?.setup.snippet_connected ?? false, href: "/onboarding" },
    { key: "channels", ok: data?.setup.channels_connected ?? false, href: "/channel-settings" },
    { key: "offers", ok: data?.setup.offers_ready ?? false, href: "/onboarding" },
    { key: "autopilot", ok: data?.setup.autopilot ?? false, href: "/campaigns" },
  ] as const;
  const goliveDone = golive.filter((s) => s.ok).length;
  // «нет данных» - это не ноль: цифры появятся только после биллинга и сниппета
  const noData = !loading && (data?.users_total ?? 0) === 0;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-extrabold text-[30px] tracking-[-0.6px] text-ink">
          Revenue <span className="text-primary">Autopilot</span>
        </h1>
        <div className="text-steel text-[14.5px] mt-1.5 max-w-[640px]">{t("saas.home.tagline")}</div>
      </div>

      {/* Пока данных нет, $0 читается как «всё хорошо, ничего не течёт» - это
          неправда. Показываем прочерк и говорим, чего не хватает. */}
      <SCardGrid>
        <SCard loading={loading} label={t("saas.home.kpi.mrr")}
               value={noData ? "-" : usd(data?.mrr)} />
        <SCard loading={loading} label={t("saas.home.kpi.leak")}
               value={noData ? "-" : usd(leak ?? 0)} valueTone={noData ? undefined : "neg"} />
        <SCard loading={loading} label={t("saas.home.kpi.users")}
               value={String(data?.users_total ?? 0)} />
        <SCard
          loading={loading}
          label={t("saas.home.kpi.atRisk")}
          value={noData ? "-" : String(data?.at_risk_now ?? 0)}
          sub={t("saas.home.kpi.atRiskSub")}
          valueTone={noData ? undefined : "neg"}
        />
      </SCardGrid>

      {!loading && noData ? (
        <p className="text-[13px] text-steel">{t("saas.home.noData")}</p>
      ) : null}

      {/* Живой пульс: клик по плитке ведёт в /users с уже включённым срезом */}
      {data?.pulse ? (
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[1px] text-primary mb-3">
            {t("saas.home.pulse")}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Link href="/users" className="rounded-card border border-hair2 bg-canvas px-4 py-3.5 transition-colors hover:border-pos">
              <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-steel">
                <span className="h-1.5 w-1.5 rounded-full bg-pos animate-pulse" />
                {t("saas.home.pulse.online")}
              </div>
              <div className="mt-1 font-mono text-[20px] font-semibold text-pos">{data.pulse.online_now}</div>
            </Link>
            <div className="rounded-card border border-hair2 bg-canvas px-4 py-3.5">
              <div className="text-[11px] font-medium uppercase tracking-wide text-steel">{t("saas.home.pulse.activeToday")}</div>
              <div className="mt-1 font-mono text-[20px] font-semibold text-ink">{data.pulse.active_today}</div>
              <div className="text-[11px] text-steel">{t("saas.home.pulse.active7d", { n: data.pulse.active_7d })}</div>
            </div>
            <div className="rounded-card border border-hair2 bg-canvas px-4 py-3.5">
              <div className="text-[11px] font-medium uppercase tracking-wide text-steel">{t("saas.home.pulse.signups7d")}</div>
              <div className="mt-1 font-mono text-[20px] font-semibold text-ink">{data.pulse.signups_7d}</div>
              <div className="text-[11px] text-steel">{t("saas.home.pulse.payTrial", { p: data.pulse.paying, tr: data.pulse.trialing })}</div>
            </div>
            <div className="rounded-card border border-hair2 bg-canvas px-4 py-3.5">
              <div className="text-[11px] font-medium uppercase tracking-wide text-steel">{t("saas.home.pulse.gens")}</div>
              <div className="mt-1 font-mono text-[20px] font-semibold text-ink">{data.pulse.generations_today}</div>
              <div className="text-[11px] text-steel">{t("saas.home.pulse.gens7d", { n: data.pulse.generations_7d })}</div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Измеренная экономика: цифры по факту, не оценки владельца */}
      {data?.measured && data.measured.revenue_usd != null ? (
        <Card className="p-5">
          <div className="flex items-baseline justify-between gap-3 mb-3">
            <div className="text-[15px] font-semibold text-ink">{t("saas.home.measured.title")}</div>
            <span className="font-mono text-[12px] text-steel">
              {t("saas.home.measured.window", { d: data.measured.window_days ?? 90 })}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-steel">{t("saas.home.measured.revenue")}</div>
              <div className="mt-0.5 font-mono text-[17px] font-semibold text-ink">{usd(data.measured.revenue_usd ?? 0)}</div>
            </div>
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-steel">{t("saas.home.measured.cost")}</div>
              <div className="mt-0.5 font-mono text-[17px] font-semibold text-neg">{usd(data.measured.provider_cost_usd ?? 0)}</div>
            </div>
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-steel">{t("saas.home.measured.margin")}</div>
              <div className={"mt-0.5 font-mono text-[17px] font-semibold " + ((data.measured.margin_pct ?? 0) > 30 ? "text-pos" : "text-neg")}>
                {(data.measured.margin_pct ?? 0).toFixed(1)}%
              </div>
            </div>
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-steel">{t("saas.home.measured.unitCost")}</div>
              <div className="mt-0.5 font-mono text-[17px] font-semibold text-ink">
                {data.measured.unit_cost_usd != null ? "$" + data.measured.unit_cost_usd.toFixed(4) : "-"}
              </div>
            </div>
          </div>
          <p className="mt-3 text-[12px] text-steel">{t("saas.home.measured.note")}</p>
        </Card>
      ) : null}

      {!loading && goliveDone < golive.length ? (
        <Card className="p-5">
          <div className="flex items-baseline justify-between gap-3 mb-4">
            <div className="text-[15px] font-semibold text-ink">{t("saas.home.golive.title")}</div>
            <span className="font-mono text-[12.5px] text-steel">{goliveDone}/{golive.length}</span>
          </div>
          <ol className="flex flex-col gap-4">
            {golive.map((s, i) => (
              <li key={s.key} className="flex items-start gap-3.5">
                <span
                  className={
                    "flex h-6 w-6 flex-none items-center justify-center rounded-full border text-[12px] font-semibold " +
                    (s.ok
                      ? "border-[#abefc6] bg-[#ecfdf3] text-pos"
                      : "border-hair2 bg-surface text-slate")
                  }
                >
                  {s.ok ? "✓" : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className={"text-[14px] font-medium " + (s.ok ? "text-steel line-through decoration-hair2" : "text-ink")}>
                    {t(`saas.home.golive.${s.key}.title` as Parameters<typeof t>[0])}
                  </div>
                  {!s.ok && (
                    <p className="mt-0.5 text-[12.5px] text-steel">
                      {t(`saas.home.golive.${s.key}.desc` as Parameters<typeof t>[0])}
                    </p>
                  )}
                </div>
                {!s.ok && (
                  <Link
                    href={s.href}
                    className="flex-none rounded-ctl border border-hair2 px-3 py-1.5 text-[12.5px] font-medium text-slate transition-[color,border-color] duration-150 hover:border-primary hover:text-primary"
                  >
                    {t("saas.home.golive.open")}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </Card>
      ) : null}

      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[1px] text-primary mb-3">
          {t("saas.home.start")}
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {START_CARDS.map((c) => (
            <Link
              key={c.href}
              href={c.href}
              className="bg-canvas border border-hair2 rounded-card px-5 py-5 transition-colors hover:border-primary"
            >
              <div className="mb-3 text-primary">
                <Icon name={c.icon} size={26} />
              </div>
              <div className="text-[15px] font-semibold text-ink">{t(c.title)}</div>
              <div className="text-[12.5px] text-steel mt-1">{t(c.desc)}</div>
            </Link>
          ))}
        </div>
      </div>

      {data ? (
        <Banner>
          <b>{t("saas.home.machine")}:</b>{" "}
          {t("saas.home.machine.body", {
            active: data.campaigns.active_enrollments,
            holdout: data.campaigns.holdout,
            touches: data.campaigns.touches_7d,
          })}
        </Banner>
      ) : null}

      <div className="grid gap-3">
        <Card>
          <div className="text-[12px] font-semibold uppercase tracking-[0.5px] text-steel mb-3">
            {t("saas.uplift.col.campaign")} · stages
          </div>
          <div className="flex flex-wrap gap-2">
            {STAGE_ORDER.map((s) => (
              <span
                key={s}
                className="inline-flex items-center gap-1.5 bg-surface border border-hair2 rounded-full px-3 py-1 text-[12px]"
              >
                <span className="font-semibold text-ink">{t(`saas.stage.${s}` as MessageKey)}</span>
                <span className="text-steel">{data?.stages[s] ?? 0}</span>
              </span>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
