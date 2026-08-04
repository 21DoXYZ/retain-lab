"use client";

import { useState } from "react";
import { PageHeader, Pill, PillRow } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { ExportsJournal } from "./ExportsJournal";
import { ExportsDetail } from "./ExportsDetail";

/**
 * /exports — «Проверка выгрузок» (C5). Journal of lists handed to the call-center
 * and the per-list result. The list ↔ detail switch is local state (the board
 * uses ?exp&seg query params on the same page); no extra route is declared.
 */

interface Selection {
  exp: string;
  seg: string;
}

export function ExportsScreen() {
  const t = useT();
  const [selected, setSelected] = useState<Selection | null>(null);

  if (selected) {
    return (
      <ExportsDetail
        exp={selected.exp}
        seg={selected.seg}
        onBack={() => setSelected(null)}
      />
    );
  }

  return (
    <>
      <PageHeader
        title={t("monitor.exportsScreen.title")}
        accent={t("monitor.exportsScreen.accent")}
        lead={t("monitor.exportsScreen.lead")}
        right={
          <PillRow>
            <Pill live>{t("monitor.pill.live")}</Pill>
          </PillRow>
        }
      />
      <ExportsJournal onOpen={(exp, seg) => setSelected({ exp, seg })} />
    </>
  );
}
