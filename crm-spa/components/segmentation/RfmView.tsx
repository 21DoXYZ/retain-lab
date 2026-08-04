"use client";

import Link from "next/link";
import {
  PageHeader,
  SCard,
  SCardGrid,
  Card,
  ChartBox,
  Panel,
  Badge,
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
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSegmentationData } from "./useSegmentationData";
import { Chart } from "./Chart";
import { rfmBarOption } from "./chartOptions";
import type { RfmResponse, RfmSegment } from "./types";

/**
 * /rfm — RFM segmentation (Recency · Frequency · Monetary). Segment counts,
 * meanings and actions are 1:1 with /api/v1/rfm (the board's rfm() SQL + META).
 */
function SegRow({ s, daySuffix }: { s: RfmSegment; daySuffix: string }) {
  return (
    <TR>
      <TD>
        <Badge bg={s.bg} fg={s.fg}>
          {s.seg}
        </Badge>
      </TD>
      <TD mono>{formatInt(s.n)}</TD>
      <TD mono>{s.pct}%</TD>
      <TD mono>{formatInt(s.avg_turn)} ₺</TD>
      <TD mono>{s.avg_rec == null ? "—" : `${s.avg_rec}${daySuffix}`}</TD>
      <TD mono>{s.avg_act == null ? "—" : s.avg_act}</TD>
      <TD className="text-left text-steel">{s.mean}</TD>
      <TD className="text-left">{s.action}</TD>
    </TR>
  );
}

export function RfmView() {
  const t = useT();
  const { state, data, error, reload } = useSegmentationData<RfmResponse>(
    "/api/v1/rfm",
    (d) => d.segments.length === 0,
  );

  return (
    <>
      <PageHeader
        title={t("segmentation.rfm.title")}
        accent={t("segmentation.rfm.accent")}
        lead={t("segmentation.rfm.lead")}
      />

      {state === "error" ? (
        <Card className="mt-6">
          <ErrorState description={error ?? undefined} onRetry={reload} />
        </Card>
      ) : (
        <div className="mt-6 space-y-4">
          <SCardGrid>
            <SCard
              variant="alert"
              icon="📊"
              label={t("segmentation.rfm.card.coverage.label")}
              value={data ? formatInt(data.played) : "…"}
              sub={
                data
                  ? t("segmentation.rfm.card.coverage.sub", {
                      base: formatInt(data.base),
                      never: formatInt(data.never_count),
                    })
                  : ""
              }
              loading={state === "loading"}
            />
            <SCard icon="📅" label={t("segmentation.rfm.card.r.label")} value="1–5" sub={t("segmentation.rfm.card.r.sub")} loading={state === "loading"} />
            <SCard icon="🔁" label={t("segmentation.rfm.card.f.label")} value="1–5" sub={t("segmentation.rfm.card.f.sub")} loading={state === "loading"} />
            <SCard variant="cream" icon="💰" label={t("segmentation.rfm.card.m.label")} value="1–5" sub={t("segmentation.rfm.card.m.sub")} loading={state === "loading"} />
          </SCardGrid>

          <ChartBox title={t("segmentation.rfm.chart.title")} caption={t("segmentation.rfm.chart.caption")}>
            {state === "data" && data ? (
              <Chart option={rfmBarOption(data.segments)} height={240} />
            ) : (
              <Skeleton className="h-[240px] w-full" />
            )}
          </ChartBox>

          <Panel>
            <Table>
              <THead>
                <TR>
                  <TH>{t("segmentation.rfm.col.segment")}</TH>
                  <TH>{t("segmentation.rfm.col.players")}</TH>
                  <TH>{t("segmentation.rfm.col.pctBase")}</TH>
                  <TH>{t("segmentation.rfm.col.avgTurn")}</TH>
                  <TH title={t("segmentation.rfm.col.avgRecencyTitle")}>{t("segmentation.rfm.col.avgRecency")}</TH>
                  <TH title={t("segmentation.rfm.col.avgDaysTitle")}>{t("segmentation.rfm.col.avgDays")}</TH>
                  <TH className="text-left">{t("segmentation.rfm.col.meaning")}</TH>
                  <TH className="text-left">{t("segmentation.rfm.col.action")}</TH>
                </TR>
              </THead>
              <TBody>
                {state === "loading" &&
                  Array.from({ length: 8 }).map((_, i) => (
                    <TR key={`sk-${i}`}>
                      {Array.from({ length: 8 }).map((__, j) => (
                        <TD key={j}>
                          <Skeleton className={j === 0 ? "h-3.5 w-32" : "h-3.5 w-16 ml-auto"} />
                        </TD>
                      ))}
                    </TR>
                  ))}
                {state === "data" &&
                  data && [
                    ...data.segments.map((s) => <SegRow key={s.seg} s={s} daySuffix={t("segmentation.rfm.daySuffix")} />),
                    <SegRow key="__never" s={data.never} daySuffix={t("segmentation.rfm.daySuffix")} />,
                  ]}
              </TBody>
            </Table>
          </Panel>

          <Banner>
            {t("segmentation.rfm.banner.pre")} <b>{t("segmentation.rfm.banner.playedWord")}</b>{t("segmentation.rfm.banner.mid")}
            {data ? <>{t("segmentation.rfm.banner.convergeTo", { base: formatInt(data.base) })}</> : null}{t("segmentation.rfm.banner.post")}
            {/* board rfm() :2172-2173 — «Пульте» кликабелен → /desk */}
            <Link href="/desk" className="text-primary hover:underline">{t("segmentation.rfm.banner.deskLink")}</Link>
            {t("segmentation.rfm.banner.deskTail")}
          </Banner>
        </div>
      )}
    </>
  );
}
