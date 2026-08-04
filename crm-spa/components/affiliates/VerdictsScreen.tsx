"use client";

import { useMemo, useState } from "react";
import {
  PageHeader,
  Badge,
  Banner,
  Tabs,
  DataTable,
  Pill,
  PillRow,
  FormField,
  Select,
  ErrorState,
  type Column,
  type TabItem,
} from "@/components/ui";
import { formatInt, formatMoney, formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import { useFlaskData } from "@/components/marketing/useFlaskData";

/**
 * /verdicts — Traffic module screen "Source verdicts" (W2-T2). One row per
 * source (dim=source) or affiliate (dim=affiliate): the day-5 cohort quality
 * forecast (pred LTV D90) turned into a scale/watch/disable/maturing call.
 * Data 1:1 with GET /api/v1/traffic/verdicts (api/traffic.py). Thresholds are
 * drafts — see the legend note (to be agreed with Vasiliy).
 */

type Dim = "source" | "affiliate";
type Verdict = "scale" | "watch" | "disable" | "maturing";
type Confidence = "high" | "mid" | "low";

/** Day-5 threshold — mirrors MATURING_AGE_DAYS in api/traffic.py (for the "in N days" copy). */
const MATURING_AGE_DAYS = 5;

interface VerdictRow {
  source: string;
  players: number;
  players_7d: number;
  ftd: number;
  ftd_sum: number;
  deposits: number;
  pred_d90_sum: number;
  pred_d90_avg: number;
  p10_sum: number;
  p90_sum: number;
  ggr_real: number;
  age_days: number;
  verdict: Verdict;
  confidence: Confidence;
}

interface VerdictsResponse {
  rows: VerdictRow[];
  meta: {
    asof: string | null;
    median_ltv: number;
    global_ftd_rate: number;
    days: number;
    dim: Dim;
  };
}

/** Filled pill tones — kept inside the board palette (green pos / red neg / steel / muted). */
const VERDICT_STYLE: Record<Verdict, { bg: string; fg: string }> = {
  scale: { bg: "#e7f6ee", fg: "#1f9d57" },
  watch: { bg: "#eef2f6", fg: "#475569" },
  disable: { bg: "#fdeaea", fg: "#dc2626" },
  maturing: { bg: "#f1f5f9", fg: "#94a3b8" },
};

const CONF_STYLE: Record<Confidence, { bg: string; fg: string }> = {
  high: { bg: "#e7f6ee", fg: "#1f9d57" },
  mid: { bg: "#eef2f6", fg: "#475569" },
  low: { bg: "#f1f5f9", fg: "#94a3b8" },
};

const DAY_OPTIONS = [7, 14, 30, 90] as const;

export function VerdictsScreen() {
  const t = useT();
  const [dim, setDim] = useState<Dim>("source");
  const [days, setDays] = useState<number>(30);

  const path = useMemo(
    () => `/api/v1/traffic/verdicts?dim=${dim}&days=${days}`,
    [dim, days],
  );
  const { state, data, error, reload } = useFlaskData<VerdictsResponse>(path);
  const loading = state === "loading";
  const meta = data?.meta;

  const tabs: TabItem[] = [
    { key: "source", label: t("traffic.verdicts.tab.source") },
    { key: "affiliate", label: t("traffic.verdicts.tab.affiliate") },
  ];

  function VerdictBadge({ row }: { row: VerdictRow }) {
    const st = VERDICT_STYLE[row.verdict];
    let label: string;
    if (row.verdict === "maturing") {
      const left = MATURING_AGE_DAYS - row.age_days;
      label =
        left > 0
          ? t("traffic.verdicts.verdict.maturing", { n: left })
          : t("traffic.verdicts.verdict.maturingSmall");
    } else {
      label = t(`traffic.verdicts.verdict.${row.verdict}` as MessageKey);
    }
    return (
      <Badge bg={st.bg} fg={st.fg}>
        {label}
      </Badge>
    );
  }

  function ConfBadge({ level }: { level: Confidence }) {
    const st = CONF_STYLE[level];
    return (
      <Badge bg={st.bg} fg={st.fg}>
        {t(`traffic.verdicts.conf.${level}` as MessageKey)}
      </Badge>
    );
  }

  const columns: Column<VerdictRow>[] = [
    {
      key: "source",
      header: dim === "affiliate"
        ? t("traffic.verdicts.col.affiliate")
        : t("traffic.verdicts.col.source"),
      align: "left",
      id: true,
      render: (r) => <span className="break-all">{r.source}</span>,
    },
    {
      key: "players",
      header: t("traffic.verdicts.col.players"),
      mono: true,
      render: (r) => (
        <span title={t("traffic.verdicts.col.playersTitle")}>
          {formatInt(r.players)}
          <span className="text-steel"> ({formatInt(r.players_7d)})</span>
        </span>
      ),
    },
    {
      key: "ftd",
      header: t("traffic.verdicts.col.ftd"),
      mono: true,
      render: (r) => <span title={t("traffic.verdicts.col.ftdTitle")}>{formatInt(r.ftd)}</span>,
    },
    {
      key: "deposits",
      header: t("traffic.verdicts.col.deposits"),
      mono: true,
      render: (r) => <span title={t("traffic.verdicts.col.depositsTitle")}>{formatMoney(r.deposits)}</span>,
    },
    {
      key: "predSum",
      header: t("traffic.verdicts.col.predSum"),
      mono: true,
      render: (r) => <span title={t("traffic.verdicts.col.predSumTitle")}>{formatMoney(r.pred_d90_sum)}</span>,
    },
    {
      key: "predAvg",
      header: t("traffic.verdicts.col.predAvg"),
      mono: true,
      render: (r) => <span title={t("traffic.verdicts.col.predAvgTitle")}>{formatMoney(r.pred_d90_avg)}</span>,
    },
    {
      key: "confidence",
      header: t("traffic.verdicts.col.confidence"),
      align: "left",
      render: (r) => <ConfBadge level={r.confidence} />,
    },
    {
      key: "verdict",
      header: t("traffic.verdicts.col.verdict"),
      align: "left",
      render: (r) => <VerdictBadge row={r} />,
    },
  ];

  const tableState =
    loading ? "loading" : data && data.rows.length === 0 ? "empty" : "data";

  return (
    <>
      <PageHeader
        title={t("traffic.verdicts.title")}
        lead={t("traffic.verdicts.lead")}
        right={
          <PillRow>
            {meta?.asof ? <Pill>{t("traffic.verdicts.pill.asOf", { date: formatDate(meta.asof) })}</Pill> : null}
            {meta ? <Pill>{t("traffic.verdicts.pill.median", { v: formatMoney(meta.median_ltv) })}</Pill> : null}
          </PillRow>
        }
      />

      {state === "error" ? (
        <div className="mt-6">
          <ErrorState
            title={t("traffic.verdicts.error.title")}
            description={error ?? t("traffic.verdicts.error.desc")}
            onRetry={reload}
          />
        </div>
      ) : (
        <>
          <div className="mt-5 flex flex-wrap items-end justify-between gap-3">
            <Tabs tabs={tabs} value={dim} onChange={(k) => setDim(k as Dim)} />
            <FormField label={t("traffic.verdicts.days.label")} className="w-auto">
              <Select
                className="!w-auto"
                value={String(days)}
                onChange={(e) => setDays(Number(e.target.value))}
              >
                {DAY_OPTIONS.map((d) => (
                  <option key={d} value={d}>
                    {t("traffic.verdicts.days.opt", { n: d })}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>

          <div className="mt-4 overflow-hidden rounded-card border border-hair bg-canvas">
            <DataTable
              columns={columns}
              rows={data?.rows ?? []}
              getRowKey={(r) => r.source}
              state={tableState}
              emptyTitle={t("traffic.verdicts.empty.title")}
              emptyDescription={t("traffic.verdicts.empty.desc")}
            />
          </div>

          <Banner>
            <b>{t("traffic.verdicts.legend.label")}</b>{" "}
            <Badge bg={VERDICT_STYLE.scale.bg} fg={VERDICT_STYLE.scale.fg}>{t("traffic.verdicts.verdict.scale")}</Badge>{" "}
            {t("traffic.verdicts.legend.scale")} ·{" "}
            <Badge bg={VERDICT_STYLE.watch.bg} fg={VERDICT_STYLE.watch.fg}>{t("traffic.verdicts.verdict.watch")}</Badge>{" "}
            {t("traffic.verdicts.legend.watch")} ·{" "}
            <Badge bg={VERDICT_STYLE.disable.bg} fg={VERDICT_STYLE.disable.fg}>{t("traffic.verdicts.verdict.disable")}</Badge>{" "}
            {t("traffic.verdicts.legend.disable")} ·{" "}
            <Badge bg={VERDICT_STYLE.maturing.bg} fg={VERDICT_STYLE.maturing.fg}>{t("traffic.verdicts.verdict.maturingSmall")}</Badge>{" "}
            {t("traffic.verdicts.legend.maturing")}.
            <br />
            <span className="text-steel">{t("traffic.verdicts.legend.draft")}</span>
          </Banner>
        </>
      )}
    </>
  );
}
