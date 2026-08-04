"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import {
  Eyebrow,
  Panel,
  ChartBox,
  Banner,
  DataTable,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  type Column,
} from "@/components/ui";
import { formatInt, formatMoneyMn } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Chart } from "./Chart";
import type {
  GgrDashboardTab,
  GgrProviderRow,
  GgrRatesRow,
  GgrSegmentsTab,
  GgrBonusTab,
  GgrSettleTab,
  GgrReportsTab,
} from "./types";

/**
 * GGR tab bodies (agent F1) — one component per tab, 1:1 with ggr_page() of the
 * live board. Money in these tables is the millions short form (board `mn`),
 * counts use the space-thousands integer (board `f`). GGR is coloured green when
 * positive (casino profit) and red when negative (players won) — board `.num.pos`
 * / `.num.neg`. The `tab_data` union is narrowed by the caller (data.filters.tab).
 */

const mn = formatMoneyMn;
const f = formatInt;

// board palette (shared with AuditScreen)
const OR = "#2563eb";
const ST = "#64748b";
const HA = "#e5e7eb";
const INK = "#1e293b";

/** GGR value cell — green when ≥0, red when <0 (board `.num.pos/.neg`). */
function Ggr({ v }: { v: number }): ReactNode {
  return <span className={v < 0 ? "text-neg" : "text-pos"}>{mn(v)}</span>;
}

