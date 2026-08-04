"use client";

import { useMemo, useState, useSyncExternalStore, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  PageHeader,
  ModuleHeader,
  SCard,
  SCardGrid,
  Chip,
  ChipBar,
  DataTable,
  Pill,
  PillRow,
  ErrorState,
  Banner,
  Input,
  Button,
  DateInput,
  Tabs,
  type Column,
  type TabItem,
} from "@/components/ui";
import { formatInt, formatMoney, formatDate } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { useResource } from "./data";
import { VERDICT } from "./verdict";
import type { AffiliateRow, AffiliatesListData, AffiliateSortKey } from "./types";

/**
 * /affiliates — internal traffic overview (C5). One row per source with quality
 * (players/FTD), cash (Net Profit), game margin (GGR/NGR/hold) and commission
 * (by THIS affiliate's rate). Numbers 1:1 with the board affiliates() route.
 * Row click → the full reconciliation card at /affiliates/<code>.
 */

interface SortState {
  key: AffiliateSortKey;
  dir: "asc" | "desc";
}

/** Money cell tinted like the board (pos green / neg red). */
const TONED = (v: number) => (
  <span className={v < 0 ? "text-neg" : "text-pos"}>{formatMoney(v)}</span>
);

/** Горячий фильтр списка: null — все; ключи совпадают с флагами строки/вердиктом. */
type HotFilter = null | "risk" | "players_win" | "cash_drain";

/** Экран разделён на «Качество» (дефолт) и «Риск» (горячие плитки/чипы + фильтр). */
type AffTab = "quality" | "risk";

// ── Активная вкладка в URL (?tab=risk) — читаем ТОЛЬКО после гидратации, иначе
// SSR-HTML (без tab) и первый клиентский рендер разошлись бы. useSyncExternalStore
// даёт гидрат-флаг без setState-в-effect (react-hooks strict, паттерн DeskScreen). ─
const emptySubscribe = () => () => {};
/** true только после гидратации (SSR/первый клиентский рендер — false). */
const useHydrated = () => useSyncExternalStore(emptySubscribe, () => true, () => false);

/** Вкладка из URL — whitelist только 'risk', прочее → 'quality' (SSR-безопасно). */
function urlTab(): AffTab {
  if (typeof window === "undefined") return "quality";
  return new URLSearchParams(window.location.search).get("tab") === "risk" ? "risk" : "quality";
}

/** Записать вкладку в URL без перезагрузки (board history.replaceState). */
function writeTabToUrl(tab: AffTab): void {
  if (typeof window === "undefined") return;
  const qs = new URLSearchParams(window.location.search);
  if (tab === "risk") qs.set("tab", "risk");
  else qs.delete("tab");
  const s = qs.toString();
  window.history.replaceState(null, "", s ? `${window.location.pathname}?${s}` : window.location.pathname);
}

