"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch, FlaskApiError, flaskErrorText } from "@/lib/api";
import { useT, useLocale } from "@/lib/i18n";

/**
 * useSection — per-section client fetch for the analytics card. Like money/kit's
 * `useResource`, but also surfaces the HTTP `status` so a section can tell the
 * three "not-here" cases apart from a real failure:
 *   • 403 → role has no access to this player/section → soft "нет доступа"
 *   • 404 → player/section has no data → empty-state
 *   • other → error-state with retry
 * Each section owns its own instance, so they load in parallel and one failing
 * never blocks the others (C2 requirement: independent loading).
 */
export type SectionState = "loading" | "data" | "error";

export interface Section<T> {
  state: SectionState;
  data: T | null;
  error: string | null;
  /** HTTP code of the last error (0 for network), null while ok/loading. */
  status: number | null;
  reload: () => void;
}

export function useSection<T>(path: string, enabled = true): Section<T> {
  const t = useT();
  // Локаль в зависимостях: бэкенд отдаёт локализованный контент (каталог акций)
  // по заголовку X-Locale — при смене языка данные надо перезапросить.
  const { locale } = useLocale();
  const [state, setState] = useState<SectionState>(enabled ? "loading" : "data");
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setState("loading");
    setError(null);
    setStatus(null);
    flaskFetch<T>(path)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setStatus(e instanceof FlaskApiError ? e.status : 0);
        setError(flaskErrorText(e, t, "common.loadFailed"));
        setState("error");
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, enabled, locale]);

  return { state, data, error, status, reload };
}
