"use client";

import { Collapsible, EmptyState, Badge } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { formatDateShort } from "@/lib/format";
import type { UserRole } from "@/lib/types";
import { canSeePlayerAnalysis } from "@/components/call-analysis/labels";
import { OUTCOME_LABELS } from "./access";
import type { CallRow } from "./types";

/**
 * Вкладка «Звонки — анализ» в карточке игрока (§9): разбор живёт рядом с игроком.
 * Данных под связку crm.calls ↔ analyzer.calls в карточке НЕТ (CallRow не несёт
 * analyzer_call_id), поэтому показываем журнал операционных звонков без ссылок на
 * разбор и честно подписываем, что оценки появятся после связки. Гейт — только
 * руководители/аналитик (владельцу баллы по звонкам не показываем).
 *
 * Чтобы дать ссылку «Анализ →» и балл, нужна ручка map crm_call→analyzer_call
 * (см. отчёт). Здесь она не вводится — секция деградирует мягко.
 */
interface CallAnalysisTabProps {
  role: UserRole;
  meId: string;
  calls: CallRow[];
  names: Map<string, string>;
  /** true → только тело (для объединённого блока OpsJournal, без Collapsible). */
  embedded?: boolean;
}

export function CallAnalysisTab({ role, meId, calls, names, embedded = false }: CallAnalysisTabProps) {
  const t = useT();
  if (!canSeePlayerAnalysis(role)) return null;

  function nameOf(id: string): string {
    if (id === meId) return t("calls.common.you");
    return names.get(id) ?? `…${id.slice(-4)}`;
  }

  const body = (
    <>
      {calls.length === 0 ? (
        <EmptyState
          icon="🎧"
          title={t("calls.tab.empty")}
          description={t("calls.tab.emptyDesc")}
          className="py-8"
        />
      ) : (
        <>
          <ul className="flex flex-col divide-y divide-hair">
            {calls.map((c) => (
              <li key={c.id} className="py-2.5 flex items-center justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <div className="text-[12.5px] text-slate">
                    {nameOf(c.operator_id)} · {formatDateShort(c.started_at)}
                    {c.duration_sec != null ? ` · ${c.duration_sec} c` : ""}
                  </div>
                  <div className="mt-0.5">
                    <Badge bg="#eff6ff" fg="#1d4ed8" className="text-[11px]">
                      {t(OUTCOME_LABELS[c.outcome])}
                    </Badge>
                  </div>
                </div>
                <div className="text-[12.5px] text-stone whitespace-nowrap">
                  {t("calls.tab.score")}: {t("calls.tab.noScore")}
                </div>
              </li>
            ))}
          </ul>
          <div className="mt-3 text-[11.5px] text-stone">{t("calls.tab.mappingNote")}</div>
        </>
      )}
    </>
  );
  if (embedded) return body;
  return (
    <Collapsible title={t("calls.tab.title")} count={calls.length} hint={t("calls.tab.hint")}>
      {body}
    </Collapsible>
  );
}
