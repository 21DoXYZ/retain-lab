"use client";

import {
  PageHeader,
  ModuleHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  ChartBox,
  Panel,
  DataTable,
  Badge,
  AccountTypeBadge,
  Pill,
  PillRow,
  ErrorState,
  type Column,
} from "@/components/ui";
import { useState } from "react";
import { formatInt, formatMoneyMn } from "@/lib/format";
import { Chart } from "@/components/money/Chart";
import { useResource } from "@/components/money/kit";
import { ReviewerModal } from "@/components/money/ReviewerModal";
import type { AuditData } from "@/components/money/types";
import { useT } from "@/lib/i18n";
import { useAuditCategory } from "@/lib/auditCategory";

/**
 * /audit — «Аудит ручных списаний» (paritet с audit() борда). Это НЕ выплаты
 * игрокам, а списания казино (отмена бонус-выигрышей, нарушений, тест-операции).
 * Данные из /api/v1/audit. Роли: director/finance/risk_officer/head_retention/super_admin.
 */

const OR = "#465fff";
const ST = "#667085";
const HA = "#e5e7eb";
const INK = "#101828";

function ChartSkeleton({ height }: { height: number }) {
  return <div className="animate-pulse rounded-md bg-hair2/60" style={{ height }} />;
}

type ReviewerRow = AuditData["reviewers"][number];
type TopRow = AuditData["top"][number];
type NoDepRow = AuditData["no_deposit"]["rows"][number];
type TestRow = AuditData["test_ops"]["rows"][number];

const mn = formatMoneyMn;
const f = formatInt;

