"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, useLocale } from "@/lib/i18n";

/**
 * useFlaskData — client hook that fetches an analytics endpoint from the Flask
 * JSON backend (via lib/api.flaskFetch) and tracks the three load states the
 * plan requires (loading / error / data). The "empty" state is data-shaped and
 * is decided per screen (e.g. an empty rows[] array), so it is not modelled here.
 *
 *   const { state, data, error, reload } = useFlaskData<LtvResponse>("/api/v1/ltv");
 */
export type LoadState = "loading" | "error" | "data";

export interface FlaskData<T> {
  state: LoadState;
  data: T | null;
  error: string | null;
  reload: () => void;
}

export function useFlaskData<T>(path: string): FlaskData<T> {
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
      .then((d) => {
        if (!alive) return;
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : t("common.loadFailed"));
        setState("error");
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, locale]);

  return { state, data, error, reload };
}
