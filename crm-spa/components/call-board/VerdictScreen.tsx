"use client";

import { useState } from "react";
import {
  PageHeader,
  Eyebrow,
  Card,
  Badge,
  Button,
  FormField,
  Input,
  ErrorState,
} from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import {
  useCallResource,
  useCriterionLabel,
  formatFraction,
} from "./kit";
import type { VerdictStatsData } from "./types";

/**
 * Вердикт и веса (§10.13) — можно ли разблокировать; какие критерии решают.
 * Показываем РЕАЛЬНЫЕ цифры без выдуманной цели; ориентиры «из практики похожих
 * систем» подписаны. Кнопка разблокировки НЕ заблокирована порогами — при
 * согласии ниже ориентира предупреждаем (confirm), но не запрещаем. Роли: admin.
 */
export function VerdictScreen() {
  const t = useT();
  const criterionLabel = useCriterionLabel();
  const { state, data, error, reload } = useCallResource<VerdictStatsData>("/api/v1/call-analysis/verdict-stats");
  const loading = state !== "data";

  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actErr, setActErr] = useState<string | null>(null);

  async function unlock() {
    if (!data) return;
    const pct = data.agreement;
    if (pct != null && pct < data.hints.agreement) {
      const ok = window.confirm(
        t("callsboard.verdict.unlock.confirm", {
          pct: formatFraction(pct),
          hint: formatFraction(data.hints.agreement),
        }),
      );
      if (!ok) return;
    }
    setBusy(true);
    setActErr(null);
    try {
      const res = await flaskFetch<{ warning?: string | null }>("/api/v1/call-analysis/verdict/unlock", { method: "POST", body: {} });
      setNotice(res.warning || t("callsboard.verdict.unlocked.done"));
      reload();
    } catch (e) {
      setActErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
    } finally {
      setBusy(false);
    }
  }

  const critEntries = data
    ? Object.entries(data.per_criterion_delta).sort((a, b) => b[1] - a[1])
    : [];

  return (
    <>
      <PageHeader title={t("callsboard.verdict.title")} accent={t("callsboard.verdict.subtitle")} />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : loading ? (
        <div className="mt-6 h-64 animate-pulse rounded-card bg-hair2/50" />
      ) : data ? (
        <>
          {/* «Как это работает» — экран непонятен без механики §7, объясняем на месте */}
          <Card className="mt-6 bg-cream border-beige">
            <div className="text-[13px] font-semibold text-ink mb-1.5">{t("callsboard.verdict.how.title")}</div>
            <ol className="list-decimal ml-5 space-y-1 text-[13px] text-slate">
              <li>{t("callsboard.verdict.how.step1")}</li>
              <li>{t("callsboard.verdict.how.step2")}</li>
              <li>{t("callsboard.verdict.how.step3")}</li>
            </ol>
          </Card>

          <Eyebrow>{t("callsboard.verdict.section")}</Eyebrow>
          <Card>
            <div className="mb-3 flex items-center gap-2">
              {data.verdict_unlocked ? (
                <Badge bg="#dcfce7" fg="#166534">{t("callsboard.verdict.state.unlocked")}</Badge>
              ) : (
                <Badge bg="#e5e7eb" fg="#344054">{t("callsboard.verdict.state.locked")}</Badge>
              )}
            </div>
            <dl className="space-y-1.5">
              <Stat label={t("callsboard.verdict.checked")} value={String(data.checked)} />
              <Stat label={t("callsboard.verdict.random")} value={String(data.random)} />
              <Stat label={t("callsboard.verdict.agreement")} value={formatFraction(data.agreement)} />
              <Stat label={t("callsboard.verdict.avgDelta")} value={data.avg_delta == null ? "—" : data.avg_delta.toFixed(2)} />
              <Stat
                label={t("callsboard.verdict.translationChecked")}
                value={data.translation_verified > 0 ? t("callsboard.verdict.translation.yes", { n: data.translation_verified }) : t("callsboard.verdict.translation.no")}
                warn={data.translation_verified === 0}
              />
            </dl>

            {critEntries.length ? (
              <div className="mt-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-steel">{t("callsboard.verdict.discrepancies")}</div>
                <ul className="mt-2 space-y-1">
                  {critEntries.map(([crit, delta], i) => (
                    <li key={crit} className="flex items-center justify-between text-[13.5px]">
                      <span className="text-slate">{criterionLabel(crit)}</span>
                      <span className="flex items-center gap-2">
                        <span className="font-mono text-ink">{delta.toFixed(2)}</span>
                        {i === 0 ? <span className="text-[12px] text-neg">← {t("callsboard.verdict.worst")}</span> : null}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <p className="mt-4 text-[13px] text-steel">
              ⓘ {t("callsboard.verdict.hints", { delta: data.hints.delta, agreement: formatFraction(data.hints.agreement) })}
            </p>

            {actErr ? <div className="mt-3 text-[12px] text-neg">{actErr}</div> : null}
            {notice ? <div className="mt-3 text-[12.5px] text-primary">{notice}</div> : null}

            {!data.verdict_unlocked ? (
              <div className="mt-4">
                <Button variant="brand" loading={busy} onClick={unlock}>
                  {t("callsboard.verdict.unlock")}
                </Button>
              </div>
            ) : null}
          </Card>

          {/* Динамика согласия по неделям — сходится ли модель, а не только среднее */}
          {data.agreement_weekly.length ? (
            <>
              <Eyebrow>{t("callsboard.verdict.weekly.title")}</Eyebrow>
              <Card>
                <ul className="space-y-1">
                  {data.agreement_weekly.map((w) => (
                    <li key={w.week} className="flex items-center justify-between text-[13.5px]">
                      <span className="font-mono text-steel">{w.week}</span>
                      <span className="text-slate">
                        {t("callsboard.verdict.weekly.row", {
                          checked: w.checked,
                          agreement: w.agreement == null ? "—" : `${w.agreement}%`,
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            </>
          ) : null}

          {/* Последние правки с причинами: ГДЕ модель ошиблась и ПОЧЕМУ —
              прямая наводка на починку промпта, а не голые проценты */}
          {data.recent_disagreements.length ? (
            <>
              <Eyebrow>{t("callsboard.verdict.recent.title")}</Eyebrow>
              <Card>
                <p className="text-[12.5px] text-steel mb-3">{t("callsboard.verdict.recent.caption")}</p>
                <ul className="divide-y divide-hair">
                  {data.recent_disagreements.map((d) => (
                    <li key={`${d.call_id}-${d.at}`} className="py-2.5">
                      <div className="flex items-center justify-between gap-3 flex-wrap">
                        <a href={`/call-analysis/calls/${d.call_id}`} className="font-mono text-[13px] text-primary hover:underline">
                          #{d.call_id.slice(0, 4).toUpperCase()}
                        </a>
                        <span className="font-mono text-[13px] text-ink">
                          {d.model_score ?? "—"} → {d.human_score ?? "—"}
                        </span>
                        <span className="text-[12px] text-steel">{d.reviewer ?? "—"} · {d.at.slice(0, 10)}</span>
                      </div>
                      {d.reason ? (
                        <p className="mt-1 text-[13px] text-slate">«{d.reason}»</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </Card>
            </>
          ) : null}

          <SampleSettings data={data} onSaved={reload} />

          <Eyebrow>{t("callsboard.verdict.exactWeights")}</Eyebrow>
          <Card>
            <p className="text-[13.5px] text-slate">{t("callsboard.verdict.exactWeights.body")}</p>
            <div className="mt-3">
              <Button variant="ghost" disabled title={t("callsboard.verdict.exactWeights.soon")}>
                {t("callsboard.verdict.exactWeights.soon")}
              </Button>
            </div>
          </Card>
        </>
      ) : null}
    </>
  );
}

function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between text-[13.5px]">
      <dt className="text-steel">{label}</dt>
      <dd className={`font-mono ${warn ? "text-neg font-medium" : "text-ink"}`}>{value}</dd>
    </div>
  );
}

function SampleSettings({ data, onSaved }: { data: VerdictStatsData; onSaved: () => void }) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [sample, setSample] = useState(String(data.random_sample_per_day));
  const [minTime, setMinTime] = useState(String(data.min_review_time_s));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  async function save() {
    setBusy(true);
    setErr(null);
    setOk(false);
    try {
      await flaskFetch("/api/v1/call-analysis/settings", {
        method: "POST",
        body: { random_sample_per_day: Number(sample), min_review_time_s: Number(minTime) },
      });
      setOk(true);
      setEditing(false);
      onSaved();
    } catch (e) {
      setErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Eyebrow>{t("callsboard.verdict.sampleSection")}</Eyebrow>
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="font-mono text-[15px] font-semibold text-ink">{t("callsboard.verdict.sample.perDay", { n: data.random_sample_per_day })}</div>
          {!editing ? (
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>{t("callsboard.verdict.sample.configure")}</Button>
          ) : null}
        </div>
        <p className="mt-2 text-[13px] text-steel">{t("callsboard.verdict.sample.body")}</p>

        {editing ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <FormField label={t("callsboard.verdict.sample.label")}>
              <Input type="number" min={0} value={sample} onChange={(e) => setSample(e.target.value)} />
            </FormField>
            <FormField label={t("callsboard.verdict.minReview.label")} hint={t("callsboard.verdict.minReview.hint")}>
              <Input type="number" min={0} value={minTime} onChange={(e) => setMinTime(e.target.value)} />
            </FormField>
            <div className="sm:col-span-2 flex gap-2">
              <Button variant="brand" size="sm" loading={busy} onClick={save}>{t("callsboard.verdict.settings.save")}</Button>
              <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>{t("callsboard.script.cancel")}</Button>
            </div>
          </div>
        ) : null}

        {err ? <div className="mt-2 text-[12px] text-neg">{err}</div> : null}
        {ok ? <div className="mt-2 text-[12.5px] text-primary">{t("callsboard.verdict.settings.saved")}</div> : null}
      </Card>
    </>
  );
}
