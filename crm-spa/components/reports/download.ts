import { createClient } from "@/lib/supabase/client";
import type { ReportSpec } from "./types";

/**
 * Экспорт отчёта в CSV/XLSX (POST /api/v1/reports/export.{fmt} с телом {spec}).
 * Как и у бордовых выгрузок, endpoint требует Supabase Bearer, который простой
 * <a href> не несёт — качаем файл blob-ом и триггерим клиентское скачивание,
 * сохраняя имя из Content-Disposition. Тот же приём, что app/(app)/players/download.ts.
 */
export class ReportDownloadError extends Error {
  constructor(
    public code: "forbidden" | "http_error",
    public status: number,
  ) {
    super(code);
    this.name = "ReportDownloadError";
  }
}

export async function downloadReport(
  fmt: "csv" | "xlsx",
  spec: ReportSpec,
  labels?: Record<string, string>,
): Promise<void> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const base = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;

  const res = await fetch(`${base}/api/v1/reports/export.${fmt}`, {
    method: "POST",
    headers,
    // labels — локализованные заголовки колонок (фронт — источник правды по i18n)
    body: JSON.stringify({ spec, labels }),
  });
  if (!res.ok) {
    throw new ReportDownloadError(res.status === 403 ? "forbidden" : "http_error", res.status);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const name = match?.[1] ?? `report.${fmt}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
