"use client";

import {
  Modal,
  Badge,
  Eyebrow,
  SCard,
  ChartBox,
  Panel,
  DataTable,
  AccountTypeBadge,
  ErrorState,
  Skeleton,
  type Column,
} from "@/components/ui";
import { formatInt, formatMoneyMn } from "@/lib/format";
import { Chart } from "./Chart";
import { useResource } from "./kit";
import type { ReviewerData } from "./types";
import { useT } from "@/lib/i18n";
import { useAuditCategory } from "@/lib/auditCategory";

/**
 * Модалка «Оператор списаний» — контур расследования внутреннего фрода (paritet
 * с reviewer() борда, player_board.py:3204-3243). Открывается по клику на
 * reviewed_by в /audit (drill-down). Борд открывает отдельную страницу
 * /audit/reviewer/<rid>; здесь модалка, как GameDetailModal, чтобы риск-офицер
 * не терял контекст экрана аудита. Данные из GET /api/v1/audit/reviewer/<rid>.
 */

// палитра борда (общая с AuditScreen / GgrTabs)
const OR = "#2563eb";
const ST = "#64748b";
const HA = "#e5e7eb";
const INK = "#1e293b";

const mn = formatMoneyMn;
const f = formatInt;

type TopRow = ReviewerData["top"][number];

function ReviewerBody({ d }: { d: ReviewerData }) {
  const t = useT();
  const catLabel = useAuditCategory();

  // board :3237 c_cat — за что списывал (по notes), горизонтальный бар
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
      data: d.categories.map((x) => catLabel(x.cat)).reverse(),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: ST, fontSize: 12 },
    },
    series: [
      {
        type: "bar",
        data: d.categories.map((x) => x.sum).reverse(),
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

  // board :3239 c_mon — что списывал по месяцам, вертикальный бар
  const monOption = {
    grid: { left: 6, right: 14, top: 16, bottom: 6, containLabel: true },
    tooltip: { trigger: "axis", backgroundColor: "#fff", borderColor: HA, textStyle: { color: INK } },
    xAxis: {
      type: "category",
      data: d.monthly.map((x) => x.m),
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
        data: d.monthly.map((x) => x.v),
        barWidth: "56%",
        itemStyle: { color: OR, borderRadius: [4, 4, 0, 0] },
      },
    ],
  } as const;

  // board :3241 — топ выводов оператора (без колонки «Одобрил» — оператор один)
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
      key: "flag",
      header: t("money.audit.colFlag"),
      align: "left",
      render: (r) =>
        r.no_deposit_flag ? <Badge bg="#fee2e2" fg="#991b1b">{t("money.audit.flagNoDeposit")}</Badge> : null,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* board :3218-3219 / :3234 — бейдж легитимности + период работы */}
      <div className="flex flex-wrap items-center gap-2">
        {d.is_admin ? (
          <Badge bg="#dcfce7" fg="#166534">{t("money.reviewer.badgeAdmin")}</Badge>
        ) : (
          <Badge bg="#fee2e2" fg="#991b1b">{t("money.reviewer.badgeNotAdmin")}</Badge>
        )}
        <span className="text-steel text-[13px]">
          {t("money.reviewer.period", { from: d.period.from, to: d.period.to })}
        </span>
      </div>

      {/* board :3220-3222 — 5 KPI */}
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
        <SCard label={t("money.reviewer.kpiApproved")} value={f(d.kpi.count)} />
        <SCard label={t("money.reviewer.kpiSum")} value={mn(d.kpi.sum)} />
        <SCard label={t("money.reviewer.kpiBiggest")} value={mn(d.kpi.biggest)} />
        <SCard label={t("money.reviewer.kpiPlayers")} value={f(d.kpi.players)} />
        <SCard
          variant="alert"
          label={t("money.reviewer.kpiNoDeposit")}
          value={`${f(d.kpi.no_deposit_count)} · ${mn(d.kpi.no_deposit_sum)}`}
        />
      </div>

      {/* board :3236-3237 — за что списывал (по notes) */}
      <Eyebrow>{t("money.reviewer.sectionCategories")}</Eyebrow>
      <ChartBox title="" caption="">
        {d.categories.length ? (
          <Chart option={catOption} height={220} />
        ) : (
          <div className="text-steel text-[13px] py-8 text-center">{t("money.reviewer.noData")}</div>
        )}
      </ChartBox>

      {/* board :3238-3239 — что списывал по месяцам */}
      <Eyebrow>{t("money.reviewer.sectionMonthly")}</Eyebrow>
      <ChartBox title="" caption="">
        {d.monthly.length ? (
          <Chart option={monOption} height={230} />
        ) : (
          <div className="text-steel text-[13px] py-8 text-center">{t("money.reviewer.noData")}</div>
        )}
      </ChartBox>

      {/* board :3240-3241 — топ выводов, которые он одобрил (клик → карточка игрока) */}
      <Eyebrow>{t("money.reviewer.sectionTop")}</Eyebrow>
      <Panel>
        <DataTable
          columns={topCols}
          rows={d.top}
          getRowKey={(r, i) => `${r.player_id}-${i}`}
          getRowHref={(r) => `/players/${r.player_id}`}
          state={d.top.length ? "data" : "empty"}
          emptyTitle={t("money.audit.emptyGeneric")}
        />
      </Panel>
    </div>
  );
}

/** Обёртка: сеть только пока модалка открыта (Body монтируется при rid !== null). */
function ReviewerFetch({ rid }: { rid: string }) {
  const { state, data, error, reload } = useResource<ReviewerData>(
    `/api/v1/audit/reviewer/${encodeURIComponent(rid)}`,
  );
  if (state === "loading") return <Skeleton className="h-[360px]" />;
  if (state === "error") return <ErrorState description={error ?? undefined} onRetry={reload} />;
  if (!data) return null;
  return <ReviewerBody d={data} />;
}

export function ReviewerModal({ rid, onClose }: { rid: string | null; onClose: () => void }) {
  const t = useT();
  return (
    <Modal
      open={rid !== null}
      onClose={onClose}
      widthClass="max-w-4xl"
      title={
        <span className="flex items-baseline gap-2 flex-wrap">
          {t("money.reviewer.title")}
          <em className="not-italic font-bold text-primary">{rid}</em>
        </span>
      }
    >
      {rid !== null ? <ReviewerFetch rid={rid} /> : null}
    </Modal>
  );
}
