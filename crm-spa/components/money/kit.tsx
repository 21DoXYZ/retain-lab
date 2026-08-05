"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { Badge } from "@/components/ui";
import { useT, useLocale } from "@/lib/i18n";
import type { Delta } from "./types";

/* ---------------------------------------------------------------------------
 * useResource — client data fetch with the four required states
 * (loading / empty / error / data). Re-fetches whenever `path` changes.
 * ------------------------------------------------------------------------- */
export type ResourceState = "loading" | "error" | "data";

export interface Resource<T> {
  state: ResourceState;
  data: T | null;
  error: string | null;
  reload: () => void;
}

export function useResource<T>(path: string): Resource<T> {
  const t = useT();
  // Локаль в зависимостях: бэкенд отдаёт локализованный контент (каталог акций)
  // по заголовку X-Locale — при смене языка данные надо перезапросить.
  const { locale } = useLocale();
  const [state, setState] = useState<ResourceState>("loading");
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    setState("loading");
    setError(null);
    flaskFetch<T>(path)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(flaskErrorText(e, t, "money.common.loadFailed"));
        setState("error");
      });
    return () => {
      alive = false;
    };
  }, [path, nonce, t, locale]);

  return { state, data, error, reload };
}

/* ---------------------------------------------------------------------------
 * DeltaBadge — period-over-period delta pill, 1:1 with the board dlt():
 * "+13.4%" green / "-37.4%" red. Renders nothing when there is no comparable
 * previous value (board renders '').
 * ------------------------------------------------------------------------- */
export function DeltaBadge({ delta }: { delta: Delta | null | undefined }) {
  if (!delta) return null;
  // board .badge.pos{bg:#dcfce7;fg:#15803d} / .badge.neg{bg:#fee2e2;fg:#dc2626}
  const c =
    delta.tone === "pos" ? { bg: "#dcfce7", fg: "#15803d" } : { bg: "#fee2e2", fg: "#dc2626" };
  return (
    <Badge bg={c.bg} fg={c.fg} className="ml-1 text-[11px]">
      {delta.pct >= 0 ? "+" : ""}
      {delta.pct.toFixed(1)}%
    </Badge>
  );
}

/* ---------------------------------------------------------------------------
 * MoneySpark — board `spark()` SVG polyline (150×36 viewBox), for SCard footers.
 * ------------------------------------------------------------------------- */
export function MoneySpark({ values, color = "#465fff" }: { values: number[]; color?: string }) {
  const nums = values.map((v) => Number(v) || 0);
  if (nums.length < 2) return null;
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const rng = hi - lo || 1;
  const n = nums.length;
  const pts = nums
    .map((v, i) => `${((i / (n - 1)) * 150).toFixed(1)},${(33 - ((v - lo) / rng) * 30).toFixed(1)}`)
    .join(" ");
  return (
    <svg viewBox="0 0 150 36" preserveAspectRatio="none" className="w-full h-full opacity-90">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}
