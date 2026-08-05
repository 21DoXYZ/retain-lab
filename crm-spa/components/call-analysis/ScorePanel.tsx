"use client";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { Badge, Button } from "@/components/ui";
import type { CallAudit, Dimension } from "./data";
import {
  CRITERIA_ORDER,
  criterionLabelKey,
  criterionMark,
  objectionLabelKey,
  outcomeLabelKey,
  verdictTone,
} from "./labels";
import { firstEvidenceSec } from "./timecode";
import { formatClock } from "./useReviewTimer";

/**
 * Левая зона карточки (§10.3): балл, вердикт, версии, критерии (клик = мост
 * доказательств), кнопки «Подтвердить/Поправить», учёт времени на разборе.
 */
export interface HumanOverrideView {
  model: number | null;
  human: number | null;
  name: string;
  date: string;
}

export interface ConfirmFeedback {
  text: string;
  tone: "pos" | "warn" | "neg";
}

interface ScorePanelProps {
  audit: CallAudit;
  verdictUnlocked: boolean;
  canReview: boolean;
  activeCriterion: string | null;
  humanOverride: HumanOverrideView | null;
  reviewElapsed: number;
  confirmBusy: boolean;
  confirmFeedback: ConfirmFeedback | null;
  onCriterionClick: (name: string, firstSec: number | null) => void;
  onConfirm: () => void;
  onCorrect: () => void;
}

function MarkIcon({ score }: { score: number }) {
  const m = criterionMark(score);
  const glyph = m.icon === "check" ? "✓" : m.icon === "cross" ? "✗" : "⚠";
  return (
    <span aria-hidden style={{ color: m.fg }}>
      {glyph}
    </span>
  );
}

export function ScorePanel({
  audit,
  verdictUnlocked,
  canReview,
  activeCriterion,
  humanOverride,
  reviewElapsed,
  confirmBusy,
  confirmFeedback,
  onCriterionClick,
  onConfirm,
  onCorrect,
}: ScorePanelProps) {
  const t = useT();
  const byName = new Map(audit.dimensions.map((d) => [d.name, d]));
  const ordered: Dimension[] = CRITERIA_ORDER.map((name) => byName.get(name)).filter(
    (d): d is Dimension => d != null,
  );
  const vt = verdictTone(audit.pass_fail);
  const vers = audit.versions;
  const outcomeKey = outcomeLabelKey(audit.offer_outcome);

  return (
    <div className="flex flex-col gap-4">
      {/* Балл + вердикт + версии */}
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel">
          {t("calls.card.scoreLabel")}
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className="font-mono font-extrabold text-[40px] leading-none tracking-[-1px] text-ink tabular-nums">
            {audit.score ?? "—"}
          </span>
          {verdictUnlocked && vt ? (
            <Badge bg={vt.bg} fg={vt.fg} className="text-[12px]">
              {t(vt.labelKey)}
            </Badge>
          ) : (
            <span className="text-[12px] text-steel">{t("calls.verdict.locked")}</span>
          )}
        </div>
        {humanOverride ? (
          <div className="mt-1.5 text-[12.5px] text-slate">
            {t("calls.card.humanOverride", {
              model: humanOverride.model ?? "—",
              human: humanOverride.human ?? "—",
              name: humanOverride.name,
              date: humanOverride.date,
            })}
          </div>
        ) : null}
        <div className="mt-1.5 font-mono text-[11.5px] text-stone">
          {t("calls.card.versions", {
            script: String(vers.script ?? "—"),
            rubric: String(vers.rubric ?? "—"),
            model: vers.model ?? "—",
          })}
        </div>
      </div>

      {/* Критерии — клик раскрывает обоснование и запускает мост (§10.3) */}
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel mb-2">
          {t("calls.card.criteria")}
        </div>
        <ul className="flex flex-col">
          {ordered.map((d) => {
            const lk = criterionLabelKey(d.name);
            const active = activeCriterion === d.name;
            const needsCheck = d.needs_human || d.score == null;
            return (
              <li key={d.name} className="border-b border-hair last:border-b-0">
                <button
                  type="button"
                  onClick={() => onCriterionClick(d.name, firstEvidenceSec(d.evidence_ts))}
                  className={cn(
                    "w-full flex items-center justify-between gap-3 py-2 text-left cursor-pointer",
                    "hover:bg-cream transition-colors rounded-ctl px-1.5",
                    active && "bg-cream",
                  )}
                >
                  <span className="text-[13.5px] text-slate">{lk ? t(lk) : d.name}</span>
                  {needsCheck ? (
                    <span
                      className="text-[12px] text-[#b45309] whitespace-nowrap"
                      title={t("calls.card.needsCheckTip")}
                    >
                      {t("calls.card.needsCheck")}
                    </span>
                  ) : (
                    <span className="font-mono text-[13px] text-slate whitespace-nowrap flex items-center gap-1.5 tabular-nums">
                      {d.score}/5 <MarkIcon score={d.score as number} />
                    </span>
                  )}
                </button>
                {active && d.justification ? (
                  <div className="px-1.5 pb-2.5 text-[12.5px] leading-relaxed text-steel">
                    {d.justification}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </div>

      {/* Исход оффера + возражения */}
      {outcomeKey || (audit.objections && audit.objections.length > 0) ? (
        <div className="flex flex-col gap-2">
          {outcomeKey ? (
            <div className="text-[12.5px] text-slate">
              <span className="text-steel">{t("calls.card.offerOutcome")}: </span>
              {t(outcomeKey)}
            </div>
          ) : null}
          {audit.objections && audit.objections.length > 0 ? (
            <div className="flex flex-wrap gap-1.5 items-center">
              <span className="text-[12px] text-steel">{t("calls.card.objections")}:</span>
              {audit.objections.map((o, i) => {
                // o — объект {type, reason, handled}; переводим по коду type,
                // фолбэк — сам код (НЕ весь объект, иначе React падает).
                const k = objectionLabelKey(o.type);
                return (
                  <Badge key={i} bg="#ecf3ff" fg="#3641f5" className="text-[11px]">
                    {k ? t(k) : o.type}
                  </Badge>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Подтвердить / Поправить + учёт времени (§7) */}
      {canReview ? (
        <div className="flex flex-col gap-2 border-t border-hair pt-3">
          <div className="flex gap-2">
            <Button variant="brand" onClick={onConfirm} loading={confirmBusy} className="flex-1">
              {t("calls.card.confirm")}
            </Button>
            <Button variant="ghost" onClick={onCorrect} className="flex-1">
              {t("calls.card.correct")}
            </Button>
          </div>
          <div
            className="font-mono text-[11.5px] text-stone cursor-help"
            title={t("calls.card.reconcileTip")}
          >
            {t("calls.card.reviewTime", { t: formatClock(reviewElapsed) })}
          </div>
          {confirmFeedback ? (
            <div
              className="text-[12px]"
              style={{
                color:
                  confirmFeedback.tone === "pos"
                    ? "#15803d"
                    : confirmFeedback.tone === "warn"
                      ? "#b45309"
                      : "#dc2626",
              }}
            >
              {confirmFeedback.text}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="border-t border-hair pt-3 text-[12px] text-steel">
          {t("calls.card.analystNote")}
        </div>
      )}
    </div>
  );
}
