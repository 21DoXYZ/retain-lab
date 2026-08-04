"use client";

import { useEffect, useState } from "react";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { RawDefinition } from "./catalog";

/**
 * useSegmentPreview — live "how many players match" counter for the editor.
 *
 * Debounced 500ms on every definition change (plan W4-T2): the caller passes the
 * already-serialized RawDefinition (incomplete rows dropped upstream), we key the
 * effect on its JSON so identical trees don't re-fetch, then POST /segments/preview.
 * A 422 (bad clause) surfaces as `error` text for an inline message — never a toast.
 */
export interface PreviewState {
  loading: boolean;
  count: number | null;
  error: string | null;
}

interface PreviewResponse {
  count: number;
  sample: number[];
}

export function useSegmentPreview(definition: RawDefinition): PreviewState {
  const t = useT();
  // Stable dependency: the tree serialized. Same tree → no refetch.
  const key = JSON.stringify(definition);
  const [state, setState] = useState<PreviewState>({ loading: true, count: null, error: null });

  useEffect(() => {
    let alive = true;

    // The debounce timer fires after the tree settles for 500ms — the loading
    // flag is flipped there (not synchronously in the effect body), so a burst
    // of edits keeps showing the previous count until the user pauses.
    const timer = setTimeout(() => {
      setState((s) => ({ ...s, loading: true, error: null }));
      flaskFetch<PreviewResponse>("/api/v1/segments/preview", {
        method: "POST",
        body: { definition: JSON.parse(key) as RawDefinition },
      })
        .then((d) => {
          if (!alive) return;
          setState({ loading: false, count: d.count, error: null });
        })
        .catch((e: unknown) => {
          if (!alive) return;
          setState({ loading: false, count: null, error: flaskErrorText(e, t, "common.loadFailed") });
        });
    }, 500);

    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
