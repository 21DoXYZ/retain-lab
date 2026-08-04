"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import {
  PageHeader,
  SCard,
  Pill,
  PillRow,
  ErrorState,
  Skeleton,
  Tabs,
  Select,
  Input,
  Button,
  type TabItem,
} from "@/components/ui";
import { formatInt, formatMoneyMn } from "@/lib/format";
import { useResource, DeltaBadge } from "@/components/money/kit";
import { IncomeLegend } from "@/components/money/IncomeLegend";
import type {
  GgrData,
  GgrDashboardTab,
  GgrProviderRow,
  GgrRatesRow,
  GgrSegmentsTab,
  GgrBonusTab,
  GgrSettleTab,
  GgrReportsTab,
} from "@/components/money/types";
import {
  GgrDashboard,
  GgrProviderGame,
  GgrRates,
  GgrSegments,
  GgrBonus,
  GgrSettle,
  GgrReports,
} from "@/components/money/GgrTabs";
import { useT, type MessageKey } from "@/lib/i18n";

/**
 * /ggr — «GGR и доход» (agent F1, paritet с ggr_page() борда :8050). 8 табов
 * (dashboard/provider/game/segments/bonus/rates/settle/reports) + фильтр-панель
 * (дата/провайдер/страна/аффилиат/лимит) + два ряда KPI-карточек с дельтами к
 * прошлому равному периоду. Данные из /api/v1/ggr (api/money.py) через flaskFetch.
 * Роли (server-guard): MONEY_ROLES.
 */

const mn = formatMoneyMn;
const f = formatInt;

interface Draft {
  from: string;
  to: string;
  provider: string;
  country: string;
  aff: string;
  limit: number;
}

const EMPTY: Draft = { from: "", to: "", provider: "", country: "", aff: "", limit: 25 };

/** Fallback tab labels before the server-resolved `d.tabs` arrive. */
function staticTabs(t: (key: MessageKey) => string): TabItem[] {
  return [
    { key: "dashboard", label: t("money.ggr.tab.dashboard") },
    { key: "provider", label: t("money.ggr.tab.provider") },
    { key: "game", label: t("money.ggr.tab.game") },
    { key: "segments", label: t("money.ggr.tab.segments") },
    { key: "bonus", label: t("money.ggr.tab.bonus") },
    { key: "rates", label: t("money.ggr.tab.rates") },
    { key: "settle", label: t("money.ggr.tab.settle") },
    { key: "reports", label: t("money.ggr.tab.reports") },
  ];
}

function buildPath(a: Draft, tab: string): string {
  const p = new URLSearchParams();
  p.set("tab", tab);
  if (a.from) p.set("from", a.from);
  if (a.to) p.set("to", a.to);
  if (a.provider) p.set("provider", a.provider);
  if (a.country) p.set("country", a.country);
  if (a.aff) p.set("aff", a.aff);
  p.set("limit", String(a.limit));
  return `/api/v1/ggr?${p.toString()}`;
}

/** Select options with the current value guaranteed present. */
function withCurrent(options: string[], current: string): string[] {
  return current && !options.includes(current) ? [current, ...options] : options;
}

// ── Диплинк /ggr#bonus (nav «ggr-bonus») открывает бонус-вкладку. Hash — только
// клиентский, поэтому читаем его ТОЛЬКО после гидратации (SSR-HTML без hash не
// должен разойтись с первым клиентским рендером). useSyncExternalStore даёт
// гидрат-флаг без setState-в-effect (react-hooks strict, паттерн DeskScreen). ──
const emptySubscribe = () => () => {};
/** true только после гидратации (SSR/первый клиентский рендер — false). */
const useHydrated = () => useSyncExternalStore(emptySubscribe, () => true, () => false);

/** Стартовая вкладка из hash: '#bonus' → 'bonus', иначе 'dashboard' (SSR-безопасно). */
function hashTab(): string {
  if (typeof window === "undefined") return "dashboard";
  return window.location.hash === "#bonus" ? "bonus" : "dashboard";
}

