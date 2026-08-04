/**
 * Таймкоды карточки звонка (§10.3). Чистые функции — источник «моста
 * доказательств»: evidence_ts из аудита переводится в секунды, по ним прыгает
 * транскрипт и перематывается плеер. Формат бэкенда: 'mm:ss' | 'hh:mm:ss' и
 * диапазон 'a-b' (зеркалит api/call_analysis.py _ts_to_sec / _ts_range).
 */

/** 'mm:ss' | 'hh:mm:ss' → секунды. null при мусоре. */
export function tsToSec(ts: string | null | undefined): number | null {
  if (ts == null) return null;
  const parts = String(ts).trim().split(":");
  let sec = 0;
  for (const p of parts) {
    const n = Number(p);
    if (!Number.isFinite(n)) return null;
    sec = sec * 60 + n;
  }
  return sec;
}

/** Окно доказательства 'a-b' (или одиночный 'mm:ss') → [lo, hi] секунды. */
export function parseWindow(ts: string | null | undefined): [number, number] | null {
  if (ts == null) return null;
  const raw = String(ts).trim();
  if (raw.includes("-")) {
    const [a, b] = raw.split("-", 2);
    const lo = tsToSec(a);
    const hi = tsToSec(b);
    if (lo == null || hi == null) return null;
    return lo <= hi ? [lo, hi] : [hi, lo];
  }
  const one = tsToSec(raw);
  return one == null ? null : [one, one];
}

/** Первая секунда из массива evidence_ts (для прыжка транскрипта/плеера). */
export function firstEvidenceSec(evidence: readonly string[] | null | undefined): number | null {
  if (!evidence) return null;
  for (const ts of evidence) {
    const w = parseWindow(ts);
    if (w) return w[0];
  }
  return null;
}

/** Секунды → 'm:ss' (или 'h:mm:ss' для длинных). Для баллов/таймкодов — Geist Mono. */
export function formatSec(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return "0:00";
  const total = Math.max(0, Math.floor(sec));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${ss}`;
  return `${m}:${ss}`;
}

/** true, если start слова попадает в любое из окон доказательств. */
export function inAnyWindow(start: number, windows: readonly [number, number][]): boolean {
  for (const [lo, hi] of windows) {
    // одиночный таймкод (lo==hi) — окно ±1.5с, чтобы поймать слово вокруг точки
    const pad = lo === hi ? 1.5 : 0;
    if (start >= lo - pad && start <= hi + pad) return true;
  }
  return false;
}
