"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import {
  PageHeader,
  SCard,
  SCardGrid,
  Card,
  ChartBox,
  Panel,
  Eyebrow,
  Banner,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  ErrorState,
  Skeleton,
} from "@/components/ui";
import { formatInt, formatMoneyMn } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSegmentationData } from "./useSegmentationData";
import { Chart } from "./Chart";
import { ltvConcentrationOption } from "./chartOptions";
import type { DistResponse } from "./types";

function SectionLabel({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <Eyebrow>
      {children}
      {note ? <span className="text-steel normal-case font-normal tracking-normal"> {note}</span> : null}
    </Eyebrow>
  );
}

/** Board .lead note (steel · 14.5px) — the "how to read" explainer under a table (board dist() :1990/:1996/:2012). */
function Lead({ children }: { children: ReactNode }) {
  return <div className="text-steel text-[14.5px] mt-1.5">{children}</div>;
}

export function DistView() {
  const t = useT();
  const { state, data, error, reload } = useSegmentationData<DistResponse>(
    "/api/v1/dist",
    (d) => d.ltv_deciles.length === 0 && d.deposit_percentiles.length === 0,
  );

  if (state === "error") {
    return (
      <>
        <PageHeader title={t("segmentation.dist.title")} accent={t("segmentation.dist.accent")} />
        <Card className="mt-6">
          <ErrorState description={error ?? undefined} onRetry={reload} />
        </Card>
      </>
    );
  }

  const loading = state === "loading" || !data;

  return (
    <>
      <PageHeader
        title={t("segmentation.dist.title")}
        accent={t("segmentation.dist.accent")}
        lead={t("segmentation.dist.lead")}
      />

      <div className="mt-6">
        <SCardGrid className="lg:grid-cols-3">
          <SCard
            variant="orange"
            icon="🐋"
            label={t("segmentation.dist.card.top10.label")}
            value={data ? `${data.cards.top10_pct_of_value}%` : "…"}
            sub={t("segmentation.dist.card.top10.sub")}
            loading={loading}
          />
          <SCard
            icon="📐"
            label={t("segmentation.dist.card.median.label")}
            value={data ? `${formatInt(data.cards.median_deposit)} ₺` : "…"}
            sub={
              data
                ? t("segmentation.dist.card.median.sub", {
                    p90: formatInt(data.cards.p90_deposit),
                    p99: formatInt(data.cards.p99_deposit),
                  })
                : ""
            }
            loading={loading}
          />
          <SCard
            variant="cream"
            icon="📈"
            label={t("segmentation.dist.card.max.label")}
            value={data ? formatMoneyMn(data.cards.max_deposit) : "…"}
            sub={t("segmentation.dist.card.max.sub")}
            loading={loading}
          />
        </SCardGrid>
      </div>

      {/* LTV deciles */}
      <SectionLabel note={data ? t("segmentation.dist.ltvDeciles.note", { n: formatInt(data.ltv_base) }) : null}>
        {t("segmentation.dist.ltvDeciles.title")}
      </SectionLabel>
      <Panel>
        <Table>
          <THead>
            <TR>
              <TH>{t("segmentation.dist.col.decile")}</TH>
              <TH>{t("segmentation.dist.col.players")}</TH>
              <TH>{t("segmentation.dist.col.avgLtv")}</TH>
              <TH>{t("segmentation.dist.col.sum")}</TH>
              <TH>{t("segmentation.dist.col.pctValue")}</TH>
            </TR>
          </THead>
          <TBody>
            {loading &&
              Array.from({ length: 10 }).map((_, i) => (
                <TR key={`l-${i}`}>
                  {Array.from({ length: 5 }).map((__, j) => (
                    <TD key={j}><Skeleton className={j === 0 ? "h-3.5 w-12" : "h-3.5 w-16 ml-auto"} /></TD>
                  ))}
                </TR>
              ))}
            {!loading &&
              data.ltv_deciles.map((r) => (
                <TR key={r.decile}>
                  <TD idCell>{r.is_whale ? "🐋 " : ""}D{r.decile}</TD>
                  <TD mono>{formatInt(r.players)}</TD>
                  <TD mono>{formatInt(r.avg_ltv)} ₺</TD>
                  <TD mono>{formatMoneyMn(r.sum_ltv)}</TD>
                  <TD mono>{r.pct_of_value}%</TD>
                </TR>
              ))}
          </TBody>
        </Table>
      </Panel>
      {/* board dist() :1990 — как читать децили LTV */}
      <Lead>
        {t("segmentation.dist.ltvDeciles.help.pre")}
        <b>{t("segmentation.dist.ltvDeciles.help.b1")}</b>
        {t("segmentation.dist.ltvDeciles.help.mid")}
        <b>{t("segmentation.dist.ltvDeciles.help.b2")}</b>
        {t("segmentation.dist.ltvDeciles.help.post")}
      </Lead>
      <ChartBox className="mt-4" title={t("segmentation.dist.chart.title")} caption={t("segmentation.dist.chart.caption")}>
        {!loading ? (
          <Chart option={ltvConcentrationOption(data.ltv_deciles)} height={220} />
        ) : (
          <Skeleton className="h-[220px] w-full" />
        )}
      </ChartBox>

      {/* Churn deciles */}
      <SectionLabel note={data ? t("segmentation.dist.churnDeciles.note", { n: formatInt(data.churn_base) }) : null}>
        {t("segmentation.dist.churnDeciles.title")}
      </SectionLabel>
      <Panel>
        <Table>
          <THead>
            <TR>
              <TH>{t("segmentation.dist.col.decile")}</TH>
              <TH>{t("segmentation.dist.col.players")}</TH>
              <TH>{t("segmentation.dist.col.avgRisk")}</TH>
              <TH>{t("segmentation.dist.col.range")}</TH>
            </TR>
          </THead>
          <TBody>
            {loading &&
              Array.from({ length: 10 }).map((_, i) => (
                <TR key={`c-${i}`}>
                  {Array.from({ length: 4 }).map((__, j) => (
                    <TD key={j}><Skeleton className={j === 0 ? "h-3.5 w-12" : "h-3.5 w-16 ml-auto"} /></TD>
                  ))}
                </TR>
              ))}
            {!loading &&
              data.churn_deciles.map((r) => (
                <TR key={r.decile}>
                  <TD idCell>D{r.decile}</TD>
                  <TD mono>{formatInt(r.players)}</TD>
                  <TD mono>{Math.round(r.avg_risk * 100)}%</TD>
                  <TD mono>{Math.round(r.lo * 100)}–{Math.round(r.hi * 100)}%</TD>
                </TR>
              ))}
          </TBody>
        </Table>
      </Panel>
      {/* board dist() :1996 — как читать децили риска ухода */}
      <Lead>
        {t("segmentation.dist.churnDeciles.help.pre")}
        <b>{t("segmentation.dist.churnDeciles.help.b1")}</b>
        {t("segmentation.dist.churnDeciles.help.mid")}
        <b>{t("segmentation.dist.churnDeciles.help.b2")}</b>
        {t("segmentation.dist.churnDeciles.help.post")}
      </Lead>

      {/* Why churn is not on the whole base */}
      <SectionLabel>{t("segmentation.dist.churnWhy.title")}</SectionLabel>
      <Panel>
        <Table>
          <THead>
            <TR>
              <TH className="text-left">{t("segmentation.dist.col.group")}</TH>
              <TH>{t("segmentation.dist.col.players")}</TH>
              <TH className="text-left">{t("segmentation.dist.col.whyWhat")}</TH>
            </TR>
          </THead>
          <TBody>
            {loading &&
              Array.from({ length: 4 }).map((_, i) => (
                <TR key={`b-${i}`}>
                  {Array.from({ length: 3 }).map((__, j) => (
                    <TD key={j}><Skeleton className={j === 1 ? "h-3.5 w-16 ml-auto" : "h-3.5 w-40"} /></TD>
                  ))}
                </TR>
              ))}
            {!loading && (
              <>
                {data.churn_breakdown.map((b) => (
                  <TR key={b.group}>
                    <TD className="text-left">{b.group}</TD>
                    <TD mono>{formatInt(b.players)}</TD>
                    <TD className="text-left text-steel">
                      {b.desc} · {b.note}
                    </TD>
                  </TR>
                ))}
                <TR className="border-t-2 border-hair2">
                  <TD className="text-left font-semibold">{t("segmentation.dist.total")}</TD>
                  <TD mono className="font-semibold">{formatInt(data.churn_breakdown_total)}</TD>
                  <TD className="text-left text-steel">{t("segmentation.dist.wholeBaseNormal")}</TD>
                </TR>
              </>
            )}
          </TBody>
        </Table>
      </Panel>
      {/* board dist() :2012 — churn осмыслен только для живых + ссылка на движок на Пульте */}
      <Lead>
        {t("segmentation.dist.churnWhy.help.pre")}
        <Link href="/desk" className="text-primary hover:underline">
          {t("segmentation.dist.churnWhy.help.link")}
        </Link>
        {t("segmentation.dist.churnWhy.help.post")}
      </Lead>

      {/* Deposit percentiles */}
      <SectionLabel note={data ? t("segmentation.dist.depositPercentiles.note", { n: formatInt(data.depositors) }) : null}>
        {t("segmentation.dist.depositPercentiles.title")}
      </SectionLabel>
      <Panel>
        <Table>
          <THead>
            <TR>
              <TH>{t("segmentation.dist.col.percentile")}</TH>
              <TH>{t("segmentation.dist.col.sumTry")}</TH>
            </TR>
          </THead>
          <TBody>
            {loading &&
              Array.from({ length: 8 }).map((_, i) => (
                <TR key={`p-${i}`}>
                  <TD><Skeleton className="h-3.5 w-12" /></TD>
                  <TD><Skeleton className="h-3.5 w-20 ml-auto" /></TD>
                </TR>
              ))}
            {!loading &&
              data.deposit_percentiles.map((p) => (
                <TR key={p.label}>
                  <TD idCell>{p.label}</TD>
                  <TD mono>{formatInt(p.value)} ₺</TD>
                </TR>
              ))}
          </TBody>
        </Table>
      </Panel>

      <Banner>
        {t("segmentation.dist.banner.pre")} <b>{t("segmentation.dist.banner.bold1")}</b>{t("segmentation.dist.banner.mid")} <b>{t("segmentation.dist.banner.bold2")}</b> {t("segmentation.dist.banner.post")}
      </Banner>
    </>
  );
}
