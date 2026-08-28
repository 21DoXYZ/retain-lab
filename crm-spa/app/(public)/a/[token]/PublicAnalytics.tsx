"use client";

import { useEffect, useState } from "react";
import { AnalyticsDashboard, type AnalyticsData } from "@/components/saas/AnalyticsDashboard";
import { Spinner } from "@/components/ui";

/**
 * Клиент публичной ссылки: тянет /api/v1/public/analytics/<token> ПЛОСКИМ fetch
 * (без Authorization - страница анонимная) и рендерит тот же дашборд в
 * publicMode. Бэк уже отдаёт только агрегаты (ни email, ни имён).
 */
const BASE = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";

export function PublicAnalytics({ token }: { token: string }) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [state, setState] = useState<"load" | "ok" | "err">("load");

  useEffect(() => {
    fetch(`${BASE}/api/v1/public/analytics/${encodeURIComponent(token)}`)
      .then((r) => r.json())
      .then((j) => {
        if (j && j.ok && j.data) { setData(j.data as AnalyticsData); setState("ok"); }
        else setState("err");
      })
      .catch(() => setState("err"));
  }, [token]);

  if (state === "load") return <div className="py-24 flex justify-center"><Spinner /></div>;
  if (state === "err" || !data) {
    return (
      <div className="py-24 text-center">
        <div className="text-[20px] font-semibold text-ink mb-1">404</div>
        <div className="text-[13px] text-steel">This link is not available.</div>
      </div>
    );
  }
  return <AnalyticsDashboard data={data} publicMode />;
}