export function AffiliatesScreen() {
  const t = useT();
  const router = useRouter();
  // окно дат (как на /overview): applied — в запросе, draft — в инпутах
  const [applied, setApplied] = useState<{ from: string; to: string }>({ from: "", to: "" });
  const [draft, setDraft] = useState<{ from: string; to: string }>({ from: "", to: "" });
  const path = useMemo(() => {
    const qs = new URLSearchParams();
    if (applied.from) qs.set("from", applied.from);
    if (applied.to) qs.set("to", applied.to);
    const q = qs.toString();
    return `/api/v1/affiliates${q ? `?${q}` : ""}`;
  }, [applied]);
  const { state, data, error, reload } = useResource<AffiliatesListData>(path);
  const [sort, setSort] = useState<SortState>({ key: "players", dir: "desc" });
  const [flt, setFlt] = useState<HotFilter>(null);
  const [query, setQuery] = useState("");

  // Активная вкладка: override — явный выбор пользователя; иначе следуем URL
  // (после гидратации). Дефолт — «Качество».
  const hydrated = useHydrated();
  const [tabOverride, setTabOverride] = useState<AffTab | undefined>(undefined);
  const tab: AffTab = tabOverride !== undefined ? tabOverride : hydrated ? urlTab() : "quality";
  const setTab = (k: AffTab) => {
    writeTabToUrl(k);
    setTabOverride(k);
  };
  // Риск-фильтр применяется к таблице ТОЛЬКО на вкладке «Риск»; на «Качестве»
  // таблица всегда без фильтра (логика фильтра не меняется — лишь область).
  const effectiveFlt: HotFilter = tab === "risk" ? flt : null;

  // пока пользователь не трогал инпуты — показываем границы данных (без эффекта)
  const draftFrom = draft.from || data?.window?.dmin || "";
  const draftTo = draft.to || data?.window?.dmax || "";

  function applyPeriod(e: FormEvent) {
    e.preventDefault();
    setApplied({ from: draftFrom, to: draftTo });
  }

  function resetPeriod() {
    setApplied({ from: "", to: "" });
    setDraft({ from: "", to: "" });
  }

  const toggleFlt = (v: Exclude<HotFilter, null>) => setFlt((cur) => (cur === v ? null : v));

  function openAffiliate(e: FormEvent) {
    e.preventDefault();
    const code = query.trim();
    if (code) router.push(`/affiliates/${encodeURIComponent(code)}`);
  }

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    const filtered =
      effectiveFlt === "risk" ? all.filter((r) => r.players_win || r.cash_drain)
      : effectiveFlt === "players_win" ? all.filter((r) => r.players_win)
      : effectiveFlt === "cash_drain" ? all.filter((r) => r.cash_drain)
      : all;
    const sorted = [...filtered].sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const cmp = av === bv ? 0 : av < bv ? -1 : 1;
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [data, sort, effectiveFlt]);

  function toggleSort(key: AffiliateSortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "desc" ? "asc" : "desc" }
        : { key, dir: "desc" },
    );
  }

  // Заголовок сортируемой колонки — рендер-функция (НЕ компонент): closure над
  // sort/toggleSort, вызывается как функция → без react-hooks/static-components.
  const sortHead = (labelKey: MessageKey, sortKey: AffiliateSortKey, titleKey: MessageKey) => {
    const on = sort.key === sortKey;
    const arrow = on ? (sort.dir === "desc" ? " ▾" : " ▴") : "";
    return (
      <button
        type="button"
        title={t(titleKey)}
        onClick={() => toggleSort(sortKey)}
        className={`uppercase tracking-[0.5px] transition-colors hover:text-primary ${on ? "text-primary" : ""}`}
      >
        {t(labelKey)}
        {arrow}
      </button>
    );
  };

  const totals = data?.totals;

  const tabs: TabItem[] = [
    { key: "quality", label: t("monitor.affiliates.tab.quality") },
    { key: "risk", label: t("monitor.affiliates.tab.risk") },
  ];

  const columns: Column<AffiliateRow>[] = [
    {
      key: "code",
      header: t("monitor.affiliates.col.code"),
      align: "left",
      id: true,
      render: (r) => {
        const v = VERDICT[r.status];
        return (
          <span className="inline-flex items-center gap-1.5">
            {r.code}
            <span title={t(v.titleKey)} className="cursor-help text-[11px]">
              {v.emoji}
            </span>
          </span>
        );
      },
    },
    { key: "players", header: sortHead("monitor.affiliates.col.players", "players", "monitor.affiliates.col.playersTitle"), mono: true, render: (r) => formatInt(r.players) },
    { key: "ftd", header: sortHead("monitor.affiliates.col.ftd", "ftd", "monitor.affiliates.col.ftdTitle"), mono: true, render: (r) => formatInt(r.ftd) },
    { key: "ftd_sum", header: sortHead("monitor.affiliates.col.ftdSum", "ftd_sum", "monitor.affiliates.col.ftdSumTitle"), mono: true, render: (r) => formatMoney(r.ftd_sum) },
    { key: "dep", header: sortHead("monitor.affiliates.col.dep", "dep", "monitor.affiliates.col.depTitle"), mono: true, render: (r) => formatMoney(r.dep) },
    { key: "wd", header: sortHead("monitor.affiliates.col.wd", "wd", "monitor.affiliates.col.wdTitle"), mono: true, render: (r) => formatMoney(r.wd) },
    { key: "net_profit", header: sortHead("monitor.affiliates.col.netProfit", "net_profit", "monitor.affiliates.col.netProfitTitle"), mono: true, render: (r) => TONED(r.net_profit) },
    { key: "turn", header: sortHead("monitor.affiliates.col.turn", "turn", "monitor.affiliates.col.turnTitle"), mono: true, render: (r) => formatMoney(r.turn) },
    { key: "ggr", header: sortHead("monitor.affiliates.col.ggr", "ggr", "monitor.affiliates.col.ggrTitle"), mono: true, render: (r) => formatMoney(r.ggr) },
    { key: "ggr_real", header: sortHead("monitor.affiliates.col.ggrReal", "ggr_real", "monitor.affiliates.col.ggrRealTitle"), mono: true, render: (r) => formatMoney(r.ggr_real) },
    { key: "ngr", header: sortHead("monitor.affiliates.col.ngr", "ngr", "monitor.affiliates.col.ngrTitle"), mono: true, render: (r) => TONED(r.ngr) },
    { key: "commission", header: sortHead("monitor.affiliates.col.commission", "commission", "monitor.affiliates.col.commissionTitle"), mono: true, render: (r) => (
      <span title={t("monitor.affiliates.col.commissionCellTitle", { rate: r.rate })}>{formatMoney(r.commission)}</span>
    ) },
    { key: "hold", header: sortHead("monitor.affiliates.col.hold", "hold", "monitor.affiliates.col.holdTitle"), mono: true, render: (r) => `${r.hold}%` },
  ];

  return (
    <>
      <PageHeader
        title={t("monitor.affiliates.title")}
        accent={totals ? `· ${formatInt(totals.affiliates)}` : undefined}
        lead={t("monitor.affiliates.lead")}
        right={
          <PillRow>
            {data?.window?.filtered ? (
              <Pill>{t("monitor.affiliates.period.pill", { from: data.window.from, to: data.window.to })}</Pill>
            ) : data?.asof ? (
              <Pill>{t("monitor.pill.asOf", { date: formatDate(data.asof) })}</Pill>
            ) : null}
            <Pill live>{t("monitor.pill.live")}</Pill>
          </PillRow>
        }
      />

      <ModuleHeader module="traffic" />

      {state === "error" ? (
        <div className="mt-6">
          <ErrorState description={error ?? undefined} onRetry={reload} />
        </div>
      ) : (
        <>
          <div className="mt-[18px]">
            <Tabs tabs={tabs} value={tab} onChange={(k) => setTab(k as AffTab)} />
          </div>

          {tab === "quality" ? (
            <>
              {/* KPI аффилиатов/игроков — без риск-плиток */}
              <div className="mt-[18px]">
                <SCardGrid>
                  <SCard icon="🤝" label={t("monitor.affiliates.kpi.count.label")} value={totals ? formatInt(totals.affiliates) : "—"} sub={totals ? t("monitor.affiliates.kpi.count.sub", { n: formatInt(totals.risk) }) : undefined} loading={state === "loading"} />
                  <SCard variant="cream" icon="👥" label={t("monitor.affiliates.kpi.players.label")} value={totals ? formatInt(totals.players) : "—"} sub={totals ? t("monitor.affiliates.kpi.players.sub", { n: formatInt(totals.ftd) }) : undefined} loading={state === "loading"} />
                </SCardGrid>
              </div>

              {/* период (как дейтпикер Обзора): по умолчанию вся история до среза данных */}
              <form onSubmit={applyPeriod} className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-[12.5px] text-steel">{t("monitor.affiliates.period.label")}</span>
                <DateInput className="!w-auto" value={draftFrom} min={data?.window?.dmin} max={data?.window?.dmax}
                           onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))} />
                <span className="text-steel">—</span>
                <DateInput className="!w-auto" value={draftTo} min={data?.window?.dmin} max={data?.window?.dmax}
                           onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))} />
                <Button type="submit" size="sm" variant="brand">{t("monitor.affiliates.period.apply")}</Button>
                {data?.window?.filtered ? (
                  <Chip onClick={resetPeriod}>{t("monitor.affiliates.period.reset")}</Chip>
                ) : null}
              </form>

              <Banner>
                <b>{t("monitor.affiliates.banner.howToReadLabel")}</b> <b>{t("monitor.affiliates.col.ftdSum")}</b> {t("monitor.affiliates.banner.ftdText")}{" "}
                <b>{t("monitor.affiliates.col.netProfit")}</b> {t("monitor.affiliates.banner.netProfitText")}{" "}
                <b>{t("monitor.affiliates.col.ggr")}</b> {t("monitor.affiliates.banner.ggrText")} <b>{t("monitor.affiliates.col.ggrReal")}</b> {t("monitor.affiliates.banner.ggrRealText")}{" "}
                <b>{t("monitor.affiliates.col.ngr")}</b> {t("monitor.affiliates.banner.ngrText")}{" "}
                <b>{t("monitor.affiliates.col.commission")}</b> {t("monitor.affiliates.banner.commissionText")} <b>{t("monitor.affiliates.banner.holdLabel")}</b>{" "}
                {t("monitor.affiliates.banner.holdText")}
                <br />
                <b>{t("monitor.affiliates.banner.statusLabel")}</b> {VERDICT.loss.emoji} {t("monitor.affiliates.banner.statusLoss")} · {VERDICT.risk.emoji} {t("monitor.affiliates.banner.statusRisk")} · {VERDICT.cash_drain.emoji} {t("monitor.affiliates.banner.statusCashDrain")} ·{" "}
                {VERDICT.profit.emoji} {t("monitor.affiliates.banner.statusProfit")}.
                {data?.asof ? (
                  <>
                    <br />
                    {t("monitor.affiliates.banner.asofHint", { asof: formatDate(data.asof) })}
                  </>
                ) : null}
              </Banner>

              {/* Поиск по коду аффилиата + datalist всех кодов (борд :2763-2766) */}
              <form onSubmit={openAffiliate} className="mt-3 flex flex-wrap items-center gap-2">
                <Input
                  list="afflist"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("monitor.affiliates.search.placeholder")}
                  aria-label={t("monitor.affiliates.search.aria")}
                  className="max-w-[280px]"
                />
                <datalist id="afflist">
                  {(data?.rows ?? []).map((r) => (
                    <option key={r.code} value={r.code} />
                  ))}
                </datalist>
                <Button type="submit" variant="brand" disabled={!query.trim()}>
                  {t("monitor.affiliates.search.open")}
                </Button>
              </form>
            </>
          ) : (
            <>
              {/* горячие риск-плитки: клик = фильтр списка (запрос владельца) */}
              <div className="mt-[18px]">
                <SCardGrid>
                  <button type="button" className="text-left cursor-pointer" onClick={() => toggleFlt("players_win")}
                          title={t("monitor.affiliates.kpi.hotHint")}>
                    <SCard variant="alert" icon="🔴" label={t("monitor.affiliates.kpi.playersWin.label")} value={totals ? formatInt(totals.players_win) : "—"} sub={flt === "players_win" ? t("monitor.affiliates.kpi.hotActive") : t("monitor.affiliates.kpi.playersWin.sub")} loading={state === "loading"} className={flt === "players_win" ? "ring-2 ring-primary" : undefined} />
                  </button>
                  <button type="button" className="text-left cursor-pointer" onClick={() => toggleFlt("cash_drain")}
                          title={t("monitor.affiliates.kpi.hotHint")}>
                    <SCard variant="orange" icon="💸" label={t("monitor.affiliates.kpi.cashDrain.label")} value={totals ? formatInt(totals.cash_drain) : "—"} sub={flt === "cash_drain" ? t("monitor.affiliates.kpi.hotActive") : t("monitor.affiliates.kpi.cashDrain.sub")} loading={state === "loading"} className={flt === "cash_drain" ? "ring-2 ring-primary" : undefined} />
                  </button>
                </SCardGrid>
              </div>

              <ChipBar>
                <Chip active={flt === "risk"} onClick={() => toggleFlt("risk")}>
                  {t("monitor.affiliates.chip.riskOnly", { count: totals ? ` (${formatInt(totals.risk)})` : "" })}
                </Chip>
                <Chip active={flt === "players_win"} onClick={() => toggleFlt("players_win")}>
                  🔴 {t("monitor.affiliates.kpi.playersWin.label")}{totals ? ` (${formatInt(totals.players_win)})` : ""}
                </Chip>
                <Chip active={flt === "cash_drain"} onClick={() => toggleFlt("cash_drain")}>
                  💸 {t("monitor.affiliates.kpi.cashDrain.label")}{totals ? ` (${formatInt(totals.cash_drain)})` : ""}
                </Chip>
                <span className="text-[12.5px] text-steel">
                  {t("monitor.affiliates.chip.riskLegend")}
                </span>
              </ChipBar>
            </>
          )}

          <div className="mt-3 overflow-hidden rounded-card border border-hair bg-canvas">
            <DataTable
              columns={columns}
              rows={rows}
              state={state === "loading" ? "loading" : rows.length === 0 ? "empty" : "data"}
              getRowKey={(r) => r.code}
              getRowHref={(r) => `/affiliates/${encodeURIComponent(r.code)}`}
              emptyTitle={t("monitor.affiliates.empty.title")}
              emptyDescription={effectiveFlt ? t("monitor.affiliates.empty.riskDesc") : t("monitor.affiliates.empty.desc")}
            />
          </div>
        </>
      )}
    </>
  );
}
