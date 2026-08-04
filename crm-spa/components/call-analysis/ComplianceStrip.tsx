"use client";

import { useT } from "@/lib/i18n";
import type { ComplianceCheck } from "./data";
import { complianceLabelKey } from "./labels";
import { tsToSec, formatSec } from "./timecode";

/**
 * Полоса обязательных фраз (§10.3). Свёрнута, пока все present («2 из 2 ✓»);
 * при провале разворачивается сама. Прозвучавшая фраза кликабельна в момент;
 * у НЕ прозвучавшей таймкода нет (evidence_ts=null) — кнопка открывает запись
 * целиком. Полоса НЕ влияет на балл (§10.3): продажа и фразы — разные вопросы.
 */
interface ComplianceStripProps {
  compliance: ComplianceCheck[];
  canPlay: boolean;
  /** Перемотка плеера на секунду (прозвучавшая фраза). */
  onSeek: (sec: number) => void;
  /** Открыть запись целиком (не прозвучавшая фраза — прыгать некуда). */
  onListenFull: () => void;
}

export function ComplianceStrip({ compliance, canPlay, onSeek, onListenFull }: ComplianceStripProps) {
  const t = useT();
  if (!compliance || compliance.length === 0) return null;

  const present = compliance.filter((c) => c.present).length;
  const total = compliance.length;
  const hasFailure = present < total;

  function label(key: string): string {
    const k = complianceLabelKey(key);
    return k ? t(k) : key;
  }

  return (
    <details
      open={hasFailure}
      className="bg-canvas border border-hair2 rounded-card px-4 py-2.5"
    >
      <summary className="flex items-center gap-2 cursor-pointer list-none select-none [&::-webkit-details-marker]:hidden">
        <span className="text-sm font-semibold text-ink">{t("calls.compliance.title")}</span>
        <span className="font-mono text-[13px] text-slate">
          {t("calls.compliance.count", { present, total })}
        </span>
        <span aria-hidden className={hasFailure ? "text-[#b45309]" : "text-[#15803d]"}>
          {hasFailure ? "⚠" : "✓"}
        </span>
      </summary>

      <ul className="mt-2.5 flex flex-col gap-2 border-t border-hair pt-2.5">
        {compliance.map((c, i) => {
          const sec = c.present ? tsToSec(c.evidence_ts ?? null) : null;
          return (
            <li key={i} className="flex items-center justify-between gap-3 text-[13px]">
              <span className="flex items-center gap-2 min-w-0">
                <span aria-hidden style={{ color: c.present ? "#15803d" : "#dc2626" }}>
                  {c.present ? "✓" : "✗"}
                </span>
                <span className="text-slate truncate">{label(c.key)}</span>
                {!c.present ? (
                  <span className="text-steel">— {t("calls.compliance.notSpoken")}</span>
                ) : null}
              </span>
              {canPlay ? (
                c.present && sec != null ? (
                  <button
                    type="button"
                    onClick={() => onSeek(sec)}
                    className="font-mono text-[12.5px] text-primary hover:underline cursor-pointer whitespace-nowrap"
                  >
                    {formatSec(sec)} ▸
                  </button>
                ) : !c.present ? (
                  <button
                    type="button"
                    onClick={onListenFull}
                    className="text-[12.5px] text-primary hover:underline cursor-pointer whitespace-nowrap"
                  >
                    {t("calls.compliance.listenFull")}
                  </button>
                ) : null
              ) : null}
            </li>
          );
        })}
      </ul>
      <div className="mt-2 text-[11.5px] text-stone">{t("calls.compliance.note")}</div>
    </details>
  );
}
