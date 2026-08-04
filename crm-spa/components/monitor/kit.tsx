"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch, FlaskApiError } from "@/lib/api";
import { useLocale, useT, type MessageKey } from "@/lib/i18n";
import type { ReactNode } from "react";
import type { Offer, OfferStatus } from "./types";

/* ---------------------------------------------------------------------------
 * Data fetching
 * -------------------------------------------------------------------------
 * useResource — one-shot fetch with loading/error/data (re-exported from the
 * money kit so monitor screens have a single import path). usePolling adds the
 * /live + /signals-online refresh loop (polling replaces the SSE board, per
 * api/monitor.py: "polling-оверлей вместо SSE").
 * ------------------------------------------------------------------------- */
export { useResource } from "@/components/money/kit";
export type { Resource, ResourceState } from "@/components/money/kit";

export type PollState = "loading" | "error" | "data";

export interface PollResource<T> {
  state: PollState;
  data: T | null;
  error: string | null;
  /** True while a background refresh is in flight (data already shown). */
  refreshing: boolean;
  /** Last successful fetch (client clock, for "обновлено N сек назад"). */
  updatedAt: number | null;
  reload: () => void;
}

/**
 * usePolling — fetch `path` immediately, then every `intervalMs`. On a path
 * change the state resets to loading; a failed poll keeps the previously shown
 * data (transient) and only surfaces the error state on the very first load.
 *
 * `fetchErrorFallback` is the generic error message shown when the failure
 * carries no message and no dictionary key of its own — callers pass it already
 * resolved (it predates FlaskApiError.key and stays for compatibility).
 */
export function usePolling<T>(
  path: string,
  intervalMs: number,
  fetchErrorFallback: string,
): PollResource<T> {
  // Локаль в зависимостях: бэкенд отдаёт локализованный контент (каталог акций)
  // по заголовку X-Locale — при смене языка данные надо перезапросить.
  const { locale } = useLocale();
  const t = useT();
  const [state, setState] = useState<PollState>("loading");
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    setState("loading");
    setData(null);
    setError(null);
    setUpdatedAt(null);

    const tick = (first: boolean) => {
      if (!first) setRefreshing(true);
      flaskFetch<T>(path)
        .then((d) => {
          if (!alive) return;
          setData(d);
          setState("data");
          setError(null);
          setUpdatedAt(Date.now());
        })
        .catch((e: unknown) => {
          if (!alive) return;
          // Наша строка (есть key) → переводим; текст бэкенда/сети → как есть.
          const msg =
            e instanceof FlaskApiError && e.key
              ? t(e.key, e.vars)
              : e instanceof Error
                ? e.message
                : fetchErrorFallback;
          setError(msg);
          // Keep showing prior data on a transient poll failure.
          setState((prev) => (prev === "data" ? "data" : "error"));
        })
        .finally(() => {
          if (alive) setRefreshing(false);
        });
    };

    tick(true);
    const id = setInterval(() => tick(false), intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [path, intervalMs, nonce, locale]);

  return { state, data, error, refreshing, updatedAt, reload };
}

/* ---------------------------------------------------------------------------
 * Formatting helpers (parity with board renderers)
 * ------------------------------------------------------------------------- */
const DASH = "—";

/** Probability 0..1 → "72%" (board round(p*100)); null → «—». */
export function pctRatio(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return `${Math.round(v * 100)}%`;
}

/** Integer amount + " ₺" suffix (board `f(v) ₺`). */
export function tryAmount(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return `${Math.round(v).toLocaleString("en-US").replace(/,/g, " ")} ₺`;
}

/** Pre-resolved (translated) unit suffixes for {@link agoLabel}. */
export interface AgoUnitLabels {
  sec: string;
  min: string;
  h: string;
}

/**
 * Seconds-ago → "12 {sec}" / "3 {min}" / "2 {h}" (board live «N назад»).
 * Plain function, not a component — cannot call useT() itself, so the caller
 * resolves the unit labels via t() and passes them in.
 */
export function agoLabel(seconds: number | null | undefined, units: AgoUnitLabels): string {
  if (seconds == null || Number.isNaN(seconds)) return DASH;
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} ${units.sec}`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} ${units.min}`;
  const h = Math.round(m / 60);
  return `${h} ${units.h}`;
}

/* ---------------------------------------------------------------------------
 * OfferCell — catalog offer name + fine-print terms (board offer_cell), with an
 * optional issued-offer status badge. Data-driven colours stay inline like the
 * board.
 * ------------------------------------------------------------------------- */
/** Статус оффера: код стабилен (player_offers.status), подпись API отдаёт
 *  по-русски → переводим по КОДУ. Незнакомый код → серверная подпись. */
const OFFER_STATUS_KEY: Record<string, MessageKey> = {
  approved: "monitor.offerStatus.approved",
  edited: "monitor.offerStatus.edited",
  rejected: "monitor.offerStatus.rejected",
  sent: "monitor.offerStatus.sent",
};

export function OfferCell({
  offer,
  status,
}: {
  offer: Offer | null | undefined;
  status?: OfferStatus | null;
}) {
  const t = useT();
  if (!offer || !offer.name) return <span className="text-stone">{DASH}</span>;
  const statusKey = status ? OFFER_STATUS_KEY[status.code] : undefined;
  return (
    <div className="text-left leading-tight" title={offer.why || undefined}>
      <span className="font-semibold text-ink">{offer.name}</span>
      {offer.terms ? (
        <span className="block text-[11px] text-stone">{offer.terms}</span>
      ) : null}
      {status ? (
        <span
          className="mt-1 inline-block text-[10.5px] font-semibold rounded-full px-2 py-[2px]"
          style={{ background: status.bg, color: status.fg }}
        >
          {statusKey ? t(statusKey) : status.label}
        </span>
      ) : null}
    </div>
  );
}

/** Small dimmed caption row under a page header / eyebrow. */
export function Note({ children }: { children: ReactNode }) {
  return <p className="mt-8 text-[11.5px] text-stone leading-relaxed">{children}</p>;
}
