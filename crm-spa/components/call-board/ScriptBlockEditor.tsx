"use client";

import { Badge, Select } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { useCheckLabel, useImportanceLabel, useCriterionLabel, CRITERIA, CHECK_LEVELS, IMPORTANCE } from "./kit";
import type { ScriptBlock, CheckLevel, Importance } from "./types";

/**
 * Один блок скрипта в разметке (§10.8). Разметка по БЛОКАМ, не по словам:
 * уровень проверки + «это шаг» (из 9 канонических) + важность; для «Дословно» —
 * формы слов (их выбирает носитель) и «в пределах N слов». Иммутабельно: onChange
 * возвращает НОВЫЙ объект блока.
 */
export function ScriptBlockEditor({
  index,
  block,
  onChange,
}: {
  index: number;
  block: ScriptBlock;
  onChange: (next: ScriptBlock) => void;
}) {
  const t = useT();
  const checkLabel = useCheckLabel();
  const importanceLabel = useImportanceLabel();
  const criterionLabel = useCriterionLabel();
  const level = (block.check_level ?? "meaning") as CheckLevel;

  const set = (patch: Partial<ScriptBlock>) => onChange({ ...block, ...patch });

  return (
    <div className="rounded-card border border-hair2 bg-canvas px-5 py-4">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[14px] font-semibold text-ink">
          {t("callsboard.script.block", { n: index + 1 })}
          {block.title ? <span className="ml-2 font-normal text-steel">· {block.title}</span> : null}
        </div>
        {block.legal_proposed ? <Badge bg="#fef3c7" fg="#92400e">⚠ {t("callsboard.script.proposed")}</Badge> : null}
      </div>

      {block.text ? (
        <blockquote className="mt-2 rounded-ctl bg-surface px-3.5 py-2 font-mono text-[13px] leading-relaxed text-slate">
          «{block.text}»
        </blockquote>
      ) : null}

      {/* Уровень проверки */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-[12.5px] font-medium text-slate">{t("callsboard.script.check")}</span>
        {CHECK_LEVELS.map((lvl) => (
          <button
            key={lvl}
            type="button"
            onClick={() => set({ check_level: lvl })}
            className={
              "rounded-full border px-3 py-1 text-[12.5px] cursor-pointer transition-colors " +
              (level === lvl ? "bg-ink text-white border-ink" : "bg-canvas text-steel border-hair2 hover:border-primary")
            }
          >
            {checkLabel(lvl)}
          </button>
        ))}
      </div>

      {level === "meaning" ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-medium text-slate">{t("callsboard.script.isStep")}</span>
            <Select value={block.criterion ?? ""} onChange={(e) => set({ criterion: e.target.value || null })}>
              <option value="">{t("callsboard.script.stepNone")}</option>
              {CRITERIA.map((c) => (
                <option key={c} value={c}>{criterionLabel(c)}</option>
              ))}
            </Select>
          </label>
          <div className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-medium text-slate">{t("callsboard.script.importance")}</span>
            <div className="flex flex-wrap items-center gap-2">
              {IMPORTANCE.map((imp) => (
                <button
                  key={imp}
                  type="button"
                  onClick={() => set({ importance: imp as Importance })}
                  className={
                    "rounded-full border px-3 py-1 text-[12.5px] cursor-pointer transition-colors " +
                    ((block.importance ?? "normal") === imp ? "bg-ink text-white border-ink" : "bg-canvas text-steel border-hair2 hover:border-primary")
                  }
                >
                  {importanceLabel(imp)}
                </button>
              ))}
              {block.weight_pct != null ? (
                <span className="font-mono text-[12.5px] text-steel">{t("callsboard.script.weightHint", { pct: `${block.weight_pct}%` })}</span>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {level === "verbatim" ? <VerbatimFields block={block} set={set} /> : null}

      {level === "none" ? <p className="mt-3 text-[12.5px] text-steel">ⓘ {t("callsboard.script.noneNote")}</p> : null}
    </div>
  );
}

function VerbatimFields({ block, set }: { block: ScriptBlock; set: (p: Partial<ScriptBlock>) => void }) {
  const t = useT();
  const forms = block.word_forms ?? [];

  const updateForm = (i: number, v: string) => {
    const next = forms.map((f, idx) => (idx === i ? v : f));
    set({ word_forms: next });
  };
  const addForm = () => set({ word_forms: [...forms, ""] });

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12.5px] font-medium text-slate">{t("callsboard.script.wordForms")}</span>
        {forms.map((f, i) => (
          <input
            key={i}
            value={f}
            onChange={(e) => updateForm(i, e.target.value)}
            placeholder={t("callsboard.script.formPlaceholder")}
            className="h-8 w-28 rounded-ctl border border-hair3 bg-canvas px-2 font-mono text-[12.5px] outline-none focus:border-2 focus:border-primary"
          />
        ))}
        <button type="button" onClick={addForm} className="text-[12.5px] text-primary hover:underline cursor-pointer">
          {t("callsboard.script.addForm")}
        </button>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span className="text-[12.5px] font-medium text-slate">{t("callsboard.script.within")}</span>
        <input
          type="number"
          min={1}
          value={block.within_words ?? ""}
          onChange={(e) => set({ within_words: e.target.value ? Number(e.target.value) : null })}
          className="h-8 w-16 rounded-ctl border border-hair3 bg-canvas px-2 font-mono text-[12.5px] outline-none focus:border-2 focus:border-primary"
        />
        <span className="text-[12.5px] text-steel">{t("callsboard.script.withinUnit")}</span>
      </div>
      <p className="mt-2 text-[12.5px] text-steel">ⓘ {t("callsboard.script.verbatimNote")}</p>
    </div>
  );
}
