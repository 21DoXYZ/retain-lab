"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT, useLocale } from "@/lib/i18n";

export type LoadState = "loading" | "error" | "empty" | "data";

interface Result<T> {
  state: LoadState;
  data: T | null;
  error: string | null;
  reload: () => void;
}

/**
 * Client hook that loads one segmentation endpoint through the shared
 * flaskFetch (B1) — Supabase JWT attached, `{ ok, data }` envelope unwrapped.
 * Surfaces the four required screen states (plan §0.6): loading / error /
 * empty / data. `isEmpty` lets each screen decide what "no data" means.
 */
export function useSegmentationData<T>(
  path: string,
  isEmpty: (data: T) => boolean = () => false,
): Result<T> {
  const t = useT();
  // Локаль в зависимостях: бэкенд отдаёт локализованный контент (каталог акций)
  // по заголовку X-Locale — при смене языка данные надо перезапросить.
  const { locale } = useLocale();
  const [state, setState] = useState<LoadState>("loading");
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    setState("loading");
    setError(null);

    flaskFetch<T>(path)
      .then((res) => {
        if (!alive) return;
        setData(res);
        setState(isEmpty(res) ? "empty" : "data");
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(flaskErrorText(err, t, "common.loadFailed"));
        setState("error");
      });

    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, locale]);

  return { state, data, error, reload };
}
