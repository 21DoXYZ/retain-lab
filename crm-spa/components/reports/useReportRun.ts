"use client";

import { useCallback, useRef, useState } from "react";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { ReportSpec, RunResult } from "./types";

/**
 * useReportRun — прогон отчёта (POST /api/v1/reports/run) по кнопке «Построить».
 * В отличие от useFlaskData это НЕ авто-fetch по монтированию: run(spec) вызывается
 * императивно. Гонки гасим через nonce-ref (учитывается только последний запрос —
 * важно для «смена порядка разрезов → перезапрос»).
 *
 * Ошибки валидации бэка (422 «несовместимые метрики/разрезы») приходят как
 * FlaskApiError с ТЕКСТОМ БЭКЕНДА (key отсутствует) — flaskErrorText отдаёт его
 * как есть, и экран показывает русский текст 1:1.
 */
export type RunState = "idle" | "loading" | "data" | "error";

export interface UseReportRun {
  state: RunState;
  result: RunResult | null;
  error: string | null;
  /** spec, который дал текущий result (для экспорта и рендера сводной). */
  ranSpec: ReportSpec | null;
  run: (spec: ReportSpec) => Promise<void>;
  reset: () => void;
}

export function useReportRun(): UseReportRun {
  const t = useT();
  const [state, setState] = useState<RunState>("idle");
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ranSpec, setRanSpec] = useState<ReportSpec | null>(null);
  const nonceRef = useRef(0);

  const run = useCallback(
    async (spec: ReportSpec) => {
      const nonce = ++nonceRef.current;
      setState("loading");
      setError(null);
      try {
        const data = await flaskFetch<RunResult>("/api/v1/reports/run", {
          method: "POST",
          body: { spec },
        });
        if (nonce !== nonceRef.current) return; // устаревший ответ — игнорируем
        setResult(data);
        setRanSpec(spec);
        setState("data");
      } catch (e: unknown) {
        if (nonce !== nonceRef.current) return;
        setError(flaskErrorText(e, t, "common.loadFailed"));
        setState("error");
      }
    },
    [t],
  );

  const reset = useCallback(() => {
    nonceRef.current++;
    setState("idle");
    setResult(null);
    setError(null);
    setRanSpec(null);
  }, []);

  return { state, result, error, ranSpec, run, reset };
}
