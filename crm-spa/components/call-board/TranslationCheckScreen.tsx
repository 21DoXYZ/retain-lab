"use client";

import { useMemo, useState } from "react";
import { PageHeader, Card, Button, Textarea, ErrorState, EmptyState } from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useCallResource, formatDuration } from "./kit";
import { AudioPlayer } from "./AudioPlayer";
import type { TranslationNextData, TranscriptWord } from "./types";

/**
 * Проверка перевода (§10.11) — сверить текст с записью. Рабочий язык TR (через
 * словарь). Никаких баллов и критериев — только текст и запись. После ответа —
 * автопереход к следующему. Роли: translation_reviewer, super_admin.
 *
 * NB: аудио-эндпойнт в бэкенде гейтится MANAGE|ADMIN — для translation_reviewer
 * плеер отдаёт «нет доступа» (см. отчёт/вопросы). super_admin слушает штатно.
 */
interface Segment {
  role: string;
  start: number | null;
  text: string;
}

export function TranslationCheckScreen() {
  const t = useT();
  const { state, data, error, reload } = useCallResource<TranslationNextData>("/api/v1/call-analysis/translation-check/next");
  const loading = state !== "data";

  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  const call = data?.call ?? null;
  const segments = useMemo(() => (call ? buildSegments(call.words) : []), [call]);

  async function submit(match: boolean) {
    if (!call) return;
    setBusy(true);
    setSubmitErr(null);
    try {
      await flaskFetch(`/api/v1/call-analysis/translation-check/${call.call_id}`, {
        method: "POST",
        body: { match, note: note.trim() || undefined },
      });
      setNote("");
      reload(); // автопереход к следующему
    } catch (e) {
      setSubmitErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={t("callsboard.translation.title")}
        accent={data ? t("callsboard.translation.remaining", { n: data.remaining }) : undefined}
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : loading ? (
        <div className="mt-6 h-64 animate-pulse rounded-card bg-hair2/50" />
      ) : !call ? (
        <div className="mt-8">
          <EmptyState icon="✅" title={t("callsboard.translation.done.title")} description={t("callsboard.translation.done.body")} />
        </div>
      ) : (
        <Card className="mt-6">
          <p className="text-[14px] font-medium text-slate">{t("callsboard.translation.prompt")}</p>

          {/* Поверхность транскрипта — самая светлая, максимальный контраст (§13). */}
          <div className="mt-4 rounded-card border border-hair2 bg-white px-4 py-3.5">
            {segments.length ? (
              <div className="space-y-2.5">
                {segments.map((s, i) => (
                  <div key={i} className="flex gap-3">
                    <span className="w-14 flex-none font-mono text-[12px] text-steel">{s.start == null ? "" : formatDuration(s.start)}</span>
                    <span className="w-20 flex-none text-[11px] font-semibold uppercase tracking-[0.5px] text-primary">
                      {roleLabel(s.role, t)}
                    </span>
                    <span className="text-[14.5px] leading-relaxed text-ink">{s.text}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="whitespace-pre-wrap text-[14.5px] leading-relaxed text-ink">{call.text ?? "—"}</p>
            )}
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="brand" loading={busy} onClick={() => submit(true)}>{t("callsboard.translation.match")}</Button>
            <Button variant="ghost" loading={busy} onClick={() => submit(false)}>{t("callsboard.translation.mismatch")}</Button>
          </div>

          <div className="mt-3">
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("callsboard.translation.notePlaceholder")} rows={2} />
          </div>

          {submitErr ? <div className="mt-2 text-[12px] text-neg">{submitErr}</div> : null}

          <div className="mt-4">
            {call.has_audio ? (
              <AudioPlayer key={call.call_id} callId={call.call_id} />
            ) : (
              <div className="rounded-ctl border border-hair2 bg-surface px-4 py-3 text-[13px] text-steel">
                {t("callsboard.translation.noAudio")}
              </div>
            )}
          </div>
        </Card>
      )}
    </>
  );
}

type TFn = ReturnType<typeof useT>;

function roleLabel(role: string, t: TFn): string {
  const r = (role || "").toUpperCase();
  if (r === "AGENT" || r === "OPERATOR") return t("callsboard.translation.role.agent");
  if (r === "PLAYER" || r === "CUSTOMER") return t("callsboard.translation.role.player");
  return role || "";
}

/** Группируем слова в реплики по роли (AGENT/PLAYER) с таймкодом первого слова. */
function buildSegments(words: TranscriptWord[] | null | undefined): Segment[] {
  if (!Array.isArray(words) || words.length === 0) return [];
  const out: Segment[] = [];
  let cur: Segment | null = null;
  for (const w of words) {
    if (!w || typeof w.w !== "string") continue;
    const role = w.role ?? "";
    if (!cur || cur.role !== role) {
      cur = { role, start: typeof w.start === "number" ? w.start : null, text: w.w };
      out.push(cur);
    } else {
      cur.text += ` ${w.w}`;
    }
  }
  return out;
}
