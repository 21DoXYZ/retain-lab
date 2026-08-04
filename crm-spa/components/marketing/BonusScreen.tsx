"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import {
  PageHeader,
  ModuleHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Panel,
  Card,
  Banner,
  ChipBar,
  Chip,
  Select,
  DateInput,
  Input,
  EmptyState,
  ErrorState,
  DataTable,
  type Column,
} from "@/components/ui";
import { formatInt, formatPct } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { useFlaskData } from "./useFlaskData";
import { BonusEconomicsKpi } from "./BonusEconomicsKpi";
import { BonusFunnel } from "./BonusFunnel";
import type { BonusResponse, BonusEconomicsResponse } from "./types";

type EffRow = BonusResponse["effectiveness"][number];
type RecRow = BonusResponse["recommendations"][number];

// ── классификатор типа бонуса (ключи = ASCII-ключи бэкенда) ──────────────────
const TYPE_KEYS = ["freespin", "nodeposit", "cashback", "deposit_match", "manual", "other"] as const;
const TYPE_LABEL: Record<(typeof TYPE_KEYS)[number], MessageKey> = {
  freespin: "marketing.eco.type.freespin",
  nodeposit: "marketing.eco.type.nodeposit",
  cashback: "marketing.eco.type.cashback",
  deposit_match: "marketing.eco.type.deposit_match",
  manual: "marketing.eco.type.manual",
  other: "marketing.eco.type.other",
};
const VIP_LEVELS = [0, 1, 2, 3, 4, 5];

// ── URL-state фильтров (SSR-безопасно; паттерн BonusSection) ─────────────────
/** Стартовое значение фильтра из URL. */
function urlGet(key: string): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(key) ?? "";
}
/** Зеркалим фильтры в URL без перезагрузки (history.replaceState). */
function urlSync(patch: Record<string, string>) {
  if (typeof window === "undefined") return;
  const qs = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(patch)) {
    if (v) qs.set(k, v);
    else qs.delete(k);
  }
  const s = qs.toString();
  window.history.replaceState(null, "", s ? `${window.location.pathname}?${s}` : window.location.pathname);
}

const emptySubscribe = () => () => {};
/** true только после гидратации (SSR/первый клиентский рендер — false). */
const useHydrated = () => useSyncExternalStore(emptySubscribe, () => true, () => false);

interface UrlFilters {
  from: string;
  to: string;
  type: string;
  campaign: string;
  aff: string;
  vip: string;
}

/**
 * BonusScreen — «Бонусы: эффект» + новая Бонус-экономика (ТЗ §3.3).
 * Порядок: фильтры → (1) KPI P&L → (2) воронка → abuse-плашка →
 * (3) существующий uplift-блок → (4) существующая таблица типов.
 * Экономика (KPI/воронка/abuse) — из /api/v1/bonus/economics с фильтрами в URL;
 * uplift/типы — из существующего /api/v1/bonus (математику НЕ трогаем).
 *
 * URL читаем ТОЛЬКО после гидратации: SSR-HTML и первый клиентский рендер
 * совпадают (иначе hydration mismatch при заходе по ссылке с фильтрами).
 */
export function BonusScreen() {
  const t = useT();
  const hydrated = useHydrated();
  const init = useMemo<UrlFilters | null>(
    () =>
      hydrated
        ? {
            from: urlGet("from"),
            to: urlGet("to"),
            type: urlGet("type"),
            campaign: urlGet("campaign"),
            aff: urlGet("aff"),
            vip: urlGet("vip"),
          }
        : null,
    [hydrated],
  );

  return (
    <>
      <PageHeader title={<>{t("marketing.bonus.title")}</>} lead={t("marketing.bonus.lead")} />
      <ModuleHeader module="bonuseco" />
      {init ? <BonusScreenInner init={init} /> : null}
    </>
  );
}