/* ── dashboard ─────────────────────────────────────────────────────────────── */
export function GgrDashboard({ tab }: { tab: GgrDashboardTab }) {
  const t = useT();
  const daily = tab.daily ?? [];
  const option = {
    grid: { left: 8, right: 14, top: 14, bottom: 24, containLabel: true },
    tooltip: { trigger: "axis", backgroundColor: "#fff", borderColor: HA, textStyle: { color: INK } },
    xAxis: {
      type: "category",
      data: daily.map((x) => x.label),
      axisLabel: { fontSize: 10, color: ST },
      axisLine: { lineStyle: { color: HA } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: HA } },
      axisLabel: { color: ST },
    },
    series: [
      {
        type: "line",
        data: daily.map((x) => x.g),
        smooth: true,
        symbol: "none",
        lineStyle: { color: OR, width: 2 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(37,99,235,.25)" },
              { offset: 1, color: "rgba(37,99,235,0)" },
            ],
          },
        },
      },
    ],
  } as const;

  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <ChartBox title={t("money.ggr.dashboard.chartTitle")} caption={t("money.ggr.dashboard.chartCaption")}>
        {daily.length ? (
          <Chart option={option} height={300} />
        ) : (
          <div className="text-steel text-[13px] py-10 text-center">{t("money.ggr.dashboard.noData")}</div>
        )}
      </ChartBox>
      <div>
        <div className="text-sm font-semibold mb-2.5">{t("money.ggr.dashboard.signalsTitle")}</div>
        {tab.signals.length ? (
          <div className="flex flex-col gap-2.5">
            {tab.signals.map((s) => {
              // title/text приходят по-русски (api/money.py:232-239), но kind —
              // стабильный код, а числа (neg_days/high_rtp/bratio) отдаются
              // структурно → собираем перевод сами; незнакомый kind — как есть.
              const localized =
                s.kind === "neg_days"
                  ? { title: t("money.ggr.signal.negDays.title"), text: t("money.ggr.signal.negDays.text", { n: tab.neg_days }) }
                  : s.kind === "high_rtp"
                    ? { title: t("money.ggr.signal.highRtp.title"), text: t("money.ggr.signal.highRtp.text", { providers: tab.high_rtp.map((x) => x.provider).join(", ") }) }
                    : s.kind === "bonus"
                      ? { title: t("money.ggr.signal.bonus.title"), text: t("money.ggr.signal.bonus.text", { pct: tab.bratio }) }
                      : { title: s.title, text: s.text };
              return (
                <div
                  key={s.kind}
                  className="bg-cream border border-beige rounded-card px-3.5 py-3 text-[13px]"
                >
                  <b>{localized.title}</b>
                  <div className="text-steel mt-1">{localized.text}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-steel text-[13px]">{t("money.ggr.dashboard.noSignals")}</div>
        )}
      </div>
    </div>
  );
}

/* ── provider / game ───────────────────────────────────────────────────────── */
export function GgrProviderGame({
  rows,
  kind,
  loading,
}: {
  rows: GgrProviderRow[];
  kind: "provider" | "game";
  loading: boolean;
}) {
  const t = useT();
  const cols: Column<GgrProviderRow>[] = [
    {
      key: "name",
      header: kind === "provider" ? t("money.ggr.providerGame.colProvider") : t("money.ggr.providerGame.colGame"),
      align: "left",
      render: (r) => r.name || "—",
    },
    { key: "bet", header: t("money.ggr.providerGame.colBet"), mono: true, render: (r) => mn(r.bet) },
    { key: "win", header: t("money.ggr.providerGame.colWin"), mono: true, render: (r) => mn(r.win) },
    { key: "ggr", header: t("money.ggr.providerGame.colGgr"), mono: true, render: (r) => <Ggr v={r.ggr} /> },
    { key: "rtp", header: t("money.ggr.providerGame.colRtp"), mono: true, render: (r) => `${r.rtp || 0}%` },
    { key: "players", header: t("money.ggr.providerGame.colPlayers"), mono: true, render: (r) => f(r.players) },
    { key: "rounds", header: t("money.ggr.providerGame.colRounds"), mono: true, render: (r) => f(r.rounds) },
  ];
  return (
    <Panel>
      <DataTable
        columns={cols}
        rows={rows}
        getRowKey={(r, i) => `${r.name}-${i}`}
        state={loading ? "loading" : rows.length ? "data" : "empty"}
        emptyTitle={t("money.ggr.providerGame.empty")}
      />
    </Panel>
  );
}

/* ── rates ─────────────────────────────────────────────────────────────────── */
export function GgrRates({ rows, loading }: { rows: GgrRatesRow[]; loading: boolean }) {
  const t = useT();
  const cols: Column<GgrRatesRow>[] = [
    { key: "provider", header: t("money.ggr.rates.colProvider"), align: "left", render: (r) => r.provider },
    { key: "engr", header: t("money.ggr.rates.colEngr"), mono: true, render: (r) => `${r.engr}%` },
    { key: "infra", header: t("money.ggr.rates.colInfra"), mono: true, render: (r) => `${r.infra}%` },
    { key: "revshare", header: t("money.ggr.rates.colRevshare"), mono: true, render: (r) => `${r.revshare}%` },
    { key: "fixed_fee", header: t("money.ggr.rates.colFixedFee"), mono: true, render: (r) => f(r.fixed_fee) },
    {
      key: "min_guarantee",
      header: t("money.ggr.rates.colMinGuarantee"),
      mono: true,
      render: (r) => f(r.min_guarantee),
    },
    { key: "period", header: t("money.ggr.rates.colPeriod"), align: "left", render: (r) => r.period },
  ];
  return (
    <>
      <p className="text-steel text-[13.5px] mb-3">{t("money.ggr.rates.note")}</p>
      <Panel>
        <DataTable
          columns={cols}
          rows={rows}
          getRowKey={(r, i) => `${r.provider}-${i}`}
          state={loading ? "loading" : rows.length ? "data" : "empty"}
          emptyTitle={t("money.ggr.rates.empty")}
        />
      </Panel>
    </>
  );
}

/* ── segments ──────────────────────────────────────────────────────────────── */
export function GgrSegments({ tab, loading }: { tab: GgrSegmentsTab; loading: boolean }) {
  const t = useT();
  const vipCols: Column<GgrSegmentsTab["vip"][number]>[] = [
    { key: "label", header: t("money.ggr.segments.colLevel"), align: "left", render: (r) => r.label },
    { key: "players", header: t("money.ggr.segments.colPlayers"), mono: true, render: (r) => f(r.players) },
    { key: "deposits", header: t("money.ggr.segments.colDeposits"), mono: true, render: (r) => mn(r.deposits) },
    {
      key: "active",
      header: t("money.ggr.segments.colActiveInPeriod"),
      mono: true,
      render: (r) => f(r.active),
    },
    { key: "bet", header: t("money.ggr.segments.colBetPeriod"), mono: true, render: (r) => mn(r.bet) },
    { key: "ggr", header: t("money.ggr.segments.colGgrPeriod"), mono: true, render: (r) => <Ggr v={r.ggr} /> },
  ];
  const behCols: Column<GgrSegmentsTab["behavioral"][number]>[] = [
    {
      key: "label",
      header: t("money.ggr.segments.colSegment"),
      align: "left",
      render: (r) => (
        <>
          {r.label} <span className="text-steel">({r.hint})</span>
        </>
      ),
    },
    { key: "players", header: t("money.ggr.segments.colPlayers"), mono: true, render: (r) => f(r.players) },
    { key: "bet", header: t("money.ggr.segments.colBet"), mono: true, render: (r) => mn(r.bet) },
    { key: "ggr", header: t("money.ggr.segments.colGgr"), mono: true, render: (r) => <Ggr v={r.ggr} /> },
  ];
  return (
    <>
      <Eyebrow>
        {t("money.ggr.segments.vipTitle")}{" "}
        <span className="text-steel font-normal normal-case tracking-normal">
          {t("money.ggr.segments.vipNote")}
        </span>
      </Eyebrow>
      <p className="text-steel text-[13.5px] -mt-1 mb-3">{t("money.ggr.segments.vipDesc")}</p>
      <Panel>
        <DataTable
          columns={vipCols}
          rows={tab.vip}
          getRowKey={(r) => r.level}
          state={loading ? "loading" : tab.vip.length ? "data" : "empty"}
          emptyTitle={t("money.ggr.segments.empty")}
        />
      </Panel>

      <Eyebrow>
        {t("money.ggr.segments.behavioralTitle")}{" "}
        <span className="text-steel font-normal normal-case tracking-normal">
          {t("money.ggr.segments.behavioralNote")}
        </span>
      </Eyebrow>
      <Panel>
        <DataTable
          columns={behCols}
          rows={tab.behavioral}
          getRowKey={(r) => r.label}
          state={loading ? "loading" : "data"}
        />
      </Panel>

      <Banner>
        <b>{t("money.ggr.segments.riskAbuse", { pct: tab.risk_abuse || 0 })}</b>
        <div className="text-steel mt-1">{t("money.ggr.segments.riskAbuseNote")}</div>
      </Banner>
    </>
  );
}

/* ── bonus ─────────────────────────────────────────────────────────────────── */
export function GgrBonus({ tab, loading }: { tab: GgrBonusTab; loading: boolean }) {
  const t = useT();
  const cols: Column<GgrBonusTab["rows"][number]>[] = [
    { key: "type", header: t("money.ggr.bonus.colType"), align: "left", render: (r) => r.type },
    { key: "events", header: t("money.ggr.bonus.colEvents"), mono: true, render: (r) => f(r.events) },
    { key: "players", header: t("money.ggr.bonus.colPlayers"), mono: true, render: (r) => f(r.players) },
    { key: "cost", header: t("money.ggr.bonus.colCost"), mono: true, render: (r) => mn(r.cost) },
    { key: "pct", header: t("money.ggr.bonus.colPct"), mono: true, render: (r) => `${r.pct}%` },
  ];
  return (
    <>
      <p className="text-steel text-[13.5px] mb-3">
        {t("money.ggr.bonus.summaryPrefix")} <b className="text-ink">{mn(tab.total_cost)}</b>{" "}
        {t("money.ggr.bonus.summarySuffix", { pct: tab.bratio })}
      </p>
      <Panel>
        <DataTable
          columns={cols}
          rows={tab.rows}
          getRowKey={(r, i) => `${r.type}-${i}`}
          state={loading ? "loading" : tab.rows.length ? "data" : "empty"}
          emptyTitle={t("money.ggr.bonus.empty")}
        />
      </Panel>
    </>
  );
}

/* ── settle ────────────────────────────────────────────────────────────────── */
export function GgrSettle({ tab, loading }: { tab: GgrSettleTab; loading: boolean }) {
  const t = useT();
  const wfCols: Column<GgrSettleTab["waterfall"][number]>[] = [
    { key: "label", header: t("money.ggr.settle.colArticle"), align: "left", render: (r) => r.label },
    { key: "value", header: t("money.ggr.settle.colSum"), mono: true, render: (r) => <Ggr v={r.value} /> },
    { key: "pct", header: t("money.ggr.settle.colPctGgr"), mono: true, render: (r) => `${r.pct}%` },
    { key: "note", header: "", align: "left", render: (r) => <span className="text-steel">{r.note}</span> },
  ];
  const affCols: Column<GgrSettleTab["affiliates"][number]>[] = [
    { key: "code", header: t("money.ggr.settle.colAffiliate"), align: "left", render: (r) => r.code },
    { key: "net", header: t("money.ggr.settle.colNetDeposit"), mono: true, render: (r) => mn(r.net) },
    { key: "rate", header: t("money.ggr.settle.colRate"), mono: true, render: (r) => `${r.rate}%` },
    {
      key: "commission",
      header: t("money.ggr.settle.colCommission"),
      mono: true,
      render: (r) => <span className="text-pos">{mn(r.commission)}</span>,
    },
  ];
  return (
    <>
      <Eyebrow>
        {t("money.ggr.settle.waterfallTitle")}{" "}
        <span className="text-steel font-normal normal-case tracking-normal">
          {t("money.ggr.settle.waterfallNote")}
        </span>
      </Eyebrow>
      <Panel>
        <DataTable
          columns={wfCols}
          rows={tab.waterfall}
          getRowKey={(r) => r.label}
          state={loading ? "loading" : "data"}
        />
      </Panel>

      <Eyebrow>
        {t("money.ggr.settle.affiliatesTitle")}{" "}
        <span className="text-steel font-normal normal-case tracking-normal">
          {t("money.ggr.settle.affiliatesNote")}
        </span>
      </Eyebrow>
      <Panel>
        <DataTable
          columns={affCols}
          rows={tab.affiliates}
          getRowKey={(r, i) => `${r.code}-${i}`}
          state={loading ? "loading" : tab.affiliates.length ? "data" : "empty"}
          emptyTitle={t("money.ggr.settle.emptyAffiliates")}
        />
      </Panel>
    </>
  );
}

/* ── reports (custom table with a totals footer, board tfoot) ──────────────── */
export function GgrReports({ tab }: { tab: GgrReportsTab }) {
  const t = useT();
  const rows = tab.rows ?? [];
  return (
    <>
      <Eyebrow>
        {t("money.ggr.reports.title")}{" "}
        <span className="text-steel font-normal normal-case tracking-normal">
          {t("money.ggr.reports.range", { from: tab.from, to: tab.to })}
        </span>
      </Eyebrow>
      <Panel>
        <Table>
          <THead>
            <TR>
              <TH>{t("money.ggr.reports.colDate")}</TH>
              <TH>{t("money.ggr.reports.colBet")}</TH>
              <TH>{t("money.ggr.reports.colWin")}</TH>
              <TH>{t("money.ggr.reports.colGgr")}</TH>
              <TH>{t("money.ggr.reports.colActive")}</TH>
              <TH>{t("money.ggr.reports.colRounds")}</TH>
            </TR>
          </THead>
          <TBody>
            {rows.length ? (
              rows.map((r) => (
                <TR key={r.d}>
                  <TD>{r.d}</TD>
                  <TD mono>{mn(r.bet)}</TD>
                  <TD mono>{mn(r.win)}</TD>
                  <TD mono>
                    <Ggr v={r.ggr} />
                  </TD>
                  <TD mono>{f(r.active)}</TD>
                  <TD mono>{f(r.rounds)}</TD>
                </TR>
              ))
            ) : (
              <TR>
                <TD className="text-steel text-center" colSpan={6}>
                  {t("money.ggr.reports.noData")}
                </TD>
              </TR>
            )}
          </TBody>
          <tfoot>
            <TR>
              <TD className="font-semibold">{t("money.ggr.reports.total")}</TD>
              <TD mono className="font-semibold">
                {mn(tab.totals.bet)}
              </TD>
              <TD mono className="font-semibold">
                {mn(tab.totals.win)}
              </TD>
              <TD mono className="font-semibold">
                <Ggr v={tab.totals.ggr} />
              </TD>
              <TD />
              <TD mono className="font-semibold">
                {f(tab.totals.rounds)}
              </TD>
            </TR>
          </tfoot>
        </Table>
      </Panel>
      <p className="text-steel text-[13.5px] mt-4">
        {t("money.ggr.reports.footer")}{" "}
        {/* board :917 — <a href="/exports">Проверка выгрузок</a> */}
        <Link href="/exports" className="text-primary font-medium hover:underline">
          {t("money.ggr.reports.footerLink")}
        </Link>
        .
      </p>
    </>
  );
}
