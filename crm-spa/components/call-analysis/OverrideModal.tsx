"use client";

import { useEffect, useMemo, useState } from "react";
import { Modal, Button, Select } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { flaskErrorText } from "@/lib/api";
import type { CallAudit, Dimension, OverrideResult } from "./data";
import { overrideCall } from "./data";
import { CRITERIA_ORDER, criterionLabelKey } from "./labels";

/**
 * Правка оценки (§10.4). Таблица критериев Модель|Вы (1..5). Итог НЕ считаем на
 * фронте — формула живёт в бэкенде; до сохранения показываем «пересчитается при
 * сохранении», после — берём human_score из ответа. Причина обязательна (уходит
 * в сверку, не в стол). needs_human у модели → «—», но человек может оценить.
 */
interface OverrideModalProps {
  open: boolean;
  onClose: () => void;
  callId: string;
  shortId: string;
  audit: CallAudit;
  getElapsed: () => number;
  onSaved: (result: OverrideResult) => void;
}

function initialScores(dims: Dimension[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const d of dims) {
    out[d.name] = d.needs_human || d.score == null ? 3 : (d.score as number);
  }
  return out;
}

export function OverrideModal({
  open,
  onClose,
  callId,
  shortId,
  audit,
  getElapsed,
  onSaved,
}: OverrideModalProps) {
  const t = useT();
  const ordered = useMemo(
    () => CRITERIA_ORDER.map((n) => audit.dimensions.find((d) => d.name === n)).filter(
      (d): d is Dimension => d != null,
    ),
    [audit.dimensions],
  );

  const [scores, setScores] = useState<Record<string, number>>(() => initialScores(ordered));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setScores(initialScores(ordered));
      setReason("");
      setError(null);
    }
  }, [open, ordered]);

  async function save() {
    if (!reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await overrideCall(callId, scores, reason.trim(), getElapsed());
      onSaved(result);
      onClose();
    } catch (e) {
      setError(flaskErrorText(e, t, "calls.override.saveError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("calls.override.title", { id: shortId })}
      widthClass="max-w-lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("calls.override.cancel")}
          </Button>
          <Button variant="brand" onClick={save} loading={busy} disabled={!reason.trim()}>
            {t("calls.override.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-steel text-[11px] uppercase tracking-[0.5px]">
              <th className="text-left font-normal pb-1.5">{t("calls.override.criterion")}</th>
              <th className="text-center font-normal pb-1.5">{t("calls.override.model")}</th>
              <th className="text-right font-normal pb-1.5">{t("calls.override.you")}</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((d) => {
              const lk = criterionLabelKey(d.name);
              const modelVal = d.needs_human || d.score == null ? "—" : d.score;
              return (
                <tr key={d.name} className="border-t border-hair">
                  <td className="py-1.5 text-slate">{lk ? t(lk) : d.name}</td>
                  <td className="py-1.5 text-center font-mono text-steel tabular-nums">{modelVal}</td>
                  <td className="py-1.5 text-right">
                    <Select
                      value={String(scores[d.name] ?? 3)}
                      onChange={(e) =>
                        setScores((s) => ({ ...s, [d.name]: Number(e.target.value) }))
                      }
                      className="h-[34px] w-[64px] inline-block text-center"
                    >
                      {[1, 2, 3, 4, 5].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </Select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div className="text-[13px] text-slate">
          <span className="font-mono">
            {t("calls.override.total", { model: audit.score ?? "—", human: "…" })}
          </span>
          <div className="text-[11.5px] text-stone mt-0.5">{t("calls.override.willRecalc")}</div>
        </div>

        <div>
          <label className="text-[12.5px] font-medium text-slate">
            {t("calls.override.reason")}
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("calls.override.reasonPlaceholder")}
            className="mt-1 w-full bg-canvas text-ink border border-hair3 rounded-ctl px-3 py-2.5 text-[13.5px] outline-none focus:border-2 focus:border-primary placeholder:text-stone min-h-[84px] resize-y"
          />
        </div>

        <div className="text-[11.5px] text-steel">{t("calls.override.toReconciliation")}</div>
        {error ? <div className="text-[12.5px] text-neg">{error}</div> : null}
      </div>
    </Modal>
  );
}
