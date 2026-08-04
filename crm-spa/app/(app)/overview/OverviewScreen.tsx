"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  PageHeader,
  ModuleHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Pill,
  PillRow,
  DateInput,
  Button,
  ErrorState,
} from "@/components/ui";
import { formatInt, formatMoneyMn, formatDate } from "@/lib/format";
import { useResource, MoneySpark } from "@/components/money/kit";
import { IncomeLegend } from "@/components/money/IncomeLegend";
import { DeltaBadge } from "@/components/money/DeltaBadge";
import { GeoRatioTable } from "@/components/money/GeoRatioTable";
import type { OverviewData } from "@/components/money/types";
import { useT } from "@/lib/i18n";

/**
 * /overview — «Обзор». Деньги/GGR/NGR за ВЫБРАННЫЙ период (?from&to) считаются
 * тем же _ggr_kpis, что страница GGR → цифры совпадают. Дейтпикер: пусто →
 * бэкенд отдаёт дефолт (30 дней) и период, инпуты подхватывают его один раз.
 * Счётчики игроков (всего/активные/VIP) — снимок текущего состояния (не период).
 */
export function OverviewScreen() {
  const t = useT();
  const [applied, setApplied] = useState<{ from: string; to: string }>({ from: "", to: "" });
  const [draft, setDraft] = useState<{ from: string; to: string }>({ from: "", to: "" });
  const [compare, setCompare] = useState(false);   // сравнение с прошлым периодом (0.2)

  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (applied.from) p.set("from", applied.from);
    if (applied.to) p.set("to", applied.to);
    if (compare) p.set("compare", "1");
    const qs = p.toString();
    return `/api/v1/money/overview${qs ? `?${qs}` : ""}`;
  }, [applied, compare]);

  const { state, data, error, reload } = useResource<OverviewData>(path);

  // подхватить дефолтный период из ответа в пустые инпуты (как GGR)
  useEffect(() => {
    if (data?.period) setDraft((d) => (d.from || d.to ? d : { from: data.period.from, to: data.period.to }));
  }, [data]);

  const loading = state === "loading";
  const d = data;

  const mn = formatMoneyMn;
  const f = formatInt;

  // дельта по метрике из блока сравнения (0.2). group/key — как в ответе бэка.
  const cmp = d?.compare ?? null;
  function delta(group: "cash" | "game" | "ngr", key: string) {
    if (!cmp) return undefined;
    const dd = cmp.delta[group] as Record<string, { pct: number | null } | undefined>;
    const v = dd?.[key];
    if (!v) return undefined;
    return <DeltaBadge pct={v.pct} />;
  }

  function applyPeriod(e: FormEvent) {
    e.preventDefault();
    setApplied({ from: draft.from, to: draft.to });
  }

  return (
    <>
      <PageHeader
        title={t("money.overview.title")}
        accent={t("money.overview.accent")}
        lead={t("money.overview.lead")}
        right={
          <PillRow>
            <Pill>{d ? `${d.period.from} → ${d.period.to}` : "…"}</Pill>
            <Pill>TRY</Pill>
          </PillRow>
        }
      />

      <ModuleHeader module="analytics" />

      {/* Период: деньги/GGR/NGR пересчитываются от выбранной даты (счётчики
          игроков — текущий снимок, на них период не влияет). */}
      <form onSubmit={applyPeriod} className="mt-4 flex flex-wrap items-end gap-2">
        <label className="text-[12px] text-steel">
          {t("money.overview.periodFrom")}
          <DateInput value={draft.from} onChange={(e) => setDraft((x) => ({ ...x, from: e.target.value }))} className="mt-1 block" />
        </label>
        <label className="text-[12px] text-steel">
          {t("money.overview.periodTo")}
          <DateInput value={draft.to} onChange={(e) => setDraft((x) => ({ ...x, to: e.target.value }))} className="mt-1 block" />
        </label>
        <Button variant="brand" size="sm" type="submit">{t("money.overview.periodApply")}</Button>
        <label className="text-[12px] text-steel flex items-center gap-1.5 ml-1 cursor-pointer select-none">
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
          {t("compare.toggle")}
        </label>
      </form>
      {compare && d?.compare ? (
        <p className="mt-1.5 text-[12px] text-steel">
          {t("compare.caption", { from: d.compare.period.from, to: d.compare.period.to })}
        </p>
      ) : null}

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          {/* ── Игроки и активность ── */}
          <Eyebrow>{t("money.overview.sectionPlayers")}</Eyebrow>
          <SCardGrid>
            <SCard
              loading={loading}
              icon="👥"
              label={t("money.overview.totalPlayers.label")}
              value={f(d?.players.total)}
              sub={t("money.overview.totalPlayers.sub")}
            />
            <SCard
              loading={loading}
              icon="🎮"
              label={t("money.overview.played.label")}
              value={f(d?.players.played)}
              sub={t("money.overview.played.sub", { pct: d?.players.played_pct ?? 0 })}
            />
            <SCard
              loading={loading}
              icon="💳"
              label={t("money.overview.depositors.label")}
              value={f(d?.players.depositors)}
              sub={t("money.overview.depositors.sub", { pct: d?.players.depositors_pct ?? 0 })}
            />
            <SCard
              loading={loading}
              variant="cream"
              icon="🔥"
              label={t("money.overview.active30.label")}
              value={f(d?.players.active30)}
              sub={t("money.overview.active30.sub", { n: f(d?.players.active7) })}
              spark={d ? <MoneySpark values={d.series.mau} /> : undefined}
            />
          </SCardGrid>

          {/* ── Деньги (кэш) — якорь #cash ── */}
          <div id="cash">
            <Eyebrow>
              {t("money.overview.sectionCash")}{" "}
              <span className="text-steel font-normal normal-case tracking-normal">
                {t("money.overview.sectionCashNote")}
              </span>
            </Eyebrow>
          </div>
          <SCardGrid>
            <SCard
              loading={loading}
              icon="💰"
              label={t("money.overview.deposits.label")}
              value={mn(d?.cash.deposits)}
              delta={delta("cash","deposits")}
              sub={t("money.overview.deposits.sub")}
              spark={d ? <MoneySpark values={d.series.dep} /> : undefined}
            />
            <SCard
              loading={loading}
              icon="💸"
              label={t("money.overview.withdrawals.label")}
              value={mn(d?.cash.withdrawals)}
              delta={delta("cash","withdrawals")}
              sub={t("money.overview.withdrawals.subRatio", { pct: d?.cash.wd_dep_ratio ?? 0 })}
              spark={d ? <MoneySpark values={d.series.wd} /> : undefined}
            />
            <SCard
              loading={loading}
              variant="cream"
              icon="🎯"
              label={t("money.overview.netCash.label")}
              value={mn(d?.cash.net_cash)}
              delta={delta("cash","net_cash")}
              sub={t("money.overview.netCash.sub", { pct: d?.cash.margin ?? 0 })}
            />
            <SCard
              loading={loading}
              variant="cream"
              icon="🎁"
              label={t("money.overview.bonusCost.label")}
              value={mn(d?.cash.bonus_cost)}
              delta={delta("cash","bonus_cost")}
              sub={t("money.overview.bonusCost.sub", { pct: d?.cash.bonus_ratio ?? 0 })}
            />
          </SCardGrid>

          {/* Разбивка выводы/депозиты по гео (Д3) — под блоком кэша. */}
          {d?.geo?.length ? (
            <>
              <Eyebrow>{t("geo.title")}</Eyebrow>
              <GeoRatioTable geo={d.geo} />
            </>
          ) : null}

          {/* ── Игра ── */}
          <Eyebrow>{t("money.overview.sectionGame")}</Eyebrow>
          <SCardGrid>
            <SCard
              loading={loading}
              variant="orange"
              icon="🎯"
              label={t("money.overview.ggr.label")}
              value={mn(d?.game.ggr)}
              delta={delta("game","ggr")}
              sub={t("money.overview.ggr.sub", { pct: d?.game.hold ?? 0 })}
              spark={d ? <MoneySpark values={d.series.ggr} /> : undefined}
            />
            <SCard
              loading={loading}
              icon="📊"
              label={t("money.overview.rtp.label")}
              value={`${d?.game.rtp ?? 0}%`}
              sub={t("money.overview.rtp.sub")}
            />
            <SCard
              loading={loading}
              icon="🎲"
              label={t("money.overview.bet.label")}
              value={mn(d?.game.bets)}
              delta={delta("game","bets")}
              sub={t("money.overview.bet.sub")}
            />
            <SCard
              loading={loading}
              icon="🏆"
              label={t("money.overview.win.label")}
              value={mn(d?.game.wins)}
              delta={delta("game","wins")}
              sub={t("money.overview.win.sub")}
            />
          </SCardGrid>

          {/* Дисклеймер «три разных дохода» — ровно там, где Net Profit, GGR и
              NGR стоят рядом (ТЗ по копирайту, задача 6.1). */}
          <div className="mt-4">
            <IncomeLegend />
          </div>

          {/* ── NGR и издержки ── */}
          <Eyebrow>{t("money.overview.sectionNgr")}</Eyebrow>
          <SCardGrid>
            <SCard
              loading={loading}
              variant="orange"
              icon="💠"
              label={t("money.overview.ngr.label")}
              value={mn(d?.ngr.ngr)}
              delta={delta("ngr","ngr")}
              sub={t("money.overview.ngr.sub")}
            />
            <SCard
              loading={loading}
              icon="🏭"
              label={t("money.overview.providerCost.label")}
              value={mn(d?.ngr.provider_cost)}
              delta={delta("ngr","provider_cost")}
              sub={
                d?.ngr.provider_resolved
                  ? t("money.overview.providerCost.subResolved")
                  : t("money.overview.providerCost.subUnresolved")
              }
            />
            <SCard
              loading={loading}
              icon="🤝"
              label={t("money.overview.affiliateCommission.label")}
              value={mn(d?.ngr.affiliate_commission)}
              delta={delta("ngr","affiliate_commission")}
              sub={t("money.overview.affiliateCommission.sub")}
            />
            <SCard
              loading={loading}
              icon="🎮"
              label={t("money.overview.bonusUsage.label")}
              value={mn(d?.ngr.bonus_usage)}
              sub={t("money.overview.bonusUsage.sub")}
            />
          </SCardGrid>

          {/* ── Бонус-списания и риск ── */}
          <div id="risk">
            <Eyebrow>{t("money.overview.sectionRisk")}</Eyebrow>
          </div>
          <SCardGrid>
            <SCard
              loading={loading}
              variant="alert"
              icon="🧾"
              label={t("money.overview.manualWithdrawals.label")}
              value={mn(d?.risk.manual_withdrawals)}
              sub={t("money.overview.manualWithdrawals.sub")}
            />
            <SCard
              loading={loading}
              icon="🚨"
              label={t("money.overview.vipAtRisk.label")}
              value={f(d?.risk.vip_at_risk)}
              sub={t("money.overview.vipAtRisk.sub")}
            />
            <SCard
              loading={loading}
              icon="⛔"
              label={t("money.overview.depRejected.label")}
              value={mn(d?.risk.dep_rejected)}
              sub={t("money.overview.depRejected.sub")}
            />
            <SCard
              loading={loading}
              icon="💵"
              label={t("money.overview.winners.label")}
              value={f(d?.risk.winners)}
              sub={t("money.overview.winners.sub")}
            />
          </SCardGrid>

          <p className="mt-8 text-[11.5px] text-stone">
            {t("money.overview.footer", { date: d?.asof ? formatDate(d.asof) : "—" })}
          </p>
        </>
      )}
    </>
  );
}
