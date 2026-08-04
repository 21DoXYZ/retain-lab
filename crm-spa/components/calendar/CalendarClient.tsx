"use client";

import { useRouter } from "next/navigation";
import { PageHeader, Eyebrow, Panel, ErrorState } from "@/components/ui";
import { useT, type Locale } from "@/lib/i18n";
import { DayPlan } from "./DayPlan";
import { AutoPlan } from "./AutoPlan";
import { HeadSummary } from "./HeadSummary";
import type { AutoPlanCandidate, DayPlanRow, OperatorSummary } from "./types";

/**
 * Client root for /calendar. Renders either the operator day plan + auto-plan, or
 * the head-of-department per-operator summary. All copy comes through useT().
 *
 * i18n-провайдер живёт ГЛОБАЛЬНО в app/(app)/layout.tsx — здесь его оборачивать
 * НЕЛЬЗЯ: вложенный провайдер держал бы свой useState(initialLocale) и не
 * реагировал бы на переключатель языка в шапке (он меняет state внешнего).
 */

export interface CalendarClientProps {
  /** @deprecated локаль раздаёт глобальный I18nProvider; проп оставлен для совместимости вызова. */
  locale?: Locale;
  isHead: boolean;
  /** Server-side load failed → render an error state with retry. */
  error?: boolean;
  dayPlan: DayPlanRow[];
  autoPlan: AutoPlanCandidate[];
  summary: OperatorSummary[];
}

export function CalendarClient({ isHead, error, dayPlan, autoPlan, summary }: CalendarClientProps) {
  const t = useT();
  const router = useRouter();

  return (
    <>
      <PageHeader
        title={t("calendar.title")}
        lead={isHead ? t("calendar.lead.head") : t("calendar.lead.operator")}
      />

      {error ? (
        <div className="mt-6">
          <Panel>
            <ErrorState
              title={t("common.loadFailed")}
              description={t("common.loadFailedDesc")}
              retryLabel={t("common.retry")}
              onRetry={() => router.refresh()}
            />
          </Panel>
        </div>
      ) : isHead ? (
        <div className="mt-6">
          <Eyebrow>{t("calendar.summary.title")}</Eyebrow>
          <Panel>
            <HeadSummary rows={summary} />
          </Panel>
        </div>
      ) : (
        <div className="mt-6 space-y-8">
          <DayPlan rows={dayPlan} />

          <section>
            <Eyebrow>{t("calendar.autoplan.title")}</Eyebrow>
            <p className="text-[13px] text-steel mb-3 max-w-2xl leading-relaxed">
              {t("calendar.autoplan.hint")}
            </p>
            <AutoPlan candidates={autoPlan} />
          </section>
        </div>
      )}
    </>
  );
}
