"use client";

import { useEffect, useState } from "react";
import { useLocale } from "@/lib/i18n";
import { AnalyticsDashboard, type AnalyticsData } from "@/components/saas/AnalyticsDashboard";
import { MoneyView } from "@/components/saas/MoneyView";
import { LaunchesView } from "@/components/saas/LaunchesView";
import { RetentionView } from "@/components/saas/RetentionView";
import { Spinner } from "@/components/ui";

/**
 * Публичная ссылка /a/<token> - теперь ПОЛНЫЙ отчёт с вкладками: Обзор /
 * Деньги / Запуски / Удержание. Тянет /api/v1/public/report/<token>/<sec>
 * плоским fetch (страница анонимная); данные приходят уже без PII (email
 * маскированы на сервере, identity наружу не уходят, кнопок действий нет).
 */
const BASE = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";

type Tab = "analytics" | "money" | "launches" | "retention";
const TABS: { key: Tab; ru: string; en: string; tr: string }[] = [
  { key: "analytics", ru: "Обзор", en: "Overview", tr: "Genel bakış" },
  { key: "money", ru: "Деньги", en: "Money", tr: "Para" },
  { key: "launches", ru: "Запуски", en: "Launches", tr: "Lansmanlar" },
  { key: "retention", ru: "Удержание", en: "Retention", tr: "Elde tutma" },
];

export function PublicAnalytics({ token }: { token: string }) {
  const { locale } = useLocale();
  const lc = (["ru", "en", "tr"].includes(locale) ? locale : "en") as "ru" | "en" | "tr";
  const [tab, setTab] = useState<Tab>("analytics");
  // кэш по вкладкам: переключение назад не перезагружает
  const [cache, setCache] = useState<Partial<Record<Tab, unknown>>>({});
  const [state, setState] = useState<"load" | "ok" | "err">("load");

  useEffect(() => {
    if (cache[tab]) { setState("ok"); return; }
    setState("load");
    fetch(`${BASE}/api/v1/public/report/${encodeURIComponent(token)}/${tab}`)
      .then((r) => r.json())
      .then((j) => {
        if (j && j.ok && j.data) {
          setCache((c) => ({ ...c, [tab]: j.data }));
          setState("ok");
        } else setState("err");
      })
      .catch(() => setState("err"));
  }, [token, tab, cache]);

  const data = cache[tab];
  const brand = (cache.analytics as AnalyticsData | undefined)?.brand
    ?? (data as { brand?: { company: string } } | undefined)?.brand;

  if (state === "err" && !data) {
    return (
      <div className="py-24 text-center">
        <div className="text-[20px] font-semibold text-ink mb-1">404</div>
        <div className="text-[13px] text-steel">This link is not available.</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Шапка бренда + вкладки отчёта */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-hair pb-4">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-white text-[15px] font-bold">
            {(brand?.company ?? "R").slice(0, 1).toUpperCase()}
          </span>
          <span className="text-[18px] font-semibold text-ink">{brand?.company ?? ""}</span>
        </div>
        <nav className="flex gap-1.5">
          {TABS.map((tb) => (
            <button key={tb.key} onClick={() => setTab(tb.key)}
              className={"rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-colors " +
                (tab === tb.key
                  ? "bg-primary text-white"
                  : "border border-hair2 bg-canvas text-slate hover:border-primary")}>
              {tb[lc]}
            </button>
          ))}
        </nav>
      </div>

      {!data ? (
        <div className="py-24 flex justify-center"><Spinner /></div>
      ) : tab === "analytics" ? (
        <AnalyticsDashboard data={data as AnalyticsData} />
      ) : tab === "money" ? (
        <MoneyView preset={data as never} publicMode />
      ) : tab === "launches" ? (
        <LaunchesView preset={data as never} publicMode />
      ) : (
        <RetentionView preset={data as never} publicMode />
      )}

      <div className="mt-2 flex items-center justify-between border-t border-hair pt-4 text-[11px] text-steel">
        <span>{brand?.company ?? ""}</span>
        <span>Powered by Revenue Autopilot · retivo.digital</span>
      </div>
    </div>
  );
}