function BonusScreenInner({ init }: { init: UrlFilters }) {
  const t = useT();

  const [fromF, setFromF] = useState<string>(init.from);
  const [toF, setToF] = useState<string>(init.to);
  const [typeF, setTypeF] = useState<string>(init.type);
  const [campaignF, setCampaignF] = useState<string>(init.campaign);
  const [affF, setAffF] = useState<string>(init.aff);
  const [vipF, setVipF] = useState<string>(init.vip);

  const econPath = useMemo(() => {
    const qs = new URLSearchParams();
    if (fromF) qs.set("from", fromF);
    if (toF) qs.set("to", toF);
    if (typeF) qs.set("type", typeF);
    if (campaignF) qs.set("campaign", campaignF);
    if (affF) qs.set("aff", affF);
    if (vipF) qs.set("vip", vipF);
    const s = qs.toString();
    return `/api/v1/bonus/economics${s ? `?${s}` : ""}`;
  }, [fromF, toF, typeF, campaignF, affF, vipF]);

  // ── два независимых источника: экономика (фильтруется) и uplift/типы (как есть) ──
  const econ = useFlaskData<BonusEconomicsResponse>(econPath);
  const bonus = useFlaskData<BonusResponse>("/api/v1/bonus");

  const econLoading = econ.state === "loading";
  const kpi = econ.data?.kpi ?? null;
  const funnel = econ.data?.funnel ?? null;
  const abuse = econ.data?.abuse ?? null;
  const campaigns = econ.data?.filters.options.campaigns ?? [];
  const issuedItem = kpi?.find((k) => k.key === "issued");
  const econEmpty = econ.state === "data" && issuedItem != null && (issuedItem.value ?? 0) === 0;
  const hasFilters = !!(fromF || toF || typeF || campaignF || affF || vipF);

  const bonusLoading = bonus.state === "loading";
  const u = bonus.data?.uplift;

  function resetFilters() {
    setFromF("");
    setToF("");
    setTypeF("");
    setCampaignF("");
    setAffF("");
    setVipF("");
    urlSync({ from: "", to: "", type: "", campaign: "", aff: "", vip: "" });
  }

  /** ±pp with one decimal (board `+23.6 п.п.`). */
  function pp(v: number, digits = 1): string {
    return `${v >= 0 ? "+" : ""}${v.toFixed(digits)} ${t("marketing.bonus.ppSuffix")}`;
  }
  /** Signed one-decimal, no unit — for the CI bracket `[+2.3; -1.1]` (board :2329). */
  function sgn(v: number): string {
    return `${v >= 0 ? "+" : ""}${v.toFixed(1)}`;
  }

  const effCols: Column<EffRow>[] = [
    { key: "type", header: t("marketing.bonus.col.type"), align: "left", render: (r) => r.bonus_type },
    { key: "players", header: t("marketing.bonus.col.playersStar"), mono: true, render: (r) => formatInt(r.players) },
    { key: "events", header: t("marketing.bonus.col.events"), mono: true, render: (r) => formatInt(r.bonus_events) },
    {
      key: "dep",
      header: t("marketing.bonus.col.depAfter14d"),
      mono: true,
      render: (r) => (r.dep_resp_14d_pct != null ? formatPct(r.dep_resp_14d_pct) : "—"),
    },
    {
      key: "ret",
      header: t("marketing.bonus.col.retainedAfter30d"),
      mono: true,
      render: (r) => (r.retained_30d_pct != null ? formatPct(r.retained_30d_pct) : "—"),
    },
  ];

  const recCols: Column<RecRow>[] = [
    { key: "bonus", header: t("marketing.bonus.col.recBonus"), align: "left", render: (r) => r.rec_bonus },
    { key: "players", header: t("marketing.bonus.col.players"), mono: true, render: (r) => formatInt(r.players) },
    { key: "pct", header: t("marketing.bonus.col.pctScored"), mono: true, render: (r) => `${r.pct}%` },
  ];

  const ctl = "!w-auto !h-[36px] text-[12.5px]";

  return (
    <>
      {/* ── фильтры (управляют Бонус-экономикой; состояние в URL) ── */}
      <ChipBar className="mt-5">
        <Select
          value={typeF}
          aria-label={t("marketing.eco.filter.typeAll")}
          className={ctl}
          onChange={(e) => {
            setTypeF(e.target.value);
            urlSync({ type: e.target.value });
          }}
        >
          <option value="">{t("marketing.eco.filter.typeAll")}</option>
          {TYPE_KEYS.map((k) => (
            <option key={k} value={k}>
              {t(TYPE_LABEL[k])}
            </option>
          ))}
        </Select>
        <Select
          value={campaignF}
          aria-label={t("marketing.eco.filter.campaignAll")}
          className={`${ctl} max-w-[210px]`}
          onChange={(e) => {
            setCampaignF(e.target.value);
            urlSync({ campaign: e.target.value });
          }}
        >
          <option value="">{t("marketing.eco.filter.campaignAll")}</option>
          <option value="*">{t("marketing.eco.filter.campaignAny")}</option>
          {campaigns.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Select
          value={vipF}
          aria-label={t("marketing.eco.filter.vipAll")}
          className={ctl}
          onChange={(e) => {
            setVipF(e.target.value);
            urlSync({ vip: e.target.value });
          }}
        >
          <option value="">{t("marketing.eco.filter.vipAll")}</option>
          {VIP_LEVELS.map((v) => (
            <option key={v} value={String(v)}>
              {t("marketing.eco.vipLevel", { n: v })}
            </option>
          ))}
        </Select>
        <Input
          value={affF}
          placeholder={t("marketing.eco.filter.aff")}
          aria-label={t("marketing.eco.filter.aff")}
          className="!w-[150px] !h-[36px] text-[12.5px]"
          onChange={(e) => {
            const v = e.target.value.replace(/[^A-Za-z0-9_]/g, "");
            setAffF(v);
            urlSync({ aff: v });
          }}
        />
        <DateInput
          value={fromF}
          aria-label={t("marketing.eco.filter.from")}
          className={ctl}
          onChange={(e) => {
            setFromF(e.target.value);
            urlSync({ from: e.target.value });
          }}
        />
        <DateInput
          value={toF}
          aria-label={t("marketing.eco.filter.to")}
          className={ctl}
          onChange={(e) => {
            setToF(e.target.value);
            urlSync({ to: e.target.value });
          }}
        />
        {hasFilters ? <Chip onClick={resetFilters}>{t("marketing.eco.filter.reset")}</Chip> : null}
      </ChipBar>

      {/* ── (1) KPI P&L бонусов ── */}
      <Eyebrow>
        {t("marketing.eco.kpiEyebrow.main")}{" "}
        <span className="text-steel font-normal">{t("marketing.eco.kpiEyebrow.note")}</span>
      </Eyebrow>

      {econ.state === "error" ? (
        <Panel className="mt-2">
          <ErrorState description={econ.error ?? undefined} onRetry={econ.reload} />
        </Panel>
      ) : econEmpty ? (
        <Panel className="mt-2">
          <EmptyState title={t("marketing.eco.empty")} description={t("marketing.eco.emptyHint")} />
        </Panel>
      ) : (
        <>
          <div className="mt-2">
            <BonusEconomicsKpi items={kpi} loading={econLoading} />
          </div>

          {/* ── (2) воронка бонуса ── */}
          <div className="mt-6">
            <Eyebrow>
              {t("marketing.eco.funnelEyebrow.main")}{" "}
              <span className="text-steel font-normal">{t("marketing.eco.funnelEyebrow.note")}</span>
            </Eyebrow>
            <BonusFunnel stages={funnel} loading={econLoading} />
          </div>

          {/* ── (6) abuse-плашка со ссылкой в ленту флагов ── */}
          {abuse && abuse.personas > 0 ? (
            <Banner className="mt-4">
              🎁 <b>{t("marketing.eco.abuse.title")}</b>{" "}
              {t("marketing.eco.abuse.body", {
                n: formatInt(abuse.personas),
                pct: formatPct(abuse.share_pct),
              })}{" "}
              <Link href={abuse.href} className="text-primary underline">
                {t("marketing.eco.abuse.link")}
              </Link>
            </Banner>
          ) : null}
        </>
      )}

      {/* ── (3) существующий uplift-блок + (4) таблицы — КАК ЕСТЬ (/api/v1/bonus) ── */}
      {bonus.state === "error" ? (
        <Card className="mt-6">
          <div className="text-neg text-[13.5px]">{bonus.error}</div>
          <button onClick={bonus.reload} className="mt-2 text-primary text-[13px] underline">
            {t("common.retry")}
          </button>
        </Card>
      ) : (
        <>
          <div className="mt-8">
            <SCardGrid>
              <SCard
                loading={bonusLoading}
                variant="orange"
                icon="🎁"
                label={t("marketing.bonus.card.honest.label")}
                value={u ? pp(u.att_pp) : "—"}
                sub={u ? t("marketing.bonus.card.honest.sub", { lo: pp(u.ci_lo_pp), hi: pp(u.ci_hi_pp) }) : undefined}
              />
              <SCard
                loading={bonusLoading}
                icon="⚠️"
                label={t("marketing.bonus.card.raw.label")}
                value={u ? pp(u.raw_pp, 0) : "—"}
                sub={t("marketing.bonus.card.raw.sub")}
              />
              <SCard
                loading={bonusLoading}
                variant="cream"
                icon="📈"
                label={t("marketing.bonus.card.retained.label")}
                value={u ? `${Math.round(u.retain_treated_pct)}%` : "—"}
                sub={u ? t("marketing.bonus.card.retained.sub", { pct: Math.round(u.retain_control_pct) }) : undefined}
              />
              <SCard
                loading={bonusLoading}
                icon="⚖️"
                label={t("marketing.bonus.card.compare.label")}
                value={u ? `${formatInt(u.n_treated)} / ${formatInt(u.n_control)}` : "—"}
                sub={t("marketing.bonus.card.compare.sub")}
              />
            </SCardGrid>
          </div>

          {u ? (
            <Banner>
              🧠 <b>{t("marketing.bonus.banner.bold")}</b>{" "}
              {t("marketing.bonus.banner.body", { raw: pp(u.raw_pp, 0) })} <b>{pp(u.att_pp)}</b>.{" "}
              {/* вывод про CI: пересекает ли ноль (борд player_board.py:2329-2330) */}
              {u.ci_lo_pp <= 0 && u.ci_hi_pp >= 0
                ? t("marketing.bonus.banner.ciCrossesZero", { lo: sgn(u.ci_lo_pp), hi: sgn(u.ci_hi_pp) })
                : t("marketing.bonus.banner.ciSignificant", { lo: sgn(u.ci_lo_pp), hi: sgn(u.ci_hi_pp) })}
            </Banner>
          ) : null}

          <div className="mt-6">
            <Eyebrow>
              {t("marketing.bonus.effEyebrow.main")}{" "}
              <span className="text-steel font-normal">{t("marketing.bonus.effEyebrow.note")}</span>
            </Eyebrow>
            <Panel>
              <DataTable
                columns={effCols}
                rows={bonus.data?.effectiveness ?? []}
                getRowKey={(r) => r.bonus_type}
                state={bonusLoading ? "loading" : "data"}
              />
            </Panel>
            <div className="text-[13px] text-steel leading-relaxed mt-1.5">
              {t("marketing.bonus.effFootnote")}
            </div>
          </div>

          <div className="mt-6">
            <Eyebrow>
              {t("marketing.bonus.recEyebrow.main")}{" "}
              {/* реальное число оценённых игроков из API (rec_total), не хардкод */}
              <span className="text-steel font-normal">
                {t("marketing.bonus.recEyebrow.note", { n: formatInt(bonus.data?.rec_total) })}
              </span>
            </Eyebrow>
            <Panel>
              <DataTable
                columns={recCols}
                rows={bonus.data?.recommendations ?? []}
                getRowKey={(r) => r.rec_bonus}
                state={bonusLoading ? "loading" : "data"}
              />
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
