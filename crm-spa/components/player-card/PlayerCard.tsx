"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { flaskFetch, FlaskApiError } from "@/lib/api";
import { useRole } from "@/lib/role-context";
import { Card, SkeletonText, ErrorState, Skeleton } from "@/components/ui";
import { useT, useLocale } from "@/lib/i18n";
import { cardSections } from "./access";
import { CardHeader } from "./CardHeader";
import { RecommendationStrip } from "./RecommendationStrip";
import { OfferBlock } from "./OfferBlock";
import { CallBlock } from "./CallBlock";
import { ScheduleBlock } from "./ScheduleBlock";
import { AnalyticsSlot } from "./AnalyticsSlot";
import { BonusSection } from "@/components/player-analytics/BonusSection";
import { OpsJournal } from "./OpsJournal";
import { fetchOperational, resolveNames, type OperationalData } from "./data";
import type { LoadState, PlayerSummary } from "./types";

/**
 * Player card orchestrator (B3). Owns the page layout: header + operational
 * blocks (call / notes / schedule) + a slot for C2's analytics. Two data
 * sources: Flask summary (analytics/profile, may 404 for a crm-only player) and
 * Supabase crm.* (operational rows, RLS-scoped). Role decides which blocks show
 * (short card for support/affiliate; ops-only for operator).
 */
export function PlayerCard({ playerId }: { playerId: number }) {
  const t = useT();
  // Локаль в зависимостях summary: название/условия/причина оффера приходят из
  // каталога акций ЛОКАЛИЗОВАННЫМИ (заголовок X-Locale) — при смене языка
  // summary надо перезапросить, иначе оффер останется на старом языке.
  const { locale } = useLocale();
  const me = useRole();
  const sections = useMemo(() => cardSections(me.role), [me.role]);

  const [summary, setSummary] = useState<PlayerSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);

  const [op, setOp] = useState<OperationalData | null>(null);
  const [opState, setOpState] = useState<LoadState>("loading");
  const [opError, setOpError] = useState<string | null>(null);
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [nudgeSchedule, setNudgeSchedule] = useState(false);

  // --- summary (Flask) — tolerate 404 (player exists only in crm.*) ---
  // All setState happens in async continuations (loading starts true), so the
  // effect body itself stays free of synchronous setState.
  useEffect(() => {
    let alive = true;
    flaskFetch<PlayerSummary>(`/api/v1/players/${playerId}/summary`)
      .then((s) => {
        if (alive) setSummary(s);
      })
      .catch((e) => {
        // 404 → no analytics for this id; other errors also degrade gracefully.
        if (alive) setSummary(null);
        if (!(e instanceof FlaskApiError)) return;
      })
      .finally(() => {
        if (alive) setSummaryLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [playerId, locale]);

  // --- operational rows (Supabase) + name resolution ---
  // fetchCard is pure (no setState); apply/fail set state only inside promise
  // callbacks, so both the effect and the reload handler stay setState-free in
  // their synchronous bodies. Refreshes keep current data on screen (no skeleton
  // flash on every note add); the initial skeleton is the default "loading".
  const fetchCard = useCallback(async () => {
    const data = await fetchOperational(playerId);
    const ids = [
      ...data.notes.map((n) => n.author_id),
      ...data.calls.map((c) => c.operator_id),
      ...data.assignments.map((a) => a.operator_id),
    ];
    const nameMap = await resolveNames(ids);
    return { data, nameMap };
  }, [playerId]);

  const applyCard = useCallback((r: { data: OperationalData; nameMap: Map<string, string> }) => {
    setOp(r.data);
    setNames(r.nameMap);
    setOpError(null);
    setOpState("data");
  }, []);

  const failCard = useCallback(
    (e: unknown) => {
      setOpError(e instanceof Error ? e.message : t("card.common.loadError"));
      setOpState("error");
    },
    [t],
  );

  /** Reload for event handlers (note added, retry, …) — never blocks the UI. */
  const reload = useCallback(() => {
    fetchCard().then(applyCard).catch(failCard);
  }, [fetchCard, applyCard, failCard]);

  useEffect(() => {
    let alive = true;
    fetchCard()
      .then((r) => {
        if (alive) applyCard(r);
      })
      .catch((e) => {
        if (alive) failCard(e);
      });
    return () => {
      alive = false;
    };
  }, [fetchCard, applyCard, failCard]);

  const alsoWith = useMemo(() => {
    if (!op) return [];
    return op.assignments
      .filter((a) => a.operator_id !== me.id)
      .map((a) => names.get(a.operator_id) ?? t("card.common.operatorFallback", { id: a.operator_id.slice(-4) }));
  }, [op, names, me.id, t]);

  const currentOffer = useMemo(() => {
    const rec = summary?.recommendation;
    if (!rec) return null;
    if (rec.offer_name && rec.offer_name !== "—") return rec.offer_name;
    return rec.bonus ?? null;
  }, [summary]);

  return (
    <div className="flex flex-col gap-5">
      {summaryLoading && !summary ? (
        <Skeleton className="h-10 w-72" />
      ) : (
        <CardHeader playerId={playerId} summary={summary} alsoWith={alsoWith} />
      )}

      {sections.recommendation ? <RecommendationStrip summary={summary} /> : null}

      {/* Ряд 1: Оффер слева · Звонок справа (перекомпоновка по запросу владельца) */}
      {sections.recommendation || sections.call ? (
        <div className={sections.recommendation && sections.call ? "grid gap-5 lg:grid-cols-2" : undefined}>
          {sections.recommendation ? (
            <OfferBlock
              playerId={playerId}
              canWrite={sections.writeNote}
              summary={summary}
              onChanged={reload}
            />
          ) : null}
          {sections.call ? (
            opState === "loading" ? (
              <Card>
                <SkeletonText lines={4} />
              </Card>
            ) : op ? (
              <CallBlock
                playerId={playerId}
                meId={me.id}
                canListenRecording={sections.recording}
                calls={op.calls}
                names={names}
                onChanged={reload}
                onNoAnswer={() => setNudgeSchedule(true)}
              />
            ) : null
          ) : null}
        </div>
      ) : null}

      {/* Ряд 2: объединённый журнал (анализ+заметки) слева — на месте бывшего
          «Звонка»; справа под звонком — план следующего звонка (как был) */}
      {opState === "loading" ? (
        <Card>
          <SkeletonText lines={4} />
        </Card>
      ) : opState === "error" ? (
        <Card>
          <ErrorState description={opError ?? undefined} onRetry={reload} />
        </Card>
      ) : op ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <OpsJournal
            playerId={playerId}
            meId={me.id}
            meRole={me.role}
            canWriteNote={sections.writeNote}
            currentOffer={currentOffer}
            showNotes={sections.notes}
            calls={op.calls}
            notes={op.notes}
            names={names}
            onChanged={reload}
          />
          {sections.schedule ? (
            <ScheduleBlock
              playerId={playerId}
              meId={me.id}
              scheduled={op.scheduled}
              onChanged={reload}
              nudge={nudgeSchedule}
            />
          ) : null}
        </div>
      ) : null}

      {/* Аналитика — порядок борда: LTV → Прогресс → … → Траектория */}
      {sections.analytics ? (
        <AnalyticsSlot playerId={playerId} role={me.role} />
      ) : sections.bonusSection ? (
        /* Оператору — только «Реакция на бонусы» (запрос клиента), без остального слота */
        <div className="mt-6" data-analytics-slot data-player-id={playerId} data-role={me.role}>
          <BonusSection playerId={playerId} />
        </div>
      ) : null}
    </div>
  );
}
