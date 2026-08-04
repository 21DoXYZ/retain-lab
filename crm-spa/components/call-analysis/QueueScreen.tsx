"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { PageHeader, Panel, Chip, ChipBar, EmptyState, ErrorState, Button, Skeleton } from "@/components/ui";
import type { MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import { fetchQueue, type QueueItem, type QueueResponse, type DisputedCard, type QueueSeries } from "./data";
import { flagLabelKey, statusLabelKey } from "./labels";
import { formatSec } from "./timecode";
import { storeQueueIds } from "./queueNav";

/**
 * Очередь проверки (§10.2). Чипы-фильтры считаются по flags/status/pass_fail.
 * Серии repeated_pattern — одной строкой (разворачивается). Клик по строке →
 * карточка в режиме очереди (?queue=1) с навигацией и автопереходом. Слова
 * статусов — только человеческие (§11.1). Системные слова (ASR/LLM) под запретом.
 */
type FilterKey =
  | "all"
  | "modelUnsure"
  | "fails"
  | "badRecording"
  | "compliance"
  | "needsReview"
  | "disputed"
  | "randomReview";

const CHIPS: { key: FilterKey; labelKey: MessageKey }[] = [
  { key: "all", labelKey: "calls.queue.chip.all" },
  { key: "modelUnsure", labelKey: "calls.queue.chip.modelUnsure" },
  { key: "fails", labelKey: "calls.queue.chip.fails" },
  { key: "badRecording", labelKey: "calls.queue.chip.badRecording" },
  { key: "compliance", labelKey: "calls.queue.chip.compliance" },
  { key: "needsReview", labelKey: "calls.queue.chip.needsReview" },
  { key: "disputed", labelKey: "calls.queue.chip.disputed" },
  { key: "randomReview", labelKey: "calls.queue.chip.randomReview" },
];

function matches(item: QueueItem, filter: FilterKey): boolean {
  const flags = item.flags ?? [];
  switch (filter) {
    case "all":
      return true;
    case "modelUnsure":
      return item.needs_human === true;
    case "fails":
      return item.pass_fail === "FAIL";
    case "badRecording":
      return item.status === "manual_review" || item.status === "asr_failed";
    case "compliance":
      return flags.includes("compliance_failed"); // защитно: сигнала в /queue пока нет
    case "needsReview":
      return item.status === "needs_review";
    case "randomReview":
      return flags.includes("random_review");
    case "disputed":
      return false; // оспоренные — отдельный список disputed_cards
  }
}

function shortId(id: string): string {
  return `#${id.slice(0, 4).toUpperCase()}`;
}

export function QueueScreen() {
  const t = useT();
  const router = useRouter();
  const [data, setData] = useState<QueueResponse | null>(null);
  const [state, setState] = useState<"loading" | "error" | "data">("loading");
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [openSeries, setOpenSeries] = useState<string | null>(null);

  const load = useCallback(() => {
    setState("loading");
    setError(null);
    fetchQueue()
      .then((d) => {
        setData(d);
        setState("data");
      })
      .catch((e: unknown) => {
        setError(flaskErrorText(e, t, "calls.common.loadError"));
        setState("error");
      });
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const items = data?.items ?? [];
  const disputed = data?.disputed_cards ?? [];
  const series = data?.series ?? [];

  const counts = useMemo(() => {
    const c: Record<FilterKey, number> = {
      all: items.length,
      modelUnsure: 0,
      fails: 0,
      badRecording: 0,
      compliance: 0,
      needsReview: 0,
      randomReview: 0,
      disputed: disputed.length,
    };
    for (const it of items) {
      for (const f of ["modelUnsure", "fails", "badRecording", "compliance", "needsReview", "randomReview"] as const) {
        if (matches(it, f)) c[f] += 1;
      }
    }
    return c;
  }, [items, disputed.length]);

  const shownItems = useMemo(
    () => (filter === "disputed" ? [] : items.filter((it) => matches(it, filter))),
    [items, filter],
  );
  const shownDisputed = filter === "all" || filter === "disputed" ? disputed : [];
  const shownSeries = filter === "all" ? series : [];

  // Порядок звонков для режима очереди: видимые одиночные + оспоренные (§10.2).
  const navIds = useMemo(
    () => [...shownItems.map((i) => i.call_id), ...shownDisputed.map((d) => d.call_id)],
    [shownItems, shownDisputed],
  );

  const openCall = useCallback(
    (callId: string) => {
      storeQueueIds(navIds);
      router.push(`/call-analysis/calls/${callId}?queue=1`);
    },
    [navIds, router],
  );

  function reasonFor(it: QueueItem): string {
    const flags = it.flags ?? [];
    for (const f of ["mark_mismatch_no_answer", "mark_mismatch_claimed", "too_short", "no_player_speech"]) {
      if (flags.includes(f)) {
        const k = flagLabelKey(f);
        if (k) return t(k, { sec: it.duration_s ?? 0, n: 0 });
      }
    }
    if (flags.includes("random_review")) return t("calls.flag.random_review");
    if (it.status === "manual_review") return t("calls.status.manualReview");
    if (it.status === "asr_failed") return t("calls.status.asrFailed");
    if (it.status === "llm_failed") return t("calls.status.llmFailed");
    if (it.needs_human) return t("calls.queue.chip.modelUnsure");
    const sk = statusLabelKey(it.status);
    return sk ? t(sk) : "";
  }

  function actionLabel(it: QueueItem): string {
    if (it.status === "manual_review" || it.status === "asr_failed") return t("calls.queue.action.listen");
    return t("calls.queue.action.review");
  }

  const isEmpty = shownItems.length === 0 && shownDisputed.length === 0 && shownSeries.length === 0;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("calls.queue.title")} lead={t("calls.queue.lead")} />

      <ChipBar>
        {CHIPS.map((c) => (
          <Chip key={c.key} active={filter === c.key} onClick={() => setFilter(c.key)}>
            {t(c.labelKey)} <span className="ml-1 font-mono opacity-70">{counts[c.key]}</span>
          </Chip>
        ))}
      </ChipBar>

      {state === "loading" ? (
        <Panel className="p-4">
          <div className="flex flex-col gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        </Panel>
      ) : state === "error" ? (
        <Panel>
          <ErrorState description={error ?? undefined} onRetry={load} />
        </Panel>
      ) : isEmpty ? (
        <Panel>
          <EmptyState
            icon="✅"
            title={t("calls.queue.empty.title")}
            description={t("calls.queue.empty.desc")}
            action={
              <Button variant="ghost" onClick={() => router.push("/call-analysis")}>
                {t("calls.queue.empty.action")}
              </Button>
            }
          />
        </Panel>
      ) : (
        <Panel className="divide-y divide-hair">
          {/* Серии коротких — одной строкой, разворачивается (§10.2, §11.4) */}
          {shownSeries.map((s: QueueSeries) => {
            const open = openSeries === s.operator_id;
            return (
              <div key={`series-${s.operator_id}`} className="px-4 py-2.5">
                <button
                  type="button"
                  onClick={() => setOpenSeries(open ? null : s.operator_id)}
                  className="w-full flex items-center gap-2 text-left cursor-pointer"
                >
                  <span aria-hidden className="text-steel">{open ? "▾" : "▸"}</span>
                  <span className="text-[13.5px] font-medium text-slate">{s.operator_name ?? "—"}</span>
                  <span className="text-[13px] text-steel">
                    {t("calls.queue.series", { n: s.members.length })}
                  </span>
                </button>
                {open ? (
                  <ul className="mt-2 ml-6 flex flex-col gap-1.5">
                    {s.members.map((m) => (
                      <li key={m.call_id}>
                        <button
                          type="button"
                          onClick={() => router.push(`/call-analysis/calls/${m.call_id}`)}
                          className="flex items-center gap-3 text-[12.5px] cursor-pointer hover:text-primary"
                        >
                          <span className="font-mono text-primary">{shortId(m.call_id)}</span>
                          <span className="font-mono text-steel tabular-nums">{formatSec(m.duration_s ?? 0)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            );
          })}

          {/* Одиночные звонки */}
          {shownItems.map((it) => (
            <QueueRow
              key={it.call_id}
              idText={shortId(it.call_id)}
              operator={it.operator_name}
              duration={it.duration_s}
              score={it.score}
              reason={reasonFor(it)}
              action={actionLabel(it)}
              onOpen={() => openCall(it.call_id)}
            />
          ))}

          {/* Оспоренные оператором карточки (§10.2) */}
          {shownDisputed.map((d: DisputedCard) => (
            <QueueRow
              key={d.card_id}
              idText={shortId(d.call_id)}
              operator={d.operator_name ?? null}
              duration={null}
              score={null}
              reason={d.reason || t("calls.queue.disputedReason")}
              action={t("calls.queue.action.resolve")}
              onOpen={() => openCall(d.call_id)}
            />
          ))}
        </Panel>
      )}
    </div>
  );
}

interface QueueRowProps {
  idText: string;
  operator: string | null;
  duration: number | null;
  score: number | null;
  reason: string;
  action: string;
  onOpen: () => void;
}

function QueueRow({ idText, operator, duration, score, reason, action, onOpen }: QueueRowProps) {
  return (
    <div
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter") onOpen();
      }}
      tabIndex={0}
      className={cn(
        "flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-cream transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
      )}
    >
      <span className="font-mono text-[12.5px] text-primary w-14 flex-none">{idText}</span>
      <span className="text-[13px] text-slate w-32 flex-none truncate">{operator ?? "—"}</span>
      <span className="font-mono text-[12.5px] text-steel w-12 flex-none tabular-nums">
        {duration != null ? formatSec(duration) : "—"}
      </span>
      <span className="font-mono text-[13px] text-slate w-10 flex-none tabular-nums">
        {score != null ? score : "—"}
      </span>
      <span className="text-[13px] text-steel flex-1 min-w-0 truncate">{reason}</span>
      <span className="text-[12.5px] text-primary flex-none whitespace-nowrap">{action}</span>
    </div>
  );
}
