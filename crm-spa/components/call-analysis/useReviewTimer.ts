"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Учёт времени на разборе (§7). Секундомер стартует с открытия карточки и
 * сбрасывается при смене звонка. getElapsed() отдаёт целые секунды в момент
 * подтверждения/правки → уходит в review_time_s. Подтверждение быстрее порога
 * бэк в сверку не засчитывает (counted=false), фронт арифметику НЕ решает.
 */
export function useReviewTimer(callId: string): { elapsed: number; getElapsed: () => number } {
  const startRef = useRef<number>(Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    startRef.current = Date.now();
    setElapsed(0);
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [callId]);

  const getElapsed = useCallback(() => Math.floor((Date.now() - startRef.current) / 1000), []);

  return { elapsed, getElapsed };
}

/** "mm:ss" для счётчика времени на разборе. */
export function formatClock(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
