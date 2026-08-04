"use client";

import { useState } from "react";
import { Modal, Button } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import { OUTCOME_LABELS, RESULT_LABELS } from "./access";
import type { CallOutcome, CallResult } from "./types";

/**
 * Call outcome in TWO clicks, no free text (ТЗ п.3.2 — free text lives in notes):
 *   click 1 — outcome (дозвон / недозвон / занято / неверный)
 *   click 2 — if "дозвон": a result (заинтересован / оффер не подошёл /
 *             перезвонить / отказ) which submits; otherwise a single "Сохранить"
 *             confirm submits (no result needed for a non-answer).
 * "Недозвон" keeps the player in the queue and the parent offers to schedule the
 * next touch (ТЗ п.3.3).
 */
interface OutcomeModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (outcome: CallOutcome, result: CallResult | null) => Promise<void> | void;
  /** Masked phone from originate, shown as confirmation. */
  phoneMasked?: string;
  busy?: boolean;
  error?: string | null;
}

const OUTCOMES: CallOutcome[] = ["answered", "no_answer", "busy", "wrong_number"];
const RESULTS: CallResult[] = ["interested", "offer_declined", "callback_requested", "refused"];

export function OutcomeModal({
  open,
  onClose,
  onSubmit,
  phoneMasked,
  busy = false,
  error = null,
}: OutcomeModalProps) {
  const t = useT();
  const [outcome, setOutcome] = useState<CallOutcome | null>(null);

  function reset() {
    setOutcome(null);
  }

  function pickOutcome(o: CallOutcome) {
    setOutcome(o);
    // Non-answered outcomes need no result — but we still require an explicit
    // second click ("Сохранить") so a mis-tap doesn't record a call.
  }

  async function submit(result: CallResult | null) {
    await onSubmit(outcome as CallOutcome, result);
    reset();
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title={t("card.outcomeModal.title")}
      widthClass="max-w-md"
    >
      {phoneMasked ? (
        <div className="text-[12.5px] text-steel mb-3">
          {t("card.outcomeModal.dialedNumber")} <span className="font-mono text-slate">{phoneMasked}</span>
        </div>
      ) : null}

      {/* Step 1 — outcome */}
      <div className="text-[12px] font-medium text-slate mb-2">{t("card.outcomeModal.step1")}</div>
      <div className="grid grid-cols-2 gap-2">
        {OUTCOMES.map((o) => (
          <button
            key={o}
            type="button"
            onClick={() => pickOutcome(o)}
            disabled={busy}
            className={cn(
              "rounded-ctl border px-3 py-2.5 text-[13.5px] font-medium transition-colors cursor-pointer",
              outcome === o
                ? "bg-ink text-white border-ink"
                : "bg-canvas text-slate border-hair2 hover:border-primary hover:text-primary",
            )}
          >
            {t(OUTCOME_LABELS[o])}
          </button>
        ))}
      </div>

      {/* Step 2 — result (answered) or confirm (not answered) */}
      {outcome === "answered" ? (
        <>
          <div className="text-[12px] font-medium text-slate mt-4 mb-2">{t("card.outcomeModal.step2")}</div>
          <div className="grid grid-cols-2 gap-2">
            {RESULTS.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => submit(r)}
                disabled={busy}
                className="rounded-ctl border border-hair2 bg-canvas px-3 py-2.5 text-[13.5px] font-medium text-slate transition-colors hover:border-primary hover:text-primary disabled:opacity-50 cursor-pointer"
              >
                {t(RESULT_LABELS[r])}
              </button>
            ))}
          </div>
        </>
      ) : outcome ? (
        <div className="mt-4 flex items-center justify-between gap-3">
          <div className="text-[12.5px] text-steel">
            {outcome === "no_answer"
              ? t("card.outcomeModal.noAnswerNote")
              : t("card.outcomeModal.genericNote")}
          </div>
          <Button variant="brand" onClick={() => submit(null)} loading={busy}>
            {t("ui.save")}
          </Button>
        </div>
      ) : null}

      {error ? <div className="mt-3 text-[12.5px] text-neg">{error}</div> : null}
    </Modal>
  );
}
