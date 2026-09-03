"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { Spinner, ErrorState } from "@/components/ui";
import { AnalyticsDashboard, type AnalyticsData } from "./AnalyticsDashboard";

/**
 * Вкладка «Аналитика» в кабинете владельца. Один вызов GET /api/v1/saas/analytics
 * -> весь дашборд (AnalyticsDashboard) + управление внешней ссылкой. Шаринг
 * дергает POST /api/v1/saas/analytics/share и обновляет только блок share.
 */
export function AnalyticsView() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    flaskFetch<AnalyticsData>("/api/v1/saas/analytics")
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  const [shareErr, setShareErr] = useState("");
  const onShare = useCallback(async (action: "enable" | "rotate" | "disable") => {
    setShareErr("");
    try {
      const res = await flaskFetch<{ enabled: boolean; url: string }>(
        "/api/v1/saas/analytics/share", { method: "POST", body: { action } });
      setData((d) => (d ? { ...d, share: res } : d));
    } catch (e) {
      // молча глотать нельзя: владелец жал кнопку и не понимал, что сломано
      setShareErr(e instanceof Error ? e.message : "error");
    }
  }, []);

  if (loading) return <div className="py-16 flex justify-center"><Spinner /></div>;
  if (error || !data) return <ErrorState />;
  return (
    <>
      {shareErr ? (
        <div className="mb-4 rounded-card border border-neg/40 bg-neg/5 px-4 py-2.5 text-[13px] text-neg">
          {shareErr}
        </div>
      ) : null}
      <AnalyticsDashboard data={data} onShare={onShare} />
    </>
  );
}
