"use client";

import { useState } from "react";
import Link from "next/link";
import {
  PageHeader,
  Eyebrow,
  Card,
  Panel,
  Button,
  Textarea,
  ErrorState,
  EmptyState,
} from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { formatInt } from "@/lib/format";
import { useRole } from "@/lib/role-context";
import { useT } from "@/lib/i18n";
import {
  useCallResource,
  useCriterionLabel,
  formatDuration,
  TrendCell,
} from "./kit";
import type { MyCardsData, CoachingCard, RecentCall } from "./types";

/**
 * Мои звонки (§10.10) — ЭКРАН ОПЕРАТОРА, рабочий язык TR (через словарь).
 * Открывается на карточке коучинга, не на рейтинге. Пока вердикт заблокирован —
 * балла нет, только подтверждённые человеком карточки (сервер фильтрует).
 * Никаких красных штампов; «Anladım» замыкает фидбек-луп, «Katılmıyorum» → к
 * руководителю. Роли: operator, vip_manager.
 */
export function MyCallsScreen() {
  const t = useT();
  const criterionLabel = useCriterionLabel();
  const { state, data, error, reload } = useCallResource<MyCardsData>("/api/v1/call-analysis/my/cards");
  const loading = state !== "data";
  const me = useRole();

  const score = data?.score;

  return (
    <>
      <PageHeader
        title={t("callsboard.my.title")}
        accent={me.full_name}
        lead={data ? t("callsboard.my.thisWeek", { n: data.recent_calls.length }) : undefined}
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          {/* Балл-блок — только если пришёл score (вердикт разблокирован, §7). */}
          {data?.verdict_unlocked && score ? (
            <div className="mt-5 rounded-card border border-beige bg-cream px-[18px] py-4">
              <div className="flex flex-wrap items-baseline gap-3">
                <span className="text-[13px] font-semibold uppercase tracking-[0.5px] text-steel">{t("callsboard.my.avgScore")}</span>
                <span className="font-mono text-[26px] font-extrabold text-ink">{score.avg == null ? "—" : formatInt(score.avg)}</span>
                {score.trend != null ? (
                  <span className="flex items-baseline gap-1.5">
                    <TrendCell value={score.trend} />
                    <span className="text-[13px] text-steel">{t("callsboard.my.vsLastWeek")}</span>
                  </span>
                ) : null}
              </div>
              {score.weak_spot ? (
                <div className="mt-1.5 text-[13.5px] text-slate">
                  {t("callsboard.my.improve", { criterion: criterionLabel(score.weak_spot.criterion) })}
                </div>
              ) : null}
            </div>
          ) : null}

          <Eyebrow>{t("callsboard.my.newCard")}</Eyebrow>
          {loading ? (
            <div className="h-40 animate-pulse rounded-card bg-hair2/50" />
          ) : data && data.cards.length ? (
            <div className="space-y-4">
              {data.cards.map((c) => (
                <CoachingCardView key={c.card_id} card={c} onChanged={reload} />
              ))}
            </div>
          ) : (
            <EmptyState icon="☕" title={t("callsboard.my.noCards")} />
          )}

          <Eyebrow>{t("callsboard.my.recent")}</Eyebrow>
          <Panel>
            {loading ? (
              <div className="p-4 text-steel text-[13.5px]">…</div>
            ) : data && data.recent_calls.length ? (
              <ul className="divide-y divide-hair">
                {data.recent_calls.map((r) => (
                  <RecentRow key={r.call_id} call={r} showScore={data.verdict_unlocked} />
                ))}
              </ul>
            ) : (
              <div className="p-4 text-steel text-[13.5px]">{t("callsboard.my.noRecent")}</div>
            )}
          </Panel>
        </>
      )}
    </>
  );
}

function RecentRow({ call, showScore }: { call: RecentCall; showScore: boolean }) {
  const t = useT();
  return (
    <li>
      <Link href={`/call-analysis/calls/${call.call_id}`} className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-cream">
        <span className="font-mono text-[13px] text-primary">#{call.call_id.slice(0, 4).toUpperCase()}</span>
        <span className="flex-1 text-[13.5px] text-slate">{t("callsboard.my.player", { id: String(call.player_id ?? "—") })}</span>
        <span className="font-mono text-[13px] text-steel">{formatDuration(call.duration_s)}</span>
        {showScore && call.score != null ? <span className="font-mono text-[13px] font-medium text-ink">{formatInt(call.score)}</span> : null}
      </Link>
    </li>
  );
}

function CoachingCardView({ card, onChanged }: { card: CoachingCard; onChanged: () => void }) {
  const t = useT();
  const [disputing, setDisputing] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const responded = card.op_response;

  async function respond(response: "acknowledged" | "disputed", body?: string) {
    setBusy(true);
    setErr(null);
    try {
      await flaskFetch(`/api/v1/call-analysis/cards/${card.card_id}/respond`, {
        method: "POST",
        body: response === "disputed" ? { response, reason: body } : { response },
      });
      onChanged();
    } catch (e) {
      setErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
      setBusy(false);
    }
  }

  return (
    <Card>
      {!responded ? (
        <div className="text-[11px] font-semibold uppercase tracking-[0.6px] text-primary">{t("callsboard.my.newCard")}</div>
      ) : null}

      <div className="mt-2 space-y-2.5">
        {card.tips.map((tip, i) => (
          <div key={i} className="rounded-ctl border-l-[3px] border-l-primary bg-surface px-3.5 py-2.5">
            {tip.ts ? <span className="mr-2 font-mono text-[12px] text-steel">{tip.ts}</span> : null}
            <span className="text-[14px] leading-relaxed text-ink">{tip.text}</span>
          </div>
        ))}
      </div>

      {err ? <div className="mt-2 text-[12px] text-neg">{err}</div> : null}

      {responded ? (
        <div className="mt-3 text-[13px] font-medium text-steel">
          {responded === "disputed" ? t("callsboard.my.disputed") : t("callsboard.my.acknowledged")}
        </div>
      ) : disputing ? (
        <div className="mt-3">
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("callsboard.my.disagree.placeholder")}
            rows={2}
          />
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="brand" loading={busy} disabled={!reason.trim()} onClick={() => respond("disputed", reason.trim())}>
              {t("callsboard.my.disagree.send")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setDisputing(false)}>
              {t("callsboard.my.disagree.cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="primary" loading={busy} onClick={() => respond("acknowledged")}>
            {t("callsboard.my.acknowledge")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setDisputing(true)}>
            {t("callsboard.my.disagree")}
          </Button>
        </div>
      )}
    </Card>
  );
}
