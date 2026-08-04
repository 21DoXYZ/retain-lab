"use client";

import { useCallback } from "react";
import { useT, type MessageKey } from "./i18n";

/**
 * Перевод дня недели, пришедшего С БЭКЕНДА русской подписью.
 *
 * `_rhythm()` в player_board.py отдаёт `stats.peak_day` как DOW_RU[i]
 * (player_board.py:1189 — `['Пн','Вт','Ср','Чт','Пт','Сб','Вс']`), потому что
 * старый борд одноязычный. Набор фиксированный и стабильный, поэтому это КОД, а
 * не свободный текст: переводим по нему — тот же приём, что для статусов оффера
 * и бейджей действий (подпись API не переводим, переводим по коду).
 *
 * Незнакомое значение возвращаем как есть — не ломаем экран из-за словаря.
 */
const DOW_KEY: Record<string, MessageKey> = {
  "Пн": "analytics.rhythm.dow.mon",
  "Вт": "analytics.rhythm.dow.tue",
  "Ср": "analytics.rhythm.dow.wed",
  "Чт": "analytics.rhythm.dow.thu",
  "Пт": "analytics.rhythm.dow.fri",
  "Сб": "analytics.rhythm.dow.sat",
  "Вс": "analytics.rhythm.dow.sun",
};

/** `dow("Пт")` → «Cum» / «Fri» / «Пт» по текущей локали. */
export function useDow(): (raw: string | null | undefined) => string {
  const t = useT();
  return useCallback(
    (raw: string | null | undefined): string => {
      if (!raw) return "";
      const key = DOW_KEY[raw.trim()];
      return key ? t(key) : raw;
    },
    [t],
  );
}
