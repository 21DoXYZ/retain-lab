"use client";

import { useEffect, useMemo, useState } from "react";
import { Card, Button, Badge, Input, EmptyState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import { useDow } from "@/lib/dow";
import { flaskFetch } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { addSchedule, cardErrorText } from "./data";
import type { PlayerHeatmap, ScheduledRow, SchedStatus } from "./types";

/**
 * "Запланировать следующий звонок" — a block IN the card (owner decision), not a
 * separate screen (plan §6). Date+time+comment → crm.scheduled_calls. Autosuggest
 * (ТЗ п.5.3): read the player heatmap (A3) and propose the busiest weekday/hour
 * ("обычно активен чт 19–22"); the operator accepts or picks their own.
 */
interface ScheduleBlockProps {
  playerId: number;
  meId: string;
  scheduled: ScheduledRow[];
  onChanged: () => void;
  /** Highlight + expand after a "недозвон" (ТЗ п.3.3). */
  nudge?: boolean;
}

const SCHED_TONE: Record<SchedStatus, { bg: string; fg: string; labelKey: MessageKey }> = {
  planned: { bg: "#eff6ff", fg: "#1d4ed8", labelKey: "card.schedule.status.planned" },
  done: { bg: "#ecfdf5", fg: "#047857", labelKey: "card.schedule.status.done" },
  overdue: { bg: "#fef2f2", fg: "#b91c1c", labelKey: "card.schedule.status.overdue" },
  missed: { bg: "#fffbeb", fg: "#b45309", labelKey: "card.schedule.status.missed" },
};

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Date → value for <input type="datetime-local"> (local wall time). */
function toLocalInputValue(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Next occurrence (from tomorrow) of a weekday (0=Mon..6=Sun) at `hour`. */
function nextSlot(dowMonday0: number, hour: number): Date {
  const jsTarget = (dowMonday0 + 1) % 7; // JS: 0=Sun..6=Sat
  const d = new Date();
  d.setHours(hour, 0, 0, 0);
  d.setDate(d.getDate() + 1);
  for (let i = 0; i < 7; i++) {
    if (d.getDay() === jsTarget) break;
    d.setDate(d.getDate() + 1);
  }
  return d;
}

/** Рекомендация «когда звонить» из модуля анализа (retry-правило + пик игрока). */
interface WhenToCall {
  rec_id: string;
  kind: "best_time" | "retry";
  slot: string;
  basis: string;
  context: { retry_hours?: number; peak_hour?: number | null; peak_day?: string | null };
}

export function ScheduleBlock({ playerId, meId, scheduled, onChanged, nudge }: ScheduleBlockProps) {
  const t = useT();
  const dowLabel = useDow();
  const [when, setWhen] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [heatmap, setHeatmap] = useState<PlayerHeatmap | null>(null);
  // рекомендация тайминга + id принятой (для фиксации исхода — обучающие данные)
  const [rec, setRec] = useState<WhenToCall | null>(null);
  const [acceptedRecId, setAcceptedRecId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // Рекомендация «когда звонить»: сама фиксируется на бэке (analyzer). Учитывает
    // недозвон (перезвонить через N ч) — heatmap этого не знает. Опционально.
    flaskFetch<WhenToCall>(`/api/v1/call-analysis/players/${playerId}/when-to-call`)
      .then((r) => {
        if (alive) setRec(r);
      })
      .catch(() => {
        /* модуль анализа мог быть недоступен роли — тихо */
      });
    flaskFetch<PlayerHeatmap>(`/api/v1/players/${playerId}/heatmap`)
      .then((h) => {
        if (alive) setHeatmap(h);
      })
      .catch(() => {
        /* autosuggest is optional — silent on failure */
      });
    return () => {
      alive = false;
    };
  }, [playerId]);

  // Busiest (weekday, hour) cell from the heatmap for the concrete slot.
  const suggestion = useMemo(() => {
    const cells = heatmap?.heatmap?.hm ?? [];
    if (cells.length === 0) return null;
    let best = cells[0];
    for (const c of cells) if (c[2] > best[2]) best = c;
    const [hour, dow] = best;
    const slot = nextSlot(dow, hour);
    return {
      slot,
      label: heatmap?.stats?.peak_day
        ? t("card.schedule.suggestionAround", {
            // peak_day приходит русской подписью (board DOW_RU) → переводим по коду
            day: dowLabel(heatmap.stats.peak_day),
            hour: heatmap.stats.peak_hour,
          })
        : `${formatDateTime(slot)}`,
    };
  }, [heatmap, t, dowLabel]);

  function applySuggestion() {
    if (suggestion) {
      setWhen(toLocalInputValue(suggestion.slot));
      if (!comment) setComment(t("card.schedule.autoComment"));
    }
  }

  /** Текст рекомендации «когда звонить»: перезвон после недозвона / лучшее время. */
  const recLabel = useMemo(() => {
    if (!rec) return null;
    if (rec.kind === "retry") {
      return t("card.schedule.rec.retry", { hours: rec.context.retry_hours ?? 4 });
    }
    const day = rec.context.peak_day ? dowLabel(rec.context.peak_day) : "";
    const hour = rec.context.peak_hour;
    return t("card.schedule.rec.bestTime", { day, hour: hour == null ? "—" : `${hour}:00` });
  }, [rec, t, dowLabel]);

  function applyRec() {
    if (!rec) return;
    setWhen(toLocalInputValue(new Date(rec.slot)));
    setAcceptedRecId(rec.rec_id);          // зафиксируем принятие при сохранении
    if (!comment) setComment(t("card.schedule.autoComment"));
  }

  async function submit() {
    if (!when) {
      setError(t("card.schedule.missingDateTime"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await addSchedule({
        playerId,
        operatorId: meId,
        scheduledAt: new Date(when).toISOString(),
        comment: comment.trim() || null,
      });
      // если планировали по рекомендации — фиксируем принятие СО СВЯЗКОЙ на
      // созданный звонок (иначе исход рекомендации потом не сверить)
      if (acceptedRecId) {
        flaskFetch(`/api/v1/call-analysis/recommendations/${acceptedRecId}/accept`, {
          method: "POST",
          body: { schedule_id: created.id },
        }).catch(() => {
          /* фиксация не критична для оператора — тихо */
        });
        setAcceptedRecId(null);
      }
      setWhen("");
      setComment("");
      onChanged();
    } catch (e) {
      setError(cardErrorText(e, t, "card.common.error"));
    } finally {
      setBusy(false);
    }
  }

  const upcoming = scheduled.filter((s) => s.status === "planned" || s.status === "overdue");

  return (
    <Card className={nudge ? "border-primary border-[1.5px]" : undefined}>
      <div className="text-sm font-semibold text-ink">{t("card.schedule.title")}</div>
      {nudge ? (
        <div className="mt-2 rounded-ctl bg-cream border border-beige px-3 py-2 text-[12.5px] text-slate">
          {t("card.schedule.nudgeHint")}
        </div>
      ) : null}

      {/* Рекомендация модели «когда звонить» — приоритетнее эвристики heatmap:
          знает про недозвон (перезвонить через N ч). */}
      {recLabel ? (
        <div className="mt-3 flex items-center justify-between gap-3 flex-wrap rounded-ctl border border-primary/40 bg-primary/5 px-3 py-2">
          <div className="text-[12.5px] text-slate">
            {rec?.kind === "retry" ? "🔁 " : "⭐ "}
            {recLabel}
          </div>
          <Button size="sm" variant="brand" onClick={applyRec}>
            {t("card.schedule.rec.apply")}
          </Button>
        </div>
      ) : null}

      {suggestion ? (
        <div className="mt-3 flex items-center justify-between gap-3 flex-wrap rounded-ctl bg-surface px-3 py-2">
          <div className="text-[12.5px] text-slate">
            {t("card.schedule.suggestionPrefix")} <b>{suggestion.label}</b>
          </div>
          <Button size="sm" variant="ghost" onClick={applySuggestion}>
            {t("card.schedule.applySuggestion")}
          </Button>
        </div>
      ) : null}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Input
          type="datetime-local"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
          aria-label={t("card.schedule.dateTimeAriaLabel")}
        />
        <Input
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={t("card.schedule.commentPlaceholder")}
        />
      </div>

      <div className="mt-2 flex items-center justify-between gap-3">
        {error ? <span className="text-[12.5px] text-neg">{error}</span> : <span />}
        <Button variant="brand" size="sm" onClick={submit} loading={busy}>
          {t("card.schedule.submitButton")}
        </Button>
      </div>

      {/* Upcoming touches for this player */}
      <div className="mt-4">
        <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel mb-2">
          {t("card.schedule.upcomingTitle")}
        </div>
        {upcoming.length === 0 ? (
          <EmptyState icon="🗓" title={t("card.schedule.emptyTitle")} className="py-8" />
        ) : (
          <ul className="flex flex-col divide-y divide-hair">
            {upcoming.map((s) => {
              const tone = SCHED_TONE[s.status];
              return (
                <li key={s.id} className="py-2.5 flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <div className="text-[13.5px] font-medium text-ink">
                      {formatDateTime(s.scheduled_at)}
                    </div>
                    {s.comment ? (
                      <div className="text-[12.5px] text-steel">{s.comment}</div>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    {s.by_system ? (
                      <span className="text-[11.5px] text-stone">{t("card.schedule.bySystem")}</span>
                    ) : null}
                    <Badge bg={tone.bg} fg={tone.fg}>
                      {t(tone.labelKey)}
                    </Badge>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}
