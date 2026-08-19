"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Button, Card } from "@/components/ui";

/**
 * Предполётный чеклист запуска: автопроверки (подписи, тексты, привязки,
 * домен) + ручные подтверждения владельца (ящик ответов, DMARC, тест-письмо).
 * GET /saas/launch-check, POST /saas/launch-check/confirm.
 */

interface Check {
  key: string;
  status: "pass" | "warn" | "fail" | "manual";
  detail: string;
}

interface Payload {
  checks: Check[];
  verdict: "ready" | "almost" | "not_ready";
  autopilot: boolean;
}

const TONE: Record<Check["status"], string> = {
  pass: "border-[#abefc6] bg-[#ecfdf3] text-pos",
  warn: "border-[#fedf89] bg-[#fffaeb] text-[#b54708]",
  fail: "border-[#fecdca] bg-[#fef3f2] text-neg",
  manual: "border-hair2 bg-surface text-steel",
};

const ICON: Record<Check["status"], string> = {
  pass: "✓", warn: "!", fail: "✕", manual: "?",
};

export function LaunchCheck() {
  const t = useT();
  const [data, setData] = useState<Payload | null>(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    flaskFetch<Payload>("/api/v1/saas/launch-check")
      .then(setData)
      .catch(() => setData(null));
  }, []);
  useEffect(load, [load]);

  if (!data || data.autopilot) return null;   // после запуска чеклист уходит

  const confirm = (key: string) => {
    setBusy(key);
    flaskFetch("/api/v1/saas/launch-check/confirm", {
      method: "POST", body: { key, ok: true },
    }).then(load).catch(() => {}).finally(() => setBusy(""));
  };

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[15px] font-semibold text-ink">{t("saas.launch.title")}</div>
        <span className={"rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold " + TONE[
          data.verdict === "ready" ? "pass" : data.verdict === "almost" ? "warn" : "fail"]}>
          {t(`saas.launch.verdict.${data.verdict}` as MessageKey)}
        </span>
      </div>
      <p className="mt-1 max-w-[720px] text-[12.5px] leading-relaxed text-steel">
        {t("saas.launch.lead")}
      </p>
      <div className="mt-3 flex flex-col gap-1.5">
        {data.checks.map((c) => (
          <div key={c.key} className="flex items-center gap-2.5">
            <span className={"flex h-5 w-5 flex-none items-center justify-center rounded-full border text-[11px] font-bold " + TONE[c.status]}>
              {ICON[c.status]}
            </span>
            <span className="min-w-0 flex-1 text-[13px] text-slate">
              {t(`saas.launch.c.${c.key}` as MessageKey, { d: c.detail || "-" })}
              {c.detail && c.status !== "pass" ? (
                <span className="ml-1.5 font-mono text-[11.5px] text-steel">{c.detail}</span>
              ) : null}
            </span>
            {c.status === "manual" ? (
              <Button variant="ghost" size="sm" loading={busy === c.key}
                      onClick={() => confirm(c.key)}>
                {t("saas.launch.confirm")}
              </Button>
            ) : null}
          </div>
        ))}
      </div>
    </Card>
  );
}
