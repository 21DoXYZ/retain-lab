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
import type { GlossaryData } from "./types";

/**
 * /glossary — «Обозначения (словарь)» (paritet с glossary() борда). Что значит
 * каждое сокращение — простыми словами; текст 1-в-1 со статическим HTML.
 * Справочная: любой аутентифицированный (require_auth() в api/monitor.py).
 */
export function GlossaryScreen() {
  const t = useT();
  const { state, data, error, reload } = useResource<GlossaryData>("/api/v1/glossary");
  const loading = state === "loading";
  const d = data;

  return (
    <>
      <PageHeader
        title={t("monitor.glossary.title")}
        accent={t("monitor.glossary.accent")}
        lead={t("monitor.glossary.lead")}
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
                      <TH className="text-left first:text-left">{t("monitor.glossary.col.term")}</TH>
                      <TH className="text-left first:text-left">{t("monitor.glossary.col.full")}</TH>
                      <TH className="text-left first:text-left">{t("monitor.glossary.col.plain")}</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {section.rows.map((row, ri) => (
                      <TR key={ri}>
                        <TD className="text-left first:text-left align-top whitespace-normal font-semibold text-ink">
                          {row.term}
                        </TD>
                        <TD className="text-left first:text-left align-top whitespace-normal text-steel">
                          {row.full || "—"}
                        </TD>
                        <TD className="text-left first:text-left align-top whitespace-normal">{row.plain}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </Panel>
              {section.banner ? <Banner>{section.banner}</Banner> : null}
            </div>
          ))}
        </>
      )}
    </>
  );
}