export function GgrScreen() {
  const t = useT();
  // Вкладка: override — явный выбор пользователя; иначе — стартовая из hash после
  // гидратации (диплинк /ggr#bonus), до гидратации — дефолтная 'dashboard'.
  const hydrated = useHydrated();
  const [tabOverride, setTabOverride] = useState<string | undefined>(undefined);
  const tab = tabOverride !== undefined ? tabOverride : hydrated ? hashTab() : "dashboard";
  const setTab = setTabOverride;
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [applied, setApplied] = useState<Draft>(EMPTY);
  const syncedRef = useRef(false);

  const path = useMemo(() => buildPath(applied, tab), [applied, tab]);
  const { state, data, error, reload } = useResource<GgrData>(path);

  // Adopt the server-resolved default window into the date inputs once.
  useEffect(() => {
    if (data && !syncedRef.current) {
      syncedRef.current = true;
      setDraft((d) => (d.from || d.to ? d : { ...d, from: data.filters.from, to: data.filters.to }));
    }
  }, [data]);

  const d = data;
  const kpiLoading = !d;
  const bodyLoading = state === "loading";

  function onApply(e: FormEvent) {
    e.preventDefault();
    setApplied({ ...draft });
  }
  function onReset() {
    syncedRef.current = false;
    setDraft(EMPTY);
    setApplied(EMPTY);
  }

  const provOptions = withCurrent(d?.provider_options ?? [], draft.provider);
  const countryOptions = withCurrent(d?.country_options ?? [], draft.country);
  // Названия табов — по КОДУ через словарь: API отдаёт label по-русски
  // (player_board.GGR_TABS), в нерусском UI он не годится. Серверный label —
  // только фолбэк для таба, которого словарь ещё не знает.
  const known = new Set(staticTabs(t).map((x) => x.key));
  const tabs: TabItem[] =
    d?.tabs.map((x) => ({
      key: x.key,
      label: known.has(x.key) ? t(`money.ggr.tab.${x.key}` as MessageKey) : x.label,
    })) ?? staticTabs(t);

  return (
    <>
      <PageHeader
        title={t("money.ggr.title")}
        accent={t("money.ggr.accent")}
        lead={t("money.ggr.lead")}
        right={
          <PillRow>
            <Pill live>{d ? `${d.filters.from} → ${d.filters.to}` : t("money.ggr.pillPeriodPlaceholder")}</Pill>
            <Pill>{d?.filters.provider || t("money.ggr.pillAllProviders")}</Pill>
          </PillRow>
        }
      />

      {state === "error" && !d ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          {/* ── KPI ряд 1 ── */}
          <div className="mt-6 grid gap-4 grid-cols-2 lg:grid-cols-5">
            <SCard
              loading={kpiLoading}
              icon="🎲"
              label={t("money.ggr.kpi.bet.label")}
              value={mn(d?.kpi.bet)}
              sub={
                <>
                  {t("money.ggr.kpi.bet.sub", { rounds: f(d?.kpi.rounds) })} <DeltaBadge delta={d?.deltas.bet} />
                </>
              }
            />
            <SCard
              loading={kpiLoading}
              icon="🏆"
              label={t("money.ggr.kpi.win.label")}
              value={mn(d?.kpi.win)}
              sub={
                <>
                  {t("money.ggr.kpi.win.sub")} <DeltaBadge delta={d?.deltas.win} />
                </>
              }
            />
            <SCard
              loading={kpiLoading}
              variant="orange"
              icon="🎯"
              label={t("money.ggr.kpi.ggr.label")}
              value={mn(d?.kpi.ggr)}
              sub={
                <>
                  {t("money.ggr.kpi.ggr.sub")} <DeltaBadge delta={d?.deltas.ggr} />
                </>
              }
            />
            <SCard
              loading={kpiLoading}
              icon="📊"
              label={t("money.ggr.kpi.rtp.label")}
              value={`${d?.kpi.rtp ?? 0}%`}
              sub={
                <>
                  {t("money.ggr.kpi.rtp.sub")} <DeltaBadge delta={d?.deltas.rtp} />
                </>
              }
            />
            <SCard
              loading={kpiLoading}
              variant={d && d.kpi.ngr < 0 ? "alert" : "cream"}
              icon="💠"
              label={t("money.ggr.kpi.ngr.label")}
              value={mn(d?.kpi.ngr)}
              sub={
                <>
                  {t("money.ggr.kpi.ngr.sub")} <DeltaBadge delta={d?.deltas.ngr} />
                </>
              }
            />
          </div>

          {/* ── KPI ряд 2 — расходы (board kc2 :730-737) ── */}
          <div className="mt-4 grid gap-4 grid-cols-2 lg:grid-cols-5">
            <SCard
              loading={kpiLoading}
              icon="🎁"
              label={t("money.ggr.kpi.bonus.label")}
              value={mn(d?.kpi.bonus)}
              sub={
                <>
                  {t("money.ggr.kpi.bonus.sub", { pct: d?.kpi.bratio ?? 0 })} <DeltaBadge delta={d?.deltas.bonus} />
                </>
              }
            />
            <SCard
              loading={kpiLoading}
              icon="🏭"
              label={t("money.ggr.kpi.pcost.label")}
              value={mn(d?.kpi.pcost)}
              sub={
                <>
                  {t("money.ggr.kpi.pcost.sub")} <DeltaBadge delta={d?.deltas.pcost} />
                </>
              }
            />
            <SCard
              loading={kpiLoading}
              icon="🤝"
              label={t("money.ggr.kpi.affc.label")}
              value={mn(d?.kpi.affc)}
              sub={
                <>
                  {t("money.ggr.kpi.affc.sub")} <DeltaBadge delta={d?.deltas.affc} />
                </>
              }
            />
            <SCard
              loading={kpiLoading}
              icon="🟢"
              label={t("money.ggr.kpi.active.label")}
              value={f(d?.kpi.active)}
              sub={
                <>
                  {t("money.ggr.kpi.active.sub")} <DeltaBadge delta={d?.deltas.active} />
                </>
              }
            />
            <SCard
              loading={kpiLoading}
              icon="🎫"
              label={t("money.ggr.kpi.avgBet.label")}
              value={`₺${d?.kpi.avg_bet ?? 0}`}
              sub={
                <>
                  {t("money.ggr.kpi.avgBet.sub")} <DeltaBadge delta={d?.deltas.avg_bet} />
                </>
              }
            />
          </div>

          {/* Дисклеймер «три разных дохода» — здесь GGR, NGR и Net Profit стоят
              рядом и их путают (ТЗ по копирайту, задача 6.1). */}
          <div className="mt-4">
            <IncomeLegend />
          </div>

          {/* ── Фильтр-панель ── */}
          <form
            onSubmit={onApply}
            className="my-4 flex flex-wrap items-end gap-3 rounded-card border border-hair bg-canvas px-4 py-3.5"
          >
            <label className="flex flex-col gap-1 text-[11px] uppercase tracking-[0.5px] text-steel">
              {t("money.ggr.filter.date")}
              <span className="flex items-center gap-1.5">
                <Input
                  type="date"
                  value={draft.from}
                  onChange={(e) => setDraft({ ...draft, from: e.target.value })}
                  className="w-[150px]"
                />
                <span className="text-steel">—</span>
                <Input
                  type="date"
                  value={draft.to}
                  onChange={(e) => setDraft({ ...draft, to: e.target.value })}
                  className="w-[150px]"
                />
              </span>
            </label>
            <label className="flex flex-col gap-1 text-[11px] uppercase tracking-[0.5px] text-steel">
              {t("money.ggr.filter.provider")}
              <Select
                value={draft.provider}
                onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
                className="w-[170px]"
              >
                <option value="">{t("money.ggr.filter.providerAll")}</option>
                {provOptions.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-[11px] uppercase tracking-[0.5px] text-steel">
              {t("money.ggr.filter.country")}
              <Select
                value={draft.country}
                onChange={(e) => setDraft({ ...draft, country: e.target.value })}
                className="w-[120px]"
              >
                <option value="">{t("money.ggr.filter.countryAll")}</option>
                {countryOptions.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-[11px] uppercase tracking-[0.5px] text-steel">
              {t("money.ggr.filter.affiliate")}
              <Input
                value={draft.aff}
                placeholder={t("money.ggr.filter.affiliatePlaceholder")}
                onChange={(e) => setDraft({ ...draft, aff: e.target.value })}
                className="w-[120px]"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] uppercase tracking-[0.5px] text-steel">
              {t("money.ggr.filter.limit")}
              <Select
                value={String(draft.limit)}
                onChange={(e) => setDraft({ ...draft, limit: Number(e.target.value) })}
                className="w-[100px]"
              >
                {[25, 50, 100, 200].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </Select>
            </label>
            <Button type="submit">{t("money.ggr.filter.apply")}</Button>
            <Button type="button" variant="ghost" onClick={onReset}>
              {t("money.ggr.filter.reset")}
            </Button>
          </form>

          {/* ── Табы ── */}
          <Tabs tabs={tabs} value={tab} onChange={setTab} className="mb-1" />

          {/* ── Тело таба ── */}
          <div className="mt-4">
            {!d ? <BodySkeleton /> : renderTab(d, bodyLoading)}
          </div>
        </>
      )}
    </>
  );
}

function BodySkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function renderTab(d: GgrData, loading: boolean) {
  const t = d.filters.tab;
  const td = d.tab_data;
  switch (t) {
    case "dashboard":
      return <GgrDashboard tab={td as GgrDashboardTab} />;
    case "provider":
      return <GgrProviderGame kind="provider" rows={(td as { rows: GgrProviderRow[] }).rows} loading={loading} />;
    case "game":
      return <GgrProviderGame kind="game" rows={(td as { rows: GgrProviderRow[] }).rows} loading={loading} />;
    case "rates":
      return <GgrRates rows={(td as { rows: GgrRatesRow[] }).rows} loading={loading} />;
    case "segments":
      return <GgrSegments tab={td as GgrSegmentsTab} loading={loading} />;
    case "bonus":
      return <GgrBonus tab={td as GgrBonusTab} loading={loading} />;
    case "settle":
      return <GgrSettle tab={td as GgrSettleTab} loading={loading} />;
    case "reports":
      return <GgrReports tab={td as GgrReportsTab} />;
    default:
      return null;
  }
}
