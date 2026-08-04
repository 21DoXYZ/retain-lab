"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  PageHeader,
  SCard,
  SCardGrid,
  Chip,
  Pill,
  PillRow,
  Badge,
  Banner,
  Button,
  DateInput,
  ErrorState,
} from "@/components/ui";
import { formatInt, formatMoney, formatDate } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { downloadSegment, DownloadError } from "@/app/(app)/players/download";
import { useResource } from "./data";
import { VERDICT } from "./verdict";
import { ChartCard, MiniBars, Funnel, MoneyByMonth, TopGamesTable } from "./bars";
import { DetailPlayers } from "./DetailPlayers";
import type { AffiliateDetailData, AffiliateStatus, PlayerSortKey } from "./types";

/** Вердикт → ключ текста баннера (разный на каждый вердикт, борд :2891-2912). */
const VERDICT_BODY_KEY: Record<AffiliateStatus, MessageKey> = {
  loss: "monitor.affiliateDetail.verdict.body.loss",
  risk: "monitor.affiliateDetail.verdict.body.risk",
  cash_drain: "monitor.affiliateDetail.verdict.body.cashDrain",
  profit: "monitor.affiliateDetail.verdict.body.profit",
};

/**
 * /affiliates/<code> — full reconciliation card for one source (C5), mirroring
 * the board affiliate() route: block 1 reconciles with the partner network
 * (Registrations / FTD / Approved Deposits & Withdrawals / Bonus Cost /
 * Net Profit / Commission-by-rate / Active), block 2 adds our game analytics
 * (turnover / GGR split / NGR), plus the source funnel, distributions and the
 * per-player cash table. Window (from/to) + player status (normal/all) filter
 * every metric — a filter change is a path change, so the card refetches.
 */

