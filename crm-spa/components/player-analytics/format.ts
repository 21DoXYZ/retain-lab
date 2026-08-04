/**
 * Local formatting helpers for the C2 player-analytics sections.
 *
 * Two things lib/format does NOT cover and this module needs:
 *  1. ClickHouse datetimes come back naive (already Europe/Istanbul local, no tz
 *     offset — see api/core.py `_clean` → isoformat()). The board formats them
 *     server-side with strftime WITHOUT re-converting, so we must NOT run them
 *     through lib/format's Istanbul Intl conversion (that would double-shift).
 *     We format straight off the ISO string parts.
 *  2. Small ratio fields (0..1) render trimmed to 3 decimals, exactly like the
 *     board `fld` float branch (`f'{v:.3f}'.rstrip('0').rstrip('.')`).
 */
import { formatInt } from "@/lib/format";

const DASH = "—";

/** "2026-06-04(T14:30:00)" → "04.06.2026" (naive — no tz shift, board strftime %d.%m.%Y). */
export function fmtNaiveDate(value: string | null | undefined): string {
  if (!value) return DASH;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(value);
}

/** "2026-06-04T14:30:00" → "04.06 14:30" (naive, board session log strftime %d.%m %H:%M). */
export function fmtNaiveDateTimeShort(value: string | null | undefined): string {
  if (!value) return DASH;
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(value));
  return m ? `${m[3]}.${m[2]} ${m[4]}:${m[5]}` : fmtNaiveDate(value);
}

/** Money in TRY, plain integer + suffix ("12 345 ₺") — board `fld` cur branch (`f(v)+' ₺'`). */
export function fmtTry(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return DASH;
  return `${formatInt(value)} ₺`;
}

/**
 * Ratio / small-float field — board `fld` float branch: values with |v|<1 show up
 * to 3 trimmed decimals; everything else falls back to a space-thousands integer.
 */
export function fmtRatio(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return DASH;
  const n = Number(value);
  if (n === 0) return "0";
  if (Math.abs(n) < 1) return n.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  return formatInt(n);
}

/**
 * Boolean field → the caller-supplied yes/no label (board fld true→да /
 * false→нет), null → dash. Pure data-layer module (no useT here) — the
 * client caller passes already-translated labels, e.g.
 * `fmtBool(v, t("analytics.common.yes"), t("analytics.common.no"))`.
 */
export function fmtBool(v: boolean | null | undefined, yes: string, no: string): string {
  if (v == null) return DASH;
  return v ? yes : no;
}

/** Percent from a already-scaled value ("44%"), or dash. Board renders `f'{v}%'`. */
export function fmtPctWhole(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return DASH;
  return `${Math.round(Number(value))}%`;
}
