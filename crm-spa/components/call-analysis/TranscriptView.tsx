"use client";

import { useEffect, useMemo, useRef } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { Spinner } from "@/components/ui";
import type { Transcript, TranscriptWord } from "./data";
import { formatSec, inAnyWindow } from "./timecode";

/**
 * Транскрипт (§10.3, центр). Структура (реплики, роли, таймкоды, подсветка
 * доказательств, перемотка) строится из `words` турецкого оригинала — это спина
 * «моста доказательств», привязанная к секундам, а не к языку. Перевод бэк
 * отдаёт плоским текстом (?lang=), поэтому при RU/EN показываем его отдельной
 * читаемой панелью сверху (руководитель читает по-русски), а таймкоды/подсветка/
 * аудио остаются на оригинале снизу (слышит по-турецки, видит совпадение, §2).
 * Транскрипт — самая светлая поверхность, максимальный контраст (§13).
 */
export type ViewLang = "ru" | "en" | "tr";

interface Turn {
  role: string;
  startSec: number;
  words: TranscriptWord[];
  hasEvidence: boolean;
}

interface TranscriptViewProps {
  transcript: Transcript;
  viewLang: ViewLang;
  translationText: string | null;
  translationLoading: boolean;
  translationError: boolean;
  /** Все окна доказательств из аудита — подсвечиваем ровно эти моменты (§10.3). */
  evidenceWindows: [number, number][];
  /** Прыжок «моста»: сменился token → прокрутить к секунде. */
  focus: { sec: number; token: number } | null;
  onSeek: (sec: number) => void;
}

function buildTurns(words: TranscriptWord[], windows: [number, number][]): Turn[] {
  const turns: Turn[] = [];
  for (const w of words) {
    const last = turns[turns.length - 1];
    if (last && last.role === w.role) {
      last.words.push(w);
      if (inAnyWindow(w.start, windows)) last.hasEvidence = true;
    } else {
      turns.push({
        role: w.role,
        startSec: w.start,
        words: [w],
        hasEvidence: inAnyWindow(w.start, windows),
      });
    }
  }
  return turns;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

export function TranscriptView({
  transcript,
  viewLang,
  translationText,
  translationLoading,
  translationError,
  evidenceWindows,
  focus,
  onSeek,
}: TranscriptViewProps) {
  const t = useT();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const turnRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const words = transcript.words ?? null;
  const turns = useMemo(
    () => (words ? buildTurns(words, evidenceWindows) : []),
    [words, evidenceWindows],
  );

  // Мост доказательств: прокрутить к реплике, содержащей секунду (§2, §13).
  useEffect(() => {
    if (!focus || turns.length === 0) return;
    let targetIdx = 0;
    for (let i = 0; i < turns.length; i++) {
      if (turns[i].startSec <= focus.sec) targetIdx = i;
      else break;
    }
    const node = turnRefs.current.get(targetIdx);
    if (node) {
      node.scrollIntoView({
        behavior: prefersReducedMotion() ? "auto" : "smooth",
        block: "center",
      });
    }
  }, [focus, turns]);

  function roleLabel(role: string): string {
    if (role === "AGENT") return t("calls.transcript.roleAgent");
    if (role === "PLAYER") return t("calls.transcript.rolePlayer");
    return role;
  }

  const showTranslation = viewLang !== "tr";

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Панель перевода (RU/EN) — главная зона чтения, самая светлая (§13) */}
      {showTranslation ? (
        <div className="flex-none mb-3 rounded-card border border-hair2 bg-canvas px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel mb-1.5">
            {t("calls.transcript.translationPanel")}
          </div>
          {translationLoading ? (
            <div className="flex items-center gap-2 text-[13px] text-steel">
              <Spinner size={14} /> {t("calls.transcript.loading")}
            </div>
          ) : translationError ? (
            <div className="text-[13px] text-steel">{t("calls.transcript.translationUnavailable")}</div>
          ) : translationText ? (
            <p className="text-[14.5px] leading-relaxed text-ink whitespace-pre-wrap">{translationText}</p>
          ) : (
            <div className="text-[13px] text-steel">{t("calls.transcript.translationUnavailable")}</div>
          )}
        </div>
      ) : null}

      {/* Оригинал: реплики с таймкодами и подсветкой доказательств */}
      {showTranslation ? (
        <div className="flex-none text-[11px] font-semibold uppercase tracking-[0.5px] text-steel mb-1.5">
          {t("calls.transcript.spine")}
        </div>
      ) : null}

      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto rounded-card border border-hair2 bg-canvas px-4 py-3"
      >
        {turns.length > 0 ? (
          <div className="flex flex-col gap-3">
            {turns.map((turn, i) => (
              <div
                key={i}
                ref={(el) => {
                  if (el) turnRefs.current.set(i, el);
                  else turnRefs.current.delete(i);
                }}
                className={cn(
                  "pl-3",
                  turn.hasEvidence
                    ? "border-l-2 border-steel bg-surface rounded-r-ctl py-1.5"
                    : "border-l-2 border-transparent",
                )}
              >
                <div className="flex items-baseline gap-2 mb-0.5">
                  <button
                    type="button"
                    onClick={() => onSeek(turn.startSec)}
                    className="font-mono text-[12px] text-primary hover:underline cursor-pointer"
                  >
                    {formatSec(turn.startSec)}
                  </button>
                  <span className="text-[10.5px] font-semibold uppercase tracking-[0.5px] text-steel">
                    {roleLabel(turn.role)}
                  </span>
                </div>
                <p className="text-[14.5px] leading-relaxed text-ink">
                  {turn.words.map((w, j) => {
                    const ev = inAnyWindow(w.start, evidenceWindows);
                    return (
                      <span key={j} className={cn(ev && "bg-hair2 rounded-[3px]")}>
                        {w.w}
                        {j < turn.words.length - 1 ? " " : ""}
                      </span>
                    );
                  })}
                </p>
              </div>
            ))}
          </div>
        ) : transcript.text ? (
          // Нет пословной разметки — показываем плоский оригинал (без таймкодов).
          <p className="text-[14.5px] leading-relaxed text-ink whitespace-pre-wrap">{transcript.text}</p>
        ) : (
          <div className="text-[13px] text-steel">{t("calls.transcript.unavailable")}</div>
        )}
      </div>
    </div>
  );
}
