"use client";

import { SCard } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { SectionShell } from "./SectionShell";
import { KGrid } from "./ui";
import { fmtPctWhole } from "./format";
import type { Section } from "./hooks";
import type { LtvData, LadderBlock } from "./types";

/**
 * 🪜 Прогресс по депозитам — /players/<id>/ltv (ladder block). Board «Прогресс по
 * депозитам» kc tiles + steps strip (player_board.py line 1477): Сейчас / P(след.
 * деп) персон. / по базе на ступени / Цель, plus the deposit-conversion ladder
 * with the current step highlighted. Rendered ONLY for depositors (board omits
 * prog_sec when dep_count < 1). Shares the /ltv fetch with LtvSection.
 */
function LadderView({ ladder }: { ladder: LadderBlock }) {
  const t = useT();
  return (
    <div className="flex flex-col gap-2.5">
      <KGrid>
        {/* Подсказки — board SCARD_TIP (player_board.py:1317-1320). */}
        <SCard
          label={t("analytics.ladder.current")}
          value={t("analytics.ladder.depositN", { n: ladder.current })}
          title={t("card.tip.scard.current")}
        />
        <SCard
          label={t("analytics.ladder.pNextPersonal")}
          value={fmtPctWhole(ladder.p_next_personal)}
          valueTone="pos"
          title={t("card.tip.scard.pNextPersonal")}
        />
        <SCard
          label={t("analytics.ladder.pNextBase")}
          value={fmtPctWhole(ladder.p_next_base)}
          title={t("card.tip.scard.pNextBase")}
        />
        <SCard
          label={t("analytics.ladder.target")}
          value={t("analytics.ladder.depositN", { n: ladder.target })}
          variant="cream"
          title={t("card.tip.scard.target")}
        />
      </KGrid>
      {ladder.steps.length ? (
        <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
          {ladder.steps.map((s) => {
            const cur = s.deposit_no === ladder.current;
            return (
              <span
                key={s.deposit_no}
                className={
                  cur
                    ? "rounded-full bg-primary text-white px-2.5 py-[3px] font-semibold"
                    : "rounded-full bg-cream text-slate px-2.5 py-[3px]"
                }
              >
                {s.deposit_no}→{fmtPctWhole(s.conv_pct)}
              </span>
            );
          })}
        </div>
      ) : null}
      <div className="text-[13px] text-steel leading-relaxed">
        {t("analytics.ladder.footnote", { target: ladder.target })}
      </div>
    </div>
  );
}

export function LadderSection({ section }: { section: Section<LtvData> }) {
  const t = useT();
  // Board omits «Прогресс по депозитам» for non-depositors → hide the whole section.
  if (section.state === "data" && section.data && !section.data.ladder) return null;

  return (
    <SectionShell title={t("analytics.ladder.title")} caption={t("analytics.ladder.caption")} section={section}>
      {(d) => (d.ladder ? <LadderView ladder={d.ladder} /> : null)}
    </SectionShell>
  );
}
