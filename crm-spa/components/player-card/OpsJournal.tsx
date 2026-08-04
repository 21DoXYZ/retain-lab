"use client";

import { useState } from "react";
import { Card, Tabs } from "@/components/ui";
import { useT } from "@/lib/i18n";
import type { UserRole } from "@/lib/types";
import { canSeePlayerAnalysis } from "@/components/call-analysis/labels";
import { CallAnalysisTab } from "./CallAnalysisTab";
import { NotesBlock } from "./NotesBlock";

/**
 * OpsJournal — объединённый блок «Звонки — анализ» + «📝 Заметки» (запрос
 * владельца): один Card с табами вместо двух сворачиваемых секций в хвосте
 * карточки. Встаёт на место бывшего блока «Звонок» (левая колонка грида).
 * Гейты прежние: анализ — только роли из canSeePlayerAnalysis, заметки —
 * sections.notes; если доступен один таб — рендерится без переключателя.
 */
interface OpsJournalProps {
  playerId: number;
  meId: string;
  meRole: UserRole;
  canWriteNote: boolean;
  currentOffer: string | null;
  showNotes: boolean;
  calls: import("./types").CallRow[];
  notes: import("./types").NoteRow[];
  names: Map<string, string>;
  onChanged: () => void;
}

export function OpsJournal({
  playerId,
  meId,
  meRole,
  canWriteNote,
  currentOffer,
  showNotes,
  calls,
  notes,
  names,
  onChanged,
}: OpsJournalProps) {
  const t = useT();
  const showAnalysis = canSeePlayerAnalysis(meRole);
  const tabs = [
    ...(showAnalysis ? [{ key: "analysis", label: `${t("calls.tab.title")} (${calls.length})` }] : []),
    ...(showNotes ? [{ key: "notes", label: `${t("card.notes.title")} (${notes.length})` }] : []),
  ];
  const [tab, setTab] = useState(tabs[0]?.key ?? "notes");
  if (tabs.length === 0) return null;
  const active = tabs.some((x) => x.key === tab) ? tab : tabs[0].key;

  return (
    <Card>
      {tabs.length > 1 ? <Tabs tabs={tabs} value={active} onChange={setTab} /> : (
        <div className="text-[13.5px] font-medium text-ink">{tabs[0].label}</div>
      )}
      <div className="mt-2">
        {active === "analysis" && showAnalysis ? (
          <CallAnalysisTab embedded role={meRole} meId={meId} calls={calls} names={names} />
        ) : showNotes ? (
          <NotesBlock
            embedded
            playerId={playerId}
            meId={meId}
            meRole={meRole}
            canWrite={canWriteNote}
            currentOffer={currentOffer}
            notes={notes}
            names={names}
            onChanged={onChanged}
          />
        ) : null}
      </div>
    </Card>
  );
}
