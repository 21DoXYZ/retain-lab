"use client";

import {
  PageHeader,
  Eyebrow,
  Panel,
  Banner,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  ErrorState,
  SkeletonText,
} from "@/components/ui";
import { useT } from "@/lib/i18n";
import { useResource } from "./kit";
import type { FormulasData, FormulaCell } from "./types";

/**
 * /formulas — «Формулы расчётов» (paritet с formulas() борда). Все вычисления
 * системы по слоям; текст 1-в-1 со статическим HTML. Ячейки-формулы рендерятся
 * моноширинно (FormulaCell.code). Справочная: любой аутентифицированный.
 */

function Cell({ cell }: { cell: FormulaCell }) {
  return cell.code ? (
    <span className="font-mono text-[12.5px] text-ink">{cell.text}</span>
  ) : (
    <span>{cell.text}</span>
  );
}

export function FormulasScreen() {
  const t = useT();
  const { state, data, error, reload } = useResource<FormulasData>("/api/v1/formulas");
  const loading = state === "loading";
  const d = data;

  return (
    <>
      <PageHeader
        title={t("monitor.formulas.title")}
        accent={t("monitor.formulas.accent")}
        lead={d?.lead ?? t("monitor.formulas.leadFallback")}
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : loading ? (
        <Panel className="mt-6 p-5">
          <SkeletonText lines={10} />
        </Panel>
      ) : (
        <>
          {(d?.sections ?? []).map((section) => (
            <div key={section.title}>
              <Eyebrow>{section.title}</Eyebrow>
              <Panel>
                <Table>
                  <THead>
                    <TR>
                      {section.cols.map((c) => (
                        <TH key={c} className="text-left first:text-left">
                          {c}
                        </TH>
                      ))}
                    </TR>
                  </THead>
                  <TBody>
                    {section.rows.map((row, ri) => (
                      <TR key={ri}>
                        {row.map((cell, ci) => (
                          <TD key={ci} className="text-left first:text-left align-top whitespace-normal">
                            <Cell cell={cell} />
                          </TD>
                        ))}
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </Panel>
            </div>
          ))}

          {d?.note ? <Banner>{d.note}</Banner> : null}
        </>
      )}
    </>
  );
}
