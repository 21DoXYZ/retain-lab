"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useRole } from "@/lib/role-context";
import { formatDate } from "@/lib/format";
import { Panel, ErrorState, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import {
  fetchCall,
  confirmCall,
  type CallCardResponse,
  type OverrideResult,
} from "./data";
import { canReview as canReviewRole, statusLabelKey } from "./labels";
import { parseWindow, formatSec } from "./timecode";
import { useReviewTimer } from "./useReviewTimer";
import { readQueueIds } from "./queueNav";
import { ScorePanel, type HumanOverrideView, type ConfirmFeedback } from "./ScorePanel";
import { TranscriptView, type ViewLang } from "./TranscriptView";
import { ComplianceStrip } from "./ComplianceStrip";
import { OverrideModal } from "./OverrideModal";
import { AudioPlayer, type AudioPlayerHandle } from "./AudioPlayer";
import { LangSwitch } from "./LangSwitch";

/**
 * Карточка звонка — ядро продукта (§10.3). Три зоны: слева балл+критерии, центр
 * транскрипт, снизу плеер (sticky). МОСТ ДОКАЗАТЕЛЬСТВ: клик по критерию →
 * раскрыть обоснование → прокрутить транскрипт к моменту → перемотать плеер.
 * Режим очереди (?queue=1): навигация ← Пред / След →, автопереход, горячие
 * клавиши. Учёт времени на разборе (§7) → review_time_s в confirm/override.
 */
function CallCardScreenInner({ callId }: { callId: string }) {
  const t = useT();
  const router = useRouter();
  const me = useRole();
  const searchParams = useSearchParams();
  const canReview = canReviewRole(me.role);

  const [base, setBase] = useState<CallCardResponse | null>(null);
  const [state, setState] = useState<"loading" | "error" | "data">("loading");
  const [error, setError] = useState<string | null>(null);

  const [viewLang, setViewLang] = useState<ViewLang>("ru");
  const [translations, setTranslations] = useState<Record<string, string>>({});
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationError, setTranslationError] = useState(false);

  const [activeCriterion, setActiveCriterion] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ sec: number; token: number } | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmFeedback, setConfirmFeedback] = useState<ConfirmFeedback | null>(null);
  const [humanOverride, setHumanOverride] = useState<HumanOverrideView | null>(null);

  const playerRef = useRef<AudioPlayerHandle | null>(null);
  const focusToken = useRef(0);
  const timer = useReviewTimer(callId);

  // Режим очереди (§10.2)
  const queueMode = searchParams.get("queue") === "1";
  const queueIds = useMemo(() => (queueMode ? readQueueIds() : []), [queueMode]);
  const queueIdx = queueIds.indexOf(callId);
  const hasQueue = queueMode && queueIdx >= 0;

  // ── Загрузка карточки (по умолчанию RU-перевод подгружается при открытии) ──
  useEffect(() => {
    let alive = true;
    setState("loading");
    setError(null);
    setActiveCriterion(null);
    setFocus(null);
    setConfirmFeedback(null);
    setViewLang("ru");
    setTranslationError(false);
    fetchCall(callId, "ru")
      .then((r) => {
        if (!alive) return;
        setBase(r);
        setState("data");
        setTranslations(r.transcript?.translation?.text ? { ru: r.transcript.translation.text } : {});
        setHumanOverride(buildHumanOverride(r));
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(flaskErrorText(e, t, "calls.common.loadError"));
        setState("error");
      });
    return () => {
      alive = false;
    };
  }, [callId, t]);

  // ── Перевод по требованию (§10.3): TR не грузим, RU/EN — с кэшем ──────────
  useEffect(() => {
    if (viewLang === "tr" || translations[viewLang] != null) {
      setTranslationError(false);
      return;
    }
    let alive = true;
    setTranslationLoading(true);
    setTranslationError(false);
    fetchCall(callId, viewLang)
      .then((r) => {
        if (!alive) return;
        const txt = r.transcript?.translation?.text ?? "";
        setTranslations((prev) => ({ ...prev, [viewLang]: txt }));
        if (!txt) setTranslationError(true);
      })
      .catch(() => {
        if (alive) setTranslationError(true);
      })
      .finally(() => {
        if (alive) setTranslationLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [callId, viewLang, translations]);

  const audit = base?.audit ?? null;
  const evidenceWindows = useMemo<[number, number][]>(() => {
    if (!audit) return [];
    const out: [number, number][] = [];
    for (const d of audit.dimensions) {
      for (const ts of d.evidence_ts ?? []) {
        const w = parseWindow(ts);
        if (w) out.push(w);
      }
    }
    return out;
  }, [audit]);

  const seek = useCallback((sec: number) => playerRef.current?.seek(sec), []);

  const onCriterionClick = useCallback(
    (name: string, firstSec: number | null) => {
      const opening = activeCriterion !== name;
      setActiveCriterion(opening ? name : null);
      if (opening && firstSec != null) {
        focusToken.current += 1;
        setFocus({ sec: firstSec, token: focusToken.current }); // прокрутка транскрипта
        playerRef.current?.seek(firstSec); // перемотка плеера
      }
    },
    [activeCriterion],
  );

  const gotoIndex = useCallback(
    (i: number) => {
      if (i < 0 || i >= queueIds.length) {
        router.push("/call-analysis/queue");
        return;
      }
      router.push(`/call-analysis/calls/${queueIds[i]}?queue=1`);
    },
    [queueIds, router],
  );

  const advance = useCallback(() => {
    if (hasQueue) setTimeout(() => gotoIndex(queueIdx + 1), 700); // после подтв./правки (§10.2)
  }, [hasQueue, gotoIndex, queueIdx]);

  const handleConfirm = useCallback(async () => {
    setConfirmBusy(true);
    setConfirmFeedback(null);
    try {
      const res = await confirmCall(callId, timer.getElapsed());
      setConfirmFeedback(
        res.counted
          ? { text: t("calls.card.confirmed"), tone: "pos" }
          : { text: t("calls.card.confirmedNotCounted"), tone: "warn" },
      );
      advance();
    } catch (e) {
      setConfirmFeedback({ text: flaskErrorText(e, t, "calls.card.confirmError"), tone: "neg" });
    } finally {
      setConfirmBusy(false);
    }
  }, [callId, timer, t, advance]);

  const handleOverrideSaved = useCallback(
    (res: OverrideResult) => {
      setHumanOverride({
        model: res.model_score,
        human: res.human_score,
        name: me.full_name,
        date: formatDate(new Date()),
      });
      advance();
    },
    [me.full_name, advance],
  );

  // ── Горячие клавиши (§10.2): →/← нав по очереди, Пробел, П, O, Esc ────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT")) return;
      if (overrideOpen) return;
      const k = e.key;
      if (k === " ") {
        e.preventDefault();
        playerRef.current?.toggle();
      } else if (k === "ArrowRight") {
        if (hasQueue && !e.shiftKey) gotoIndex(queueIdx + 1);
        else playerRef.current?.nudge(5);
      } else if (k === "ArrowLeft") {
        if (hasQueue && !e.shiftKey) gotoIndex(queueIdx - 1);
        else playerRef.current?.nudge(-5);
      } else if ("pPзЗпП".includes(k)) {
        // «П» подтвердить (§10.2): Latin p, тот же физ-клавиш в ЙЦУКЕН (з), сама буква п
        if (canReview) void handleConfirm();
      } else if ("oOщЩоО".includes(k)) {
        // «O» поправить: Latin o, тот же физ-клавиш (щ), кириллическая о
        if (canReview && audit) setOverrideOpen(true);
      } else if (k === "Escape") {
        if (queueMode) router.push("/call-analysis/queue");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hasQueue, queueIdx, gotoIndex, canReview, handleConfirm, audit, overrideOpen, queueMode, router]);

  if (state === "loading") {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-96" />
        <div className="grid lg:grid-cols-[320px_1fr] gap-5">
          <Skeleton className="h-80 w-full" />
          <Skeleton className="h-80 w-full" />
        </div>
      </div>
    );
  }
  if (state === "error" || !base) {
    return (
      <Panel>
        <ErrorState description={error ?? undefined} onRetry={() => router.refresh()} />
      </Panel>
    );
  }

  const call = base.call;
  const canPlay = base.can_play_audio;
  const shortId = `#${callId.slice(0, 4).toUpperCase()}`;
  const statusKey = statusLabelKey(call.status);

  return (
    <div className="flex flex-col gap-4">
      {/* Верхняя строка: возврат + режим очереди (§10.2) */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3 text-[13px]">
          {queueMode ? (
            <button
              type="button"
              onClick={() => router.push("/call-analysis/queue")}
              className="text-primary hover:underline cursor-pointer"
            >
              ← {t("calls.card.backToQueue")}
            </button>
          ) : null}
          <span className="font-mono text-primary">{shortId}</span>
          <span className="text-steel">
            {t("calls.common.player", { id: call.player_id ?? "—" })} ·{" "}
            <span className="font-mono">{formatSec(call.duration_s ?? 0)}</span>
          </span>
        </div>
        {hasQueue ? (
          <div className="flex items-center gap-2 text-[13px]">
            <button
              type="button"
              onClick={() => gotoIndex(queueIdx - 1)}
              disabled={queueIdx <= 0}
              className="text-primary hover:underline disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              ← {t("calls.card.prev")}
            </button>
            <span className="font-mono text-steel">
              {t("calls.card.position", { i: queueIdx + 1, n: queueIds.length })}
            </span>
            <button
              type="button"
              onClick={() => gotoIndex(queueIdx + 1)}
              className="text-primary hover:underline cursor-pointer"
            >
              {t("calls.card.next")} →
            </button>
          </div>
        ) : null}
      </div>

      {/* Полоса обязательных фраз (§10.3) */}
      {audit?.compliance && audit.compliance.length > 0 ? (
        <ComplianceStrip
          compliance={audit.compliance}
          canPlay={canPlay}
          onSeek={seek}
          onListenFull={() => seek(0)}
        />
      ) : null}

      {/* Реакция ПОСЛЕ звонка: через сколько минут деп / вернулся в игру (≤7д).
          Единственная опора, не зависящая от рубрики, — результат (§10.6). */}
      {base?.reaction && (base.reaction.deposit_min != null || base.reaction.played_min != null) ? (
        <div className="rounded-ctl border border-hair bg-cream px-3.5 py-2.5 text-[13px] text-slate">
          <b>{t("calls.card.reaction.title")}</b>{" "}
          {base.reaction.deposit_min != null
            ? t("calls.card.reaction.deposit", { min: base.reaction.deposit_min })
            : t("calls.card.reaction.noDeposit")}
          {" · "}
          {base.reaction.played_min != null
            ? t("calls.card.reaction.played", { min: base.reaction.played_min })
            : t("calls.card.reaction.noPlay")}
        </div>
      ) : null}

      {/* Три зоны */}
      <div className="grid lg:grid-cols-[320px_1fr] gap-5 lg:h-[calc(100vh-260px)] lg:min-h-[420px]">
        <div className="lg:overflow-y-auto lg:min-h-0">
          <Panel className="p-4">
            {audit ? (
              <ScorePanel
                audit={audit}
                verdictUnlocked={base.verdict_unlocked}
                canReview={canReview}
                activeCriterion={activeCriterion}
                humanOverride={humanOverride}
                reviewElapsed={timer.elapsed}
                confirmBusy={confirmBusy}
                confirmFeedback={confirmFeedback}
                onCriterionClick={onCriterionClick}
                onConfirm={handleConfirm}
                onCorrect={() => setOverrideOpen(true)}
              />
            ) : (
              <div className="text-[13px] text-steel">
                {statusKey ? t(statusKey) : t("calls.card.notFound")}
              </div>
            )}
          </Panel>
        </div>

        <div className="lg:min-h-0 flex flex-col">
          <div className="flex items-center justify-between gap-3 mb-2">
            <h2 className="text-sm font-semibold text-ink">{t("calls.transcript.title")}</h2>
            <LangSwitch value={viewLang} onChange={setViewLang} />
          </div>
          {base.transcript ? (
            <TranscriptView
              transcript={base.transcript}
              viewLang={viewLang}
              translationText={viewLang === "tr" ? null : (translations[viewLang] ?? null)}
              translationLoading={translationLoading}
              translationError={translationError}
              evidenceWindows={evidenceWindows}
              focus={focus}
              onSeek={seek}
            />
          ) : (
            <Panel className="p-4 text-[13px] text-steel">{t("calls.transcript.unavailable")}</Panel>
          )}
        </div>
      </div>

      {/* Плеер снизу — sticky (§10.3). analyst/оператор: can_play_audio=false */}
      {canPlay ? (
        <div className="sticky bottom-0 z-10 -mx-8 px-8 py-3 bg-canvas border-t border-hair2">
          <AudioPlayer ref={playerRef} callId={callId} />
          <div className="mt-1 text-[10.5px] text-stone">{t("calls.audio.keysHint")}</div>
        </div>
      ) : null}

      {audit ? (
        <OverrideModal
          open={overrideOpen}
          onClose={() => setOverrideOpen(false)}
          callId={callId}
          shortId={shortId}
          audit={audit}
          getElapsed={timer.getElapsed}
          onSaved={handleOverrideSaved}
        />
      ) : null}
    </div>
  );
}

/** useSearchParams требует Suspense-границы в App Router (§10.2 режим очереди). */
export function CallCardScreen({ callId }: { callId: string }) {
  return (
    <Suspense fallback={null}>
      <CallCardScreenInner callId={callId} />
    </Suspense>
  );
}

function buildHumanOverride(r: CallCardResponse): HumanOverrideView | null {
  const a = r.audit;
  if (!a || a.human?.override_score == null) return null;
  const ovr = (r.reviews ?? []).find((rv) => rv.kind === "override");
  return {
    model: a.score,
    human: a.human.override_score,
    name: ovr?.reviewer_name ?? "—",
    date: ovr?.created_at ? formatDate(ovr.created_at) : "",
  };
}
