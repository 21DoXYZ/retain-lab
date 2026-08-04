"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";

/**
 * useResource — client data fetch for the affiliates screens with the four
 * required states (loading / error / data). Re-fetches whenever `path` changes
 * (so paginating / re-sorting / re-windowing the detail is a path change).
 * Kept local to the affiliates domain to avoid cross-module coupling.
 */
export type ResourceState = "loading" | "error" | "data";

export interface Resource<T> {
  state: ResourceState;
  data: T | null;
  error: string | null;
  reload: () => void;
}

export function useResource<T>(path: string): Resource<T> {
  const t = useT();
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
        setError(flaskErrorText(e, t, "common.loadFailed"));
        setState("error");
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce]);

  return { state, data, error, reload };
}
