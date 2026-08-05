"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Banner, Card, SCard, SCardGrid } from "@/components/ui";

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
  campaigns: { active_enrollments: number; holdout: number; touches_7d: number };
  setup: { stripe_connected: boolean; snippet_connected: boolean };
}

interface LeakData {
  headline_monthly_leak: number;
}

function usd(n: number | undefined): string {
  return "$" + (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

const STAGE_ORDER = ["ACTIVATE", "CONVERT", "UPGRADE", "SAVE", "DUNNING", "WINBACK", "MONITOR"];

const START_CARDS = [
  { href: "/leak-audit", emoji: "💸", title: "saas.home.start.leak.title", desc: "saas.home.start.leak.desc" },
  { href: "/players", emoji: "👥", title: "saas.home.start.users.title", desc: "saas.home.start.users.desc" },
  { href: "/uplift", emoji: "📈", title: "saas.home.start.uplift.title", desc: "saas.home.start.uplift.desc" },
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

  const setup = [
    {
      label: t("saas.home.setup.stripe"),
      ok: data?.setup.stripe_connected ?? false,
      text: data?.setup.stripe_connected
        ? t("saas.home.setup.stripe.on") : t("saas.home.setup.stripe.off"),
    },
    {
      label: t("saas.home.setup.snippet"),
      ok: data?.setup.snippet_connected ?? false,
      text: data?.setup.snippet_connected
        ? t("saas.home.setup.snippet.on") : t("saas.home.setup.snippet.off"),
    },
    { label: t("saas.home.setup.autopilot"), ok: false, text: t("saas.home.setup.autopilot.off") },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-extrabold text-[30px] tracking-[-0.6px] text-ink">
          Revenue <span className="text-primary">Autopilot</span>
        </h1>
        <div className="text-steel text-[14.5px] mt-1.5 max-w-[640px]">{t("saas.home.tagline")}</div>
      </div>

      <SCardGrid>
        <SCard loading={loading} label={t("saas.home.kpi.mrr")} value={usd(data?.mrr)} />
        <SCard loading={loading} label={t("saas.home.kpi.leak")} value={usd(leak ?? 0)} valueTone="neg" />
        <SCard loading={loading} label={t("saas.home.kpi.users")} value={String(data?.users_total ?? 0)} />
        <SCard
          loading={loading}
          label={t("saas.home.kpi.atRisk")}
          value={String(data?.at_risk_now ?? 0)}
          sub={t("saas.home.kpi.atRiskSub")}
          valueTone="neg"
        />
      </SCardGrid>

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
              <div className="text-[26px] leading-none mb-3">{c.emoji}</div>
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

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <div className="text-[12px] font-semibold uppercase tracking-[0.5px] text-steel mb-3">
            {t("saas.home.setup")}
          </div>
          <div className="flex flex-col gap-2.5">
            {setup.map((s) => (
              <div key={s.label} className="flex items-center gap-2.5 text-[13.5px]">
                <span className={"w-2 h-2 rounded-full flex-none " + (s.ok ? "bg-pos" : "bg-stone")} />
                <span className="font-medium text-ink">{s.label}</span>
                <span className="text-steel">- {s.text}</span>
              </div>
            ))}
          </div>
        </Card>
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
                <span className="font-semibold text-ink">{s}</span>
                <span className="text-steel">{data?.stages[s] ?? 0}</span>
              </span>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
