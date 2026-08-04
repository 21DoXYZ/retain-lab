/**
 * Number / money / date formatting — 1:1 with the Flask dashboard helpers
 * (player_board.py: f, mn, money2, dlt, date strftime formats).
 *
 * Conventions kept identical to the board:
 *  - thousands separated by a plain ASCII space  → "1 234 567"
 *  - money in TRY: space thousands, comma decimals, ₺ suffix → "88 636,51 ₺"
 *  - millions short form → "1.2 Mn ₺"
 *  - dates rendered in Europe/Istanbul (+3), format dd.mm.yyyy
 */

const DASH = "—";
const TZ = "Europe/Istanbul";

// ---------------------------------------------------------------------------
// Numbers & money
// ---------------------------------------------------------------------------

/** Integer with space-separated thousands (board `f`). Rounds floats. */
export function formatInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return DASH;
  return Math.round(n).toLocaleString("en-US").replace(/,/g, " ");
}

/** Money in TRY panel format: "88 636,51 ₺" (board `money2`). */
export function formatMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return DASH;
  const s = Number(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${s.replace(/,/g, " ").replace(".", ",")} ₺`;
}

/**
 * Адаптивная короткая форма денег (баг Б3, разбор с Василием).
 * Раньше всё делилось на миллион: «0.4 Mn ₺» — 410/440/480 тыс сливались в одно
 * число, а на гео с малым ARPU суммы обнулялись в «0.0 Mn». Теперь масштаб по
 * величине: до 1 млн — тысячи (или полное число для мелких), от 1 млн — миллионы.
 * Суффиксы M/K — языко-нейтральные (форматтер общий для RU/EN/TR; «млн/тыс»
 * зашивать нельзя — турецкий оператор увидел бы русский текст).
 */
export function formatMoneyMn(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return DASH;
  const v = Number(n);
  const abs = Math.abs(v);
  const sp = (x: number) => Math.round(x).toLocaleString("en-US").replace(/,/g, " ");
  if (abs >= 1_000_000) {
    const m = v / 1_000_000;
    // <10 млн — один знак после запятой (1.2M), дальше — целые (12M, 340M)
    return `${Math.abs(m) < 10 ? m.toFixed(1) : sp(m)}M ₺`;
  }
  if (abs >= 10_000) {
    return `${sp(v / 1_000)}K ₺`;   // 440K вместо «0.4 Mn» — различимо
  }
  return formatMoney(v);            // мелкие суммы — полностью, чтобы не терялись в «0»
}

/** Percent with fixed decimals: formatPct(12.34) → "12.3%". */
export function formatPct(
  n: number | null | undefined,
  opts: { digits?: number; sign?: boolean } = {},
): string {
  if (n == null || Number.isNaN(n)) return DASH;
  const { digits = 1, sign = false } = opts;
  const body = n.toFixed(digits);
  return `${sign && n >= 0 ? "+" : ""}${body}%`;
}

export type DeltaTone = "pos" | "neg";
export interface Delta {
  text: string;
  tone: DeltaTone;
}

/**
 * Period-over-period delta (board `dlt`): (cur-prev)/|prev|*100, signed, 1dp.
 * Returns null when there is no comparable previous value.
 */
export function formatDelta(
  cur: number | null | undefined,
  prev: number | null | undefined,
): Delta | null {
  if (cur == null || prev == null || !prev) return null;
  const p = Math.round(((cur - prev) / Math.abs(prev)) * 1000) / 10;
  return { text: `${p >= 0 ? "+" : ""}${p.toFixed(1)}%`, tone: p >= 0 ? "pos" : "neg" };
}

// ---------------------------------------------------------------------------
// Dates (Europe/Istanbul, +3)
// ---------------------------------------------------------------------------

function toDate(value: Date | string | number | null | undefined): Date | null {
  if (value == null || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

interface DateParts {
  day: string;
  month: string;
  year: string;
  hour: string;
  minute: string;
}

function istanbulParts(d: Date): DateParts {
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const map: Record<string, string> = {};
  for (const part of fmt.formatToParts(d)) map[part.type] = part.value;
  return {
    day: map.day ?? "01",
    month: map.month ?? "01",
    year: map.year ?? "1970",
    hour: (map.hour ?? "00") === "24" ? "00" : (map.hour ?? "00"),
    minute: map.minute ?? "00",
  };
}

/** "04.06.2026" (board strftime "%d.%m.%Y"). */
export function formatDate(value: Date | string | number | null | undefined): string {
  const d = toDate(value);
  if (!d) return DASH;
  const p = istanbulParts(d);
  return `${p.day}.${p.month}.${p.year}`;
}

/** "04.06.2026 14:30" (board "%d.%m.%Y %H:%i"). */
export function formatDateTime(value: Date | string | number | null | undefined): string {
  const d = toDate(value);
  if (!d) return DASH;
  const p = istanbulParts(d);
  return `${p.day}.${p.month}.${p.year} ${p.hour}:${p.minute}`;
}

/** "04.06 14:30" (board short "%d.%m %H:%M"). */
export function formatDateShort(value: Date | string | number | null | undefined): string {
  const d = toDate(value);
  if (!d) return DASH;
  const p = istanbulParts(d);
  return `${p.day}.${p.month} ${p.hour}:${p.minute}`;
}
