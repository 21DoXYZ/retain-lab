"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT, useLocale } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";

/* ---------------------------------------------------------------------------
 * useCallResource — client fetch with loading / error / data states, re-fetches
 * on path change or locale change (backend content follows X-Locale). Mirrors
 * components/money/kit.useResource but with the callsboard fallback copy.
 * ------------------------------------------------------------------------- */
export type ResourceState = "loading" | "error" | "data";

export interface Resource<T> {
  state: ResourceState;
  data: T | null;
  error: string | null;
  reload: () => void;
}

export function useCallResource<T>(path: string): Resource<T> {
  const t = useT();
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
        setError(flaskErrorText(e, t, "callsboard.common.loadFailed"));
        setState("error");
      });
    return () => {
      alive = false;
    };
  }, [path, nonce, t, locale]);

  return { state, data, error, reload };
}

/* ---------------------------------------------------------------------------
 * Canonical code lists (single-sourced with api/call_analysis.py & §8/§11).
 * ------------------------------------------------------------------------- */
export const CRITERIA = [
  "open_identify",
  "rapport",
  "discovery",
  "offer_presented",
  "offer_value",
  "objection_handling",
  "alt_offer",
  "next_step",
  "tone",
] as const;

export const CHECK_LEVELS = ["verbatim", "meaning", "none"] as const;
export const IMPORTANCE = ["critical", "normal", "minor"] as const;

/* ---------------------------------------------------------------------------
 * Code → MessageKey maps (typed so every referenced key must exist in the ru
 * base dictionary). Label hooks translate a backend code; unknown codes fall
 * back to the raw string rather than an i18n miss.
 * ------------------------------------------------------------------------- */
const CRITERION_KEY: Record<string, MessageKey> = {
  open_identify: "callsboard.criterion.open_identify",
  rapport: "callsboard.criterion.rapport",
  discovery: "callsboard.criterion.discovery",
  offer_presented: "callsboard.criterion.offer_presented",
  offer_value: "callsboard.criterion.offer_value",
  objection_handling: "callsboard.criterion.objection_handling",
  alt_offer: "callsboard.criterion.alt_offer",
  next_step: "callsboard.criterion.next_step",
  tone: "callsboard.criterion.tone",
};

const OBJECTION_KEY: Record<string, MessageKey> = {
  no_money: "callsboard.objection.no_money",
  no_time: "callsboard.objection.no_time",
  lost_before: "callsboard.objection.lost_before",
  distrust: "callsboard.objection.distrust",
  other: "callsboard.objection.other",
};

const OUTCOME_KEY: Record<string, MessageKey> = {
  accepted: "callsboard.outcome.accepted",
  refused: "callsboard.outcome.refused",
  countered: "callsboard.outcome.countered",
  no_offer: "callsboard.outcome.no_offer",
  unclear: "callsboard.outcome.unclear",
};

const CHECK_KEY: Record<string, MessageKey> = {
  verbatim: "callsboard.check.verbatim",
  meaning: "callsboard.check.meaning",
  none: "callsboard.check.none",
};

const IMPORTANCE_KEY: Record<string, MessageKey> = {
  critical: "callsboard.importance.critical",
  normal: "callsboard.importance.normal",
  minor: "callsboard.importance.minor",
};

type LabelFn = (code: string | null | undefined) => string;

function useCodeLabel(map: Record<string, MessageKey>): LabelFn {
  const t = useT();
  return (code) => {
    if (!code) return "—";
    const key = map[code];
    return key ? t(key) : code;
  };
}

export const useCriterionLabel = (): LabelFn => useCodeLabel(CRITERION_KEY);
export const useObjectionLabel = (): LabelFn => useCodeLabel(OBJECTION_KEY);
export const useOutcomeLabel = (): LabelFn => useCodeLabel(OUTCOME_KEY);
export const useCheckLabel = (): LabelFn => useCodeLabel(CHECK_KEY);
export const useImportanceLabel = (): LabelFn => useCodeLabel(IMPORTANCE_KEY);

/* ---------------------------------------------------------------------------
 * Formatters.
 * ------------------------------------------------------------------------- */

/** Seconds → "m:ss" (durations, timecodes). Board uses Geist Mono for these. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

/** Fraction 0..1 → "78%". Null → dash. */
export function formatFraction(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

/* ---------------------------------------------------------------------------
 * TrendCell — signed period-over-period delta with arrow + colour (§10.1).
 * Status is never colour-only: the arrow glyph carries direction too (§13 a11y).
 * ------------------------------------------------------------------------- */
export function TrendCell({
  value,
  suffix,
}: {
  value: number | null | undefined;
  suffix?: string;
}) {
  if (value == null || Number.isNaN(value)) {
    return <span className="font-mono text-stone">—</span>;
  }
  const rounded = Math.round(value);
  if (rounded === 0) {
    return <span className="font-mono text-steel">→ 0{suffix ?? ""}</span>;
  }
  const up = rounded > 0;
  return (
    <span className={cnTone(up)}>
      {up ? "↑ +" : "↓ −"}
      {Math.abs(rounded)}
      {suffix ?? ""}
    </span>
  );
}

function cnTone(up: boolean): string {
  return `font-mono font-medium ${up ? "text-pos" : "text-neg"}`;
}