export function AffiliateDetailScreen({ code }: { code: string }) {
  const t = useT();
  const [st, setSt] = useState<"normal" | "all">("normal");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [pSort, setPSort] = useState<PlayerSortKey>("dep");
  const [pDir, setPDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  // Экспорт игроков аффилиата (борд :3039-3044). downloadSegment — тот же generic
  // хелпер, что у /players; сегмент = aff=<code>&at=normal (+ life=churning).
  async function runExport(id: string, fmt: "csv" | "xlsx", churning: boolean) {
    setExportError(null);
    setExporting(id);
    try {
      const params = new URLSearchParams({ aff: code, at: "normal" });
      if (churning) params.set("life", "churning");
      await downloadSegment(fmt, params.toString());
    } catch (err) {
      if (err instanceof DownloadError) {
        setExportError(
          err.code === "forbidden"
            ? t("monitor.affiliateDetail.export.forbidden")
            : t("monitor.affiliateDetail.export.httpError", { status: err.status }),
        );
      } else {
        setExportError(t("monitor.affiliateDetail.export.error"));
      }
    } finally {
      setExporting(null);
    }
  }

  const path = useMemo(() => {
    const params = new URLSearchParams();
    params.set("st", st);
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    params.set("sort", pSort);
    params.set("dir", pDir);
    params.set("p", String(page));
    return `/api/v1/affiliates/${encodeURIComponent(code)}?${params.toString()}`;
  }, [code, st, from, to, pSort, pDir, page]);

  const { state, data, error, reload } = useResource<AffiliateDetailData>(path);
  const d = data; // keep the last card visible while the table refetches

  function onSort(key: PlayerSortKey) {
    if (key === pSort) setPDir((prev) => (prev === "desc" ? "asc" : "desc"));
    else {
      setPSort(key);
      setPDir("desc");
    }
    setPage(0);
  }
  function changeStatus(next: "normal" | "all") {
    setSt(next);
    setPage(0);
  }
  function changeFrom(v: string) {
    setFrom(v);
    setPage(0);
  }
  function changeTo(v: string) {
    setTo(v);
    setPage(0);
  }
  function resetWindow() {
    setFrom("");
    setTo("");
    setPage(0);
  }

  const back = (
    <Link href="/affiliates" className="text-[13px] text-primary hover:underline">
      {t("monitor.affiliateDetail.back")}
    </Link>
  );

  // Hard failure with no data yet (e.g. unknown code → 404 "no players").
  if (state === "error" && !d) {
    return (
      <>
        <div className="mb-3">{back}</div>
        <PageHeader title={t("monitor.affiliateDetail.title")} accent={`· ${code}`} />
        <div className="mt-6">
          <ErrorState
            title={t("monitor.affiliateDetail.error.title")}
            description={error ?? t("monitor.affiliateDetail.error.desc")}
            onRetry={reload}
          />
        </div>
      </>
    );
  }

  const loading = state === "loading";
  const R = d?.reconciliation;
  const G = d?.game;
  const v = d ? VERDICT[d.verdict] : VERDICT.profit;
  const win = d?.window;

  return (
    <>
      <div className="mb-3">{back}</div>

      <PageHeader
        title={t("monitor.affiliateDetail.title")}
        accent={`· ${code}`}
        lead={
          d
            ? t("monitor.affiliateDetail.leadWithData", {
                type: d.affiliate_type ?? "—",
                normal: formatInt(d.breakdown.normal),
                test: formatInt(d.breakdown.test),
                blocked: formatInt(d.breakdown.blocked),
              })
            : t("monitor.affiliateDetail.leadFallback")
        }
        right={
          <PillRow>
            {d ? (
              <Badge bg={v.badgeBg} fg={v.badgeFg} title={t(v.titleKey)}>
                {v.emoji} {t(v.labelKey)}
              </Badge>
            ) : null}
            {d?.asof ? <Pill>{t("monitor.pill.asOf", { date: formatDate(d.asof) })}</Pill> : null}
            <Pill live>{t("monitor.pill.live")}</Pill>
          </PillRow>
        }
      />

      {/* Filters: window (by event date) + player status */}
      <div className="mt-4 flex flex-wrap items-center gap-2 rounded-card border border-beige bg-cream px-3.5 py-3">
        <span className="text-[13px] font-semibold text-steel">{t("monitor.affiliateDetail.filter.period")}</span>
        <DateInput
          className="w-[150px]"
          value={from || win?.dmin || ""}
          min={win?.dmin}
          max={win?.dmax}
          onChange={(e) => changeFrom(e.target.value)}
        />
        <span className="text-steel">→</span>
        <DateInput
          className="w-[150px]"
          value={to || win?.dmax || ""}
          min={win?.dmin}
          max={win?.dmax}
          onChange={(e) => changeTo(e.target.value)}
        />
        <Chip onClick={resetWindow}>{t("monitor.affiliateDetail.filter.reset")}</Chip>
        {win?.filtered ? (
          <span className="text-[12.5px] font-semibold text-primary">
            {t("monitor.affiliateDetail.window.filtered", { from: win.from, to: win.to })}
          </span>
        ) : win ? (
          <span className="text-[12.5px] text-steel">
            {t("monitor.affiliateDetail.window.full", { dmin: win.dmin, dmax: win.dmax })}
          </span>
        ) : null}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 rounded-card border border-beige bg-cream px-3.5 py-3">
        <span className="text-[13px] font-semibold text-steel">{t("monitor.affiliateDetail.filter.status")}</span>
        <Chip active={st === "normal"} onClick={() => changeStatus("normal")}>
          {t("monitor.affiliateDetail.filter.statusNormal")}
        </Chip>
        <Chip active={st === "all"} onClick={() => changeStatus("all")}>
          {t("monitor.affiliateDetail.filter.statusAll")}
        </Chip>
        {d ? (
          <span className="text-[12.5px] text-steel">
            {t("monitor.affiliateDetail.breakdown.real")} <b>{formatInt(d.breakdown.normal)}</b> · {t("monitor.affiliateDetail.breakdown.test")} <b>{formatInt(d.breakdown.test)}</b> · {t("monitor.affiliateDetail.breakdown.blocked")}{" "}
            <b>{formatInt(d.breakdown.blocked)}</b> {t("monitor.affiliateDetail.breakdown.total")} <b>{formatInt(d.breakdown.all)}</b>
          </span>
        ) : null}
      </div>

      {/* Verdict banner — свой текст на каждый вердикт (борд :2891-2912) */}
      {d ? (
        <div
          className="mt-4 rounded-card border px-[18px] py-[15px] text-[13.5px] leading-relaxed"
          style={{ background: v.bannerBg, borderColor: v.bannerBd, borderLeft: `3px solid ${v.bannerCol}` }}
        >
          <b>
            {v.emoji} {t(v.labelKey).toUpperCase()}.
          </b>{" "}
          {t(VERDICT_BODY_KEY[d.verdict], {
            netProfit: formatMoney(R!.net_profit),
            ggrReal: formatMoney(G!.ggr_real),
          })}{" "}
          <span className="text-steel">{t("monitor.affiliateDetail.verdict.note")}</span>
        </div>
      ) : null}

      {/* Экспорт игроков аффилиата — 4 чипа (борд :3039-3044) */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-[12.5px] text-steel">{t("monitor.affiliateDetail.export.label")}</span>
        <Button size="sm" variant="ghost" loading={exporting === "all-csv"} disabled={exporting !== null} onClick={() => runExport("all-csv", "csv", false)}>
          {t("monitor.affiliateDetail.export.allCsv")}
        </Button>
        <Button size="sm" variant="ghost" loading={exporting === "all-xlsx"} disabled={exporting !== null} onClick={() => runExport("all-xlsx", "xlsx", false)}>
          {t("monitor.affiliateDetail.export.allXlsx")}
        </Button>
        <Button size="sm" variant="ghost" title={t("monitor.affiliateDetail.export.churningTitle")} loading={exporting === "ch-csv"} disabled={exporting !== null} onClick={() => runExport("ch-csv", "csv", true)}>
          {t("monitor.affiliateDetail.export.churningCsv")}
        </Button>
        <Button size="sm" variant="ghost" title={t("monitor.affiliateDetail.export.churningTitle")} loading={exporting === "ch-xlsx"} disabled={exporting !== null} onClick={() => runExport("ch-xlsx", "xlsx", true)}>
          {t("monitor.affiliateDetail.export.churningXlsx")}
        </Button>
      </div>
      {exportError ? (
        <Banner className="border-l-neg mt-2">
          <span className="text-neg font-semibold">{exportError}</span>
        </Banner>
      ) : null}

      {/* Block 1 — reconciliation with the partner network */}
      <div className="mt-6 text-[11px] font-semibold uppercase tracking-[1px] text-primary">{t("monitor.affiliateDetail.section.reconciliation")}</div>
      <div className="mt-3">
        <SCardGrid>
          <SCard variant="cream" icon="🧾" label="Total Registrations" value={R ? formatInt(R.registrations) : "—"} sub={R ? t("monitor.affiliateDetail.kpi.registrations.sub", { n: R.conversion }) : undefined} loading={loading && !d} />
          <SCard variant="cream" icon="🥇" label="Total FTD" value={R ? formatInt(R.ftd) : "—"} sub={R ? t("monitor.affiliateDetail.kpi.ftd.sub", { n: R.ftd_rate, avg: formatInt(R.avg_ftd), date: formatDate(R.last_ftd) }) : undefined} loading={loading && !d} />
          <SCard icon="💰" label="Approved Deposits" value={R ? formatMoney(R.deposits_approved) : "—"} sub={R ? t("monitor.affiliateDetail.kpi.deposits.sub", { n: formatInt(R.deposits_count) }) : undefined} loading={loading && !d} />
          <SCard icon="🏧" label="Approved Withdrawals" value={R ? formatMoney(R.withdrawals_approved) : "—"} sub={R ? t("monitor.affiliateDetail.kpi.withdrawals.sub", { n: formatInt(R.withdrawals_count), rejected: formatInt(R.withdrawals_rejected) }) : undefined} loading={loading && !d} />
          <SCard icon="🎁" label="Bonus Cost" value={R ? formatMoney(R.bonus_cost) : "—"} sub={R ? t("monitor.affiliateDetail.kpi.bonusCost.sub", { n: R.bonus_ratio }) : undefined} loading={loading && !d} />
          <SCard variant={R && R.net_profit < 0 ? "alert" : "default"} valueTone={R ? (R.net_profit < 0 ? "neg" : "pos") : "default"} icon="📈" label="Net Profit" value={R ? formatMoney(R.net_profit) : "—"} sub={t("monitor.affiliateDetail.kpi.netProfit.sub")} loading={loading && !d} />
          <SCard variant="orange" icon="🪙" label="Commission" value={R ? formatMoney(R.commission) : "—"} sub={R ? t("monitor.affiliateDetail.kpi.commission.sub", { n: R.commission_rate }) : undefined} loading={loading && !d} />
          <SCard icon="🟢" label="Active Players" value={R ? formatInt(R.active_players) : "—"} sub={t("monitor.affiliateDetail.kpi.activePlayers.sub")} loading={loading && !d} />
        </SCardGrid>
      </div>

      <Banner>
        🔎 <b>{t("monitor.affiliateDetail.reconBanner.title")}</b> {t("monitor.affiliateDetail.reconBanner.intro")} <b>Approved Deposits/Withdrawals</b>{" "}
        {t("monitor.affiliateDetail.reconBanner.approvedDef")} <b>Bonus Cost</b> {t("monitor.affiliateDetail.reconBanner.bonusCostDef")} <b>Net Profit</b> {t("monitor.affiliateDetail.reconBanner.netProfitDef")}{" "}
        <b>Commission</b> {t("monitor.affiliateDetail.reconBanner.commissionDef", { rate: R ? R.commission_rate : 0 })}
      </Banner>

      {/* Block 2 — our game analytics */}
      <div className="mt-6 text-[11px] font-semibold uppercase tracking-[1px] text-primary">{t("monitor.affiliateDetail.section.gameAnalytics")}</div>
      <div className="mt-3">
        <SCardGrid>
          <SCard icon="🎰" label={t("monitor.affiliateDetail.kpi.turnover.label")} value={G ? formatMoney(G.turnover) : "—"} sub={G ? t("monitor.affiliateDetail.kpi.turnover.sub", { real: formatMoney(G.real_bets), fs: formatMoney(G.fs_bets) }) : undefined} loading={loading && !d} />
          <SCard icon="🏦" label={t("monitor.affiliateDetail.kpi.ggr.label")} value={G ? formatMoney(G.ggr) : "—"} sub={G ? t("monitor.affiliateDetail.kpi.ggr.sub", { n: G.hold }) : undefined} loading={loading && !d} />
          <SCard variant="orange" icon="🎯" label={t("monitor.affiliateDetail.kpi.ggrReal.label")} value={G ? formatMoney(G.ggr_real) : "—"} sub={G ? t("monitor.affiliateDetail.kpi.ggrReal.sub", { n: G.hold_real }) : undefined} loading={loading && !d} />
          <SCard icon="🎁" label={t("monitor.affiliateDetail.kpi.ggrFs.label")} value={G ? formatMoney(G.ggr_fs) : "—"} sub={t("monitor.affiliateDetail.kpi.ggrFs.sub")} loading={loading && !d} />
          <SCard icon="💸" label={t("monitor.affiliateDetail.kpi.bonusGiven.label")} value={R ? formatMoney(R.bonus_cost) : "—"} sub={t("monitor.affiliateDetail.kpi.bonusGiven.sub")} loading={loading && !d} />
          <SCard valueTone={G ? (G.ngr < 0 ? "neg" : "pos") : "default"} icon="💠" label="NGR" value={G ? formatMoney(G.ngr) : "—"} sub="GGR − Bonus − Provider − Commission" loading={loading && !d} />
          <SCard icon="🧮" label={t("monitor.affiliateDetail.kpi.manualWithdrawals.label")} value={G ? formatMoney(G.manual_withdrawals) : "—"} sub={G ? t("monitor.affiliateDetail.kpi.manualWithdrawals.sub", { deposits: formatMoney(G.manual_deposits) }) : undefined} loading={loading && !d} />
          <SCard icon="💎" label={t("monitor.affiliateDetail.kpi.ftdSum.label")} value={G ? formatMoney(G.ftd_sum) : "—"} sub={R ? t("monitor.affiliateDetail.kpi.ftdSum.sub", { n: formatInt(R.ftd) }) : undefined} loading={loading && !d} />
        </SCardGrid>
      </div>

      {/* glegend — «три разных дохода» + бонусы промо-кредит (борд :2878-2887) */}
      {d ? (
        <Banner>
          📊 <b>{t("monitor.affiliateDetail.glegend.title")}</b> <b>Net Profit</b> {t("monitor.affiliateDetail.glegend.netProfit")}{" "}
          <b>GGR</b> {t("monitor.affiliateDetail.glegend.ggr")} <b>NGR</b> {t("monitor.affiliateDetail.glegend.ngr")}{" "}
          {t("monitor.affiliateDetail.glegend.ggrSplit")} {t("monitor.affiliateDetail.glegend.ftdSum")}
          <br />
          🎁 <b>{t("monitor.affiliateDetail.glegend.bonusTitle")}</b> {t("monitor.affiliateDetail.glegend.bonusText")}{" "}
          <b>{t("monitor.affiliateDetail.glegend.wdLabel")}</b> {t("monitor.affiliateDetail.glegend.wdText")}{" "}
          {t("monitor.affiliateDetail.glegend.manualText")}
        </Banner>
      ) : null}

      {/* manual_note — показывается если есть ручные бонус-операции (борд :2913-2920) */}
      {d && G && (G.manual_withdrawals > 0 || G.manual_deposits > 0) ? (
        <div
          className="mt-3 rounded-card border border-beige border-l-[3px] bg-cream px-[18px] py-[15px] text-[13.5px] leading-relaxed"
          style={{ borderLeftColor: "#7c3aed" }}
        >
          ℹ️ <b>{t("monitor.affiliateDetail.manualNote.title")}</b>{" "}
          {t("monitor.affiliateDetail.manualNote.body", { wd: formatMoney(G.manual_withdrawals) })}
        </div>
      ) : null}

      {/* Funnel + distributions */}
      {d ? (
        <>
          <div className="mt-6 grid gap-4 lg:grid-cols-2">
            <ChartCard title={t("monitor.affiliateDetail.chart.funnel.title")} caption={t("monitor.affiliateDetail.chart.funnel.caption")}>
              <Funnel registrations={d.funnel.registrations} ftd={d.funnel.ftd} active={d.funnel.active} />
            </ChartCard>
            <ChartCard title={t("monitor.affiliateDetail.chart.life.title")} caption={t("monitor.affiliateDetail.chart.life.caption")}>
              <MiniBars data={d.charts.life} />
            </ChartCard>
            <ChartCard title={t("monitor.affiliateDetail.chart.regs.title")} caption={t("monitor.affiliateDetail.chart.regs.caption")}>
              <MiniBars data={d.charts.regs} />
            </ChartCard>
            <ChartCard title={t("monitor.affiliateDetail.chart.providers.title")} caption={t("monitor.affiliateDetail.chart.byPlayersCount")}>
              <MiniBars data={d.charts.prov} />
            </ChartCard>
            <ChartCard title={t("monitor.affiliateDetail.chart.money.title")} caption={t("monitor.affiliateDetail.chart.money.caption")}>
              <MoneyByMonth data={d.charts.money} />
            </ChartCard>
            <ChartCard title={t("monitor.affiliateDetail.chart.pays.title")} caption={t("monitor.affiliateDetail.chart.byPlayersCount")}>
              <MiniBars data={d.charts.pays} />
            </ChartCard>
          </div>

          <div className="mt-4">
            <ChartCard title={t("monitor.affiliateDetail.chart.topGames.title")} caption={t("monitor.affiliateDetail.chart.topGames.caption")}>
              <TopGamesTable rows={d.charts.top_games} />
            </ChartCard>
          </div>
        </>
      ) : null}

      {/* Players */}
      {d ? (
        <>
          <div className="mt-6 text-[11px] font-semibold uppercase tracking-[1px] text-primary">
            {t("monitor.affiliateDetail.playersHeading", { n: formatInt(d.players.total) })}
          </div>
          <div className="mt-3">
            <DetailPlayers block={d.players} loading={loading} onSort={onSort} onPage={setPage} />
          </div>
        </>
      ) : null}
    </>
  );
}
