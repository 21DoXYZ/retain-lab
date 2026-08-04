"use client";

import { useState } from "react";
import Link from "next/link";
import { PageHeader, Card, Badge, ErrorState, EmptyState } from "@/components/ui";
import { useT } from "@/lib/i18n";
import {
  useCallResource,
  useCriterionLabel,
  formatFraction,
} from "./kit";
import { PeriodSelect, usePeriodQuery } from "./ui";
import type { WhatWorksData, Step } from "./types";

/**
 * Что работает (§10.6) — какой шаг переписать; чей приём раздать. Ранжирование
 * ПО РЕЗУЛЬТАТУ (принятые офферы), не по баллу — шапка обязательна. Приём в
 * TR-оригинале + перевод. «Собрать черновик» / «Раздать команде» НЕ реализованы
 * (нет ручек в бэкенде) — кнопок нет, см. отчёт. Роли: head_retention, super_admin.
 */
export function WhatWorksScreen() {
  const t = useT();
  const [days, setDays] = useState(7);
  const period = usePeriodQuery(days);   // стабильный путь — НЕ periodQuery() в аргументе
  const { state, data, error, reload } = useCallResource<WhatWorksData>(
    `/api/v1/call-analysis/what-works?${period}`,
  );
  const loading = state !== "data";

  return (
    <>
      <PageHeader title={t("callsboard.whatworks.title")} right={<PeriodSelect value={days} onChange={setDays} />} />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : loading ? (
        <div className="mt-6 space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-card bg-hair2/50" />
          ))}
        </div>
      ) : !data || data.steps.length === 0 ? (
        <div className="mt-8">
          <EmptyState title={t("callsboard.whatworks.empty")} />
        </div>
      ) : (
        <>
          {/* §10.6: шапка стоит на экране, а не в документации. */}
          <div className="mt-5 rounded-card border border-beige bg-cream px-[18px] py-[15px]">
            <div className="text-[14px] font-semibold text-ink">{t("callsboard.whatworks.bestByResult")}</div>
            <div className="mt-1.5 text-[13.5px] text-slate">
              {data.ranking
                .filter((r) => r.accept_rate != null)
                .map((r) =>
                  t("callsboard.whatworks.ranking.item", {
                    name: r.operator_name ?? r.operator_id.slice(0, 8),
                    rate: formatFraction(r.accept_rate),
                  }),
                )
                .join(" · ") || "—"}
            </div>
          </div>

          <div className="mt-5 space-y-4">
            {data.steps.map((step) => (
              <StepCard key={step.criterion} step={step} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function StepCard({ step }: { step: Step }) {
  const t = useT();
  const criterionLabel = useCriterionLabel();
  const best = step.best_operator;
  const example = best?.examples?.[0];

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[15px] font-semibold text-ink">
          {t("callsboard.whatworks.step", { name: criterionLabel(step.criterion) })}
        </div>
        {step.enough_data ? (
          <Badge bg="#dcfce7" fg="#166534">{t("callsboard.whatworks.step.norm")}</Badge>
        ) : (
          <Badge bg="#fef3c7" fg="#92400e">{t("callsboard.whatworks.step.notEnough")}</Badge>
        )}
      </div>

      {!step.enough_data ? (
        <p className="mt-2 text-[13.5px] text-steel">
          {t("callsboard.whatworks.notEnough.body", { talks: step.talks })}
        </p>
      ) : (
        <>
          {step.team_coverage != null ? (
            <p className="mt-2 text-[13.5px] text-slate">
              {t("callsboard.whatworks.teamCoverage", { pct: formatFraction(step.team_coverage) })}
            </p>
          ) : null}

          {best && example ? (
            <>
              <p className="mt-1 text-[13px] text-steel">
                {t("callsboard.whatworks.best", { name: best.operator_name ?? best.operator_id.slice(0, 8) })}
              </p>
              {example.quote_translation ? (
                <div className="mt-2.5">
                  <div className="text-[12px] font-medium text-steel">
                    {t("callsboard.whatworks.saysTranslation", { name: best.operator_name ?? "" })}
                  </div>
                  <blockquote className="mt-1 rounded-ctl border-l-[3px] border-l-primary bg-surface px-3.5 py-2.5 text-[14px] leading-relaxed text-ink">
                    «{example.quote_translation}»
                  </blockquote>
                </div>
              ) : null}
              {example.quote_tr ? (
                <div className="mt-2 text-[13px] text-steel">
                  {t("callsboard.whatworks.original")}{" "}
                  <span className="font-mono text-slate">«{example.quote_tr}»</span>
                </div>
              ) : null}
              <div className="mt-3">
                <Link href={`/call-analysis/calls/${example.call_id}`} className="text-primary font-medium text-[13px] hover:underline">
                  {t("callsboard.whatworks.listen")} →
                </Link>
              </div>
            </>
          ) : (
            <p className="mt-2 text-[13.5px] text-steel">{t("callsboard.whatworks.noExamples")}</p>
          )}
        </>
      )}
    </Card>
  );
}