export function AuditScreen() {
  const t = useT();
  const catLabel = useAuditCategory();
  const { state, data, error, reload } = useResource<AuditData>("/api/v1/audit");
  const loading = state !== "data";
  const d = data;

  // drill-down на оператора (board rev_link :3132-3135) → модалка reviewer()
  const [reviewerId, setReviewerId] = useState<string | null>(null);

  const catOption = {
    grid: { left: 6, right: 66, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: "#fff",
      borderColor: HA,
      textStyle: { color: INK },
      formatter: (p: { name: string; value: number }) => `${p.name}: ${(p.value / 1e6).toFixed(2)}M ₺`,
    },
    xAxis: { type: "value", axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
    yAxis: {
      type: "category",
      data: (d?.categories ?? []).map((x) => catLabel(x.cat)).reverse(),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: ST, fontSize: 12 },
    },
    series: [
      {
        type: "bar",
        data: (d?.categories ?? []).map((x) => x.sum).reverse(),
        barWidth: "64%",
        itemStyle: { color: OR, borderRadius: [0, 5, 5, 0] },
        label: {
          show: true,
          position: "right",
          color: ST,
          formatter: (p: { value: number }) => `${(p.value / 1e6).toFixed(1)}M`,
        },
      },
    ],
  } as const;

  const monOption = {
    grid: { left: 6, right: 14, top: 16, bottom: 6, containLabel: true },
    tooltip: { trigger: "axis", backgroundColor: "#fff", borderColor: HA, textStyle: { color: INK } },
    xAxis: {
      type: "category",
      data: (d?.monthly ?? []).map((x) => x.m),
      axisLine: { lineStyle: { color: HA } },
      axisTick: { show: false },
      axisLabel: { color: ST },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: HA } },
      axisLabel: { color: ST, formatter: (v: number) => `${v / 1e6}M` },
    },
    series: [
      {
        type: "bar",
        data: (d?.monthly ?? []).map((x) => x.v),
        barWidth: "56%",
        itemStyle: { color: OR, borderRadius: [4, 4, 0, 0] },
      },
    ],
  } as const;

  const reviewerCols: Column<ReviewerRow>[] = [
    {
      key: "rb",
      header: t("money.audit.colOperatorId"),
      id: true,
      // board :3157 rev_link(rb) — переход в reviewer(); в SPA открываем модалку
      render: (r) =>
        r.reviewed_by ? (
          <button
            type="button"
            onClick={() => setReviewerId(r.reviewed_by)}
            className="text-primary font-medium hover:underline cursor-pointer"
          >
            {r.reviewed_by}
          </button>
        ) : (
          "—"
        ),
    },
    {
      key: "status",
      header: t("money.audit.colStatus"),
      align: "left",
      render: (r) =>
        r.is_admin ? (
          <Badge bg="#dcfce7" fg="#166534">{t("money.audit.badgeAdmin")}</Badge>
        ) : (
          <Badge bg="#fee2e2" fg="#991b1b">{t("money.audit.badgeNotAdmin")}</Badge>
        ),
    },
    { key: "count", header: t("money.audit.colOps"), mono: true, render: (r) => f(r.count) },
    { key: "sum", header: t("money.audit.colSum"), mono: true, render: (r) => mn(r.sum) },
    {
      key: "unclear",
      header: t("money.audit.colUnclearPct"),
      mono: true,
      render: (r) =>
        r.unclear_pct >= 40 ? (
          <span className="text-neg font-semibold">{f(r.unclear_pct)}%</span>
        ) : (
          `${f(r.unclear_pct)}%`
        ),
    },
  ];

  const topCols: Column<TopRow>[] = [
    {
      key: "player",
      header: t("money.audit.colPlayer"),
      id: true,
      render: (r) => (
        <>
          {r.player_id}
          <AccountTypeBadge type={r.account_type} />
        </>
      ),
    },
    { key: "amount", header: t("money.audit.colWithdrawn"), mono: true, render: (r) => mn(r.amount) },
    { key: "dep", header: t("money.audit.colDepositedTotal"), mono: true, render: (r) => `${f(r.deposited)} ₺` },
    { key: "date", header: t("money.audit.colDate"), mono: true, render: (r) => r.date },
    {
      key: "rb",
      header: t("money.audit.colApprovedBy"),
      id: true,
      // board :3164 rev_link(rb, True) — stopPropagation, чтобы не уйти в карточку игрока
      render: (r) =>
        r.reviewed_by ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setReviewerId(r.reviewed_by);
            }}
            className="text-primary font-medium hover:underline cursor-pointer"
          >
            {r.reviewed_by}
          </button>
        ) : (
          "—"
        ),
    },
    {
      key: "flag",
      header: t("money.audit.colFlag"),
      align: "left",
      render: (r) =>
        r.no_deposit_flag ? <Badge bg="#fee2e2" fg="#991b1b">{t("money.audit.flagNoDeposit")}</Badge> : null,
    },
  ];

  const noDepCols: Column<NoDepRow>[] = [
    {
      key: "player",
      header: t("money.audit.colPlayer"),
      id: true,
      render: (r) => (
        <>
          {r.player_id}
          <AccountTypeBadge type={r.account_type} />
        </>
      ),
    },
    { key: "wd", header: t("money.audit.colWrittenOff"), mono: true, render: (r) => mn(r.withdrawn) },
    { key: "dep", header: t("money.audit.colDepositedTotal"), mono: true, render: (r) => `${f(r.deposited)} ₺` },
    { key: "ops", header: t("money.audit.colOps"), mono: true, render: (r) => f(r.ops) },
  ];

  const testCols: Column<TestRow>[] = [
    {
      key: "acct",
      header: t("money.audit.colAccount"),
      id: true,
      render: (r) => (
        <>
          {r.player_id}
          <AccountTypeBadge type={r.account_type} />
        </>
      ),
    },
    { key: "sum", header: t("money.audit.colSum"), mono: true, render: (r) => mn(r.sum) },
    { key: "ops", header: t("money.audit.colOps"), mono: true, render: (r) => f(r.ops) },
  ];

  return (
    <>
      <PageHeader
        title={t("money.audit.title")}
        accent={t("money.audit.accent")}
        lead={t("money.audit.lead")}
        right={
          <PillRow>
            <Pill live>{t("money.audit.pillLive")}</Pill>
          </PillRow>
        }
      />

      <ModuleHeader module="risk" />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <SCardGrid className="mt-6">
            <SCard
              loading={loading}
              variant="alert"
              icon="🧾"
              label={t("money.audit.kpi.total.label")}
              value={mn(d?.kpi.total)}
              sub={t("money.audit.kpi.total.sub", { count: f(d?.kpi.count) })}
            />
            <SCard
              loading={loading}
              icon="👤"
              label={t("money.audit.kpi.reviewers.label")}
              value={f(d?.kpi.reviewers)}
              sub={t("money.audit.kpi.reviewers.sub")}
            />
            <SCard
              loading={loading}
              variant="alert"
              icon="💥"
              label={t("money.audit.kpi.biggest.label")}
              value={mn(d?.kpi.biggest)}
              sub={t("money.audit.kpi.biggest.sub")}
            />
            <SCard
              loading={loading}
              icon="🛡"
              label={t("money.audit.kpi.adminAccounts.label")}
              value={f(d?.kpi.admin_accounts)}
              sub={t("money.audit.kpi.adminAccounts.sub")}
            />
          </SCardGrid>

          <Eyebrow>{t("money.audit.sectionCategories")}</Eyebrow>
          <ChartBox title="" caption={t("money.audit.categoriesCaption")}>
            {loading ? <ChartSkeleton height={270} /> : <Chart option={catOption} height={270} />}
          </ChartBox>

          <Eyebrow>{t("money.audit.sectionMonthly")}</Eyebrow>
          <ChartBox title="" caption={t("money.audit.monthlyCaption")}>
            {loading ? <ChartSkeleton height={230} /> : <Chart option={monOption} height={230} />}
          </ChartBox>

          <Eyebrow>
            {t("money.audit.sectionReviewers")}{" "}
            <span className="text-steel font-normal normal-case tracking-normal">
              {t("money.audit.reviewersNote")}
            </span>
          </Eyebrow>
          <Panel>
            <DataTable
              columns={reviewerCols}
              rows={d?.reviewers ?? []}
              getRowKey={(r) => r.reviewed_by}
              state={loading ? "loading" : (d?.reviewers.length ? "data" : "empty")}
              emptyTitle={t("money.audit.emptyReviewers")}
            />
          </Panel>

          <Eyebrow>{t("money.audit.sectionTop")}</Eyebrow>
          <Panel>
            <DataTable
              columns={topCols}
              rows={d?.top ?? []}
              getRowKey={(r, i) => `${r.player_id}-${i}`}
              getRowHref={(r) => `/players/${r.player_id}`}
              state={loading ? "loading" : (d?.top.length ? "data" : "empty")}
              emptyTitle={t("money.audit.emptyGeneric")}
            />
          </Panel>

          <Eyebrow>{t("money.audit.sectionNoDeposit")}</Eyebrow>
          {d ? (
            <p className="-mt-1 mb-3 text-steel text-[14.5px]">
              {t("money.audit.noDeposit.lead", { count: d.no_deposit.count })}{" "}
              <b className="text-primary">{mn(d.no_deposit.total)}</b> {t("money.audit.noDeposit.tailPrefix")}{" "}
              <b>{t("money.audit.noDeposit.bonusWinBold")}</b> {t("money.audit.noDeposit.tailSuffix")}
            </p>
          ) : null}
          <Panel>
            <DataTable
              columns={noDepCols}
              rows={d?.no_deposit.rows ?? []}
              getRowKey={(r, i) => `${r.player_id}-${i}`}
              getRowHref={(r) => `/players/${r.player_id}`}
              state={loading ? "loading" : (d?.no_deposit.rows.length ? "data" : "empty")}
              emptyTitle={t("money.audit.emptyGeneric")}
            />
          </Panel>

          <Eyebrow>{t("money.audit.sectionTestOps")}</Eyebrow>
          {d ? (
            <p className="-mt-1 mb-3 text-steel text-[14.5px]">
              {t("money.audit.testOps.lead", { count: d.test_ops.count })}{" "}
              <b className="text-primary">{mn(d.test_ops.total)}</b> {t("money.audit.testOps.tail")}
            </p>
          ) : null}
          <Panel>
            <DataTable
              columns={testCols}
              rows={d?.test_ops.rows ?? []}
              getRowKey={(r, i) => `${r.player_id}-${i}`}
              getRowHref={(r) => `/players/${r.player_id}`}
              state={loading ? "loading" : (d?.test_ops.rows.length ? "data" : "empty")}
              emptyTitle={t("money.audit.emptyGeneric")}
            />
          </Panel>
        </>
      )}

      <ReviewerModal rid={reviewerId} onClose={() => setReviewerId(null)} />
    </>
  );
}
