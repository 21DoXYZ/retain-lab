"use client";

import { useMemo, useState } from "react";
import { Card, Button, Badge, Modal, EmptyState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { formatDateShort } from "@/lib/format";
import { OUTCOME_LABELS, RESULT_LABELS } from "./access";
import { OutcomeModal } from "./OutcomeModal";
import { RecordingPlayer } from "./RecordingPlayer";
import { ScriptPeek } from "./ScriptPeek";
import { originateCall, saveCallOutcome, touchAssignment, cardErrorText } from "./data";
import { HandoffButton } from "./HandoffButton";
import type { CallOutcome, CallResult, CallRow } from "./types";

/**
 * Call block (ТЗ п.3): masked phone + "Позвонить" (adapter originate) →
 * 2-click outcome → crm.calls. A soft "сегодня уже звонил X" warning fires when
 * another operator touched this player today (no block — ТЗ п.2.2). Below: the
 * call journal with outcomes and, for RECORDING_ROLES, recording playback.
 */
interface CallBlockProps {
  playerId: number;
  meId: string;
  canListenRecording: boolean;
  calls: CallRow[];
  names: Map<string, string>;
  onChanged: () => void;
  /** Called after a "недозвон" outcome so the parent can offer to schedule. */
  onNoAnswer: () => void;
}

function startOfTodayMs(): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function nameOf(
  id: string,
  meId: string,
  names: Map<string, string>,
  t: ReturnType<typeof useT>,
): string {
  if (id === meId) return t("card.common.you");
  return names.get(id) ?? t("card.common.operatorFallback", { id: id.slice(-4) });
}

export function CallBlock({
  playerId,
  meId,
  canListenRecording,
  calls,
  names,
  onChanged,
  onNoAnswer,
}: CallBlockProps) {
  const t = useT();
  const [dialing, setDialing] = useState(false);
  const [outcomeOpen, setOutcomeOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [callRef, setCallRef] = useState<string | null>(null);
  const [phoneConfirm, setPhoneConfirm] = useState<string | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Another operator called this player today? → soft warning (ТЗ п.2.2).
  const calledTodayByOthers = useMemo(() => {
    const since = startOfTodayMs();
    const seen = new Map<string, CallRow>();
    for (const c of calls) {
      if (c.operator_id === meId) continue;
      if (new Date(c.started_at).getTime() >= since) seen.set(c.operator_id, c);
    }
    return Array.from(seen.values());
  }, [calls, meId]);

  async function doOriginate() {
    setDialing(true);
    setError(null);
    try {
      const res = await originateCall(playerId);
      setCallRef(res.call_ref);
      setPhoneConfirm(res.player_phone_masked);
      setOutcomeOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("card.call.originateError"));
    } finally {
      setDialing(false);
    }
  }

  function onCallClick() {
    if (calledTodayByOthers.length > 0) {
      setConfirmOpen(true);
    } else {
      void doOriginate();
    }
  }

  async function submitOutcome(outcome: CallOutcome, result: CallResult | null) {
    setSaving(true);
    setError(null);
    try {
      await saveCallOutcome({
        playerId,
        operatorId: meId,
        outcome,
        result,
        providerRef: callRef,
      });
      // Исход звонка ДВИЖЕТ статус в «Моей очереди»: иначе игрок навсегда
      // остаётся «не тронут», очередь не отражает работу (touchAssignment
      // был написан, но не подключён — статусы были мёртвые).
      void touchAssignment({
        playerId,
        operatorId: meId,
        status:
          outcome !== "answered" ? "no_answer"
          : result === "refused" || result === "offer_declined" ? "refused"
          : result === "interested" ? "agreed"
          : "answered",
      });
      setOutcomeOpen(false);
      setCallRef(null);
      onChanged();
      if (outcome === "no_answer") onNoAnswer();
    } catch (e) {
      setError(cardErrorText(e, t, "card.call.saveError"));
    } finally {
      setSaving(false);
    }
  }

  const todayHint = calledTodayByOthers[0];

  return (
    <Card>
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <div className="text-sm font-semibold text-ink">{t("card.call.title")}</div>
          {/* Номер НЕ показываем совсем: звонок идёт только кнопкой через
              звонилку (номер не нужен оператору и не должен смущать/утекать). */}
          <div className="mt-0.5 text-[12.5px] text-stone">{t("card.call.viaButtonOnly")}</div>
        </div>
        <div className="flex items-center gap-2">
          {/* скрипт перед глазами во время звонка — активная версия, read-only */}
          <ScriptPeek />
          {/* передать игрока на WhatsApp-менеджера / руководителя (запрос клиента) */}
          <HandoffButton playerId={playerId} />
          <Button variant="brand" onClick={onCallClick} loading={dialing}>
            {t("card.call.callButton")}
          </Button>
        </div>
      </div>

      {todayHint ? (
        <div className="mt-3 rounded-ctl bg-cream border border-beige px-3 py-2 text-[12.5px] text-slate">
          {t("card.call.todayHintLead", { time: formatDateShort(todayHint.started_at) })}{" "}
          <b>{nameOf(todayHint.operator_id, meId, names, t)}</b>{" "}
          {t("card.call.todayHintTrail", { outcome: t(OUTCOME_LABELS[todayHint.outcome]) })}
        </div>
      ) : null}

      {error ? <div className="mt-3 text-[12.5px] text-neg">{error}</div> : null}

      {/* Call journal */}
      <div className="mt-4">
        <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel mb-2">
          {t("card.call.journalTitle")}
        </div>
        {calls.length === 0 ? (
          <EmptyState
            icon="📞"
            title={t("card.call.emptyTitle")}
            description={t("card.call.emptyDescription")}
            className="py-8"
          />
        ) : (
          <ul className="flex flex-col divide-y divide-hair">
            {calls.map((c) => (
              <li key={c.id} className="py-2.5 flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <OutcomeBadge outcome={c.outcome} />
                    {c.result ? (
                      <span className="text-[12.5px] text-slate">{t(RESULT_LABELS[c.result])}</span>
                    ) : null}
                  </div>
                  <div className="mt-0.5 text-[12px] text-steel">
                    {nameOf(c.operator_id, meId, names, t)} · {formatDateShort(c.started_at)}
                    {c.duration_sec != null ? ` · ${c.duration_sec} c` : ""}
                  </div>
                </div>
                {c.recording_ref && canListenRecording ? <RecordingPlayer callId={c.id} /> : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Confirm before double-touch */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t("card.call.confirmTitle")}
        widthClass="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              {t("ui.cancel")}
            </Button>
            <Button
              variant="brand"
              onClick={() => {
                setConfirmOpen(false);
                void doOriginate();
              }}
            >
              {t("card.call.confirmAnyway")}
            </Button>
          </>
        }
      >
        <div className="text-[13.5px] text-slate">
          {todayHint ? (
            <>
              {t("card.call.confirmLead")}{" "}
              <b>{nameOf(todayHint.operator_id, meId, names, t)}</b>{" "}
              {t("card.call.confirmTrail", { outcome: t(OUTCOME_LABELS[todayHint.outcome]) })}
            </>
          ) : (
            t("card.call.confirmFallback")
          )}
        </div>
      </Modal>

      <OutcomeModal
        open={outcomeOpen}
        onClose={() => setOutcomeOpen(false)}
        onSubmit={submitOutcome}
        phoneMasked={phoneConfirm}
        busy={saving}
        error={outcomeOpen ? error : null}
      />
    </Card>
  );
}

function OutcomeBadge({ outcome }: { outcome: CallOutcome }) {
  const t = useT();
  const tone =
    outcome === "answered"
      ? { bg: "#ecfdf5", fg: "#047857" }
      : outcome === "no_answer"
        ? { bg: "#fffbeb", fg: "#b45309" }
        : { bg: "#fef2f2", fg: "#b91c1c" };
  return (
    <Badge bg={tone.bg} fg={tone.fg}>
      {t(OUTCOME_LABELS[outcome])}
    </Badge>
  );
}
