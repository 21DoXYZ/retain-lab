"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import {
  PageHeader,
  ModuleHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Panel,
  Chip,
  ChipBar,
  Pill,
  PillRow,
  DataTable,
  LifecycleBadge,
  ActionBadge,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { useResource, pctRatio, tryAmount, OfferCell, Note } from "./kit";
import { AssignButton } from "./AssignButton";
import type { DeskData, DeskRow, FilterOption } from "./types";

/**
 * /desk — «Пульт (очередь)» ретеншн-отдела (paritet с desk() борда). Рабочая
 * очередь по задаче (act) и окну импульса (w); тот же SQL/приоритеты/офферы, что
 * в HTML. Данные из /api/v1/desk?act=&w=. Роли: DESK_ROLES.
 */

/** Ключ фильтра из API → ключ словаря (подписи API русские, см. localize ниже). */
const ACT_KEYS: Record<string, MessageKey> = {
  SAVE: "monitor.desk.filter.act.save",
  WINBACK: "monitor.desk.filter.act.winback",
  NUDGE: "monitor.desk.filter.act.nudge",
  CONVERT: "monitor.desk.filter.act.convert",
  NURTURE: "monitor.desk.filter.act.nurture",
  all: "monitor.desk.filter.act.all",
};

const W_KEYS: Record<string, MessageKey> = {
  "7": "monitor.desk.filter.w.7",
  "14": "monitor.desk.filter.w.14",
  "30": "monitor.desk.filter.w.30",
  "90": "monitor.desk.filter.w.90",
  all: "monitor.desk.filter.w.all",
};

// ── VIP-пресет очереди (nav «vip-queue» → /desk?act=SAVE&tier=cd) ─────────────
// URL читаем ТОЛЬКО после гидратации, иначе SSR-HTML (без tier) и первый
// клиентский рендер разойдутся. useSyncExternalStore — гидрат-флаг без
// setState-в-effect (react-hooks strict, см. BonusSection).
const emptySubscribe = () => () => {};
/** true только после гидратации (SSR/первый клиентский рендер — false). */
const useHydrated = () => useSyncExternalStore(emptySubscribe, () => true, () => false);

/** tier из URL — whitelist только 'cd', прочее игнорируем (SSR-безопасно). */
function urlTier(): "cd" | "" {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("tier") === "cd" ? "cd" : "";
}

/** Снять пресет: убрать tier из URL без перезагрузки (board history.replaceState). */
function dropTierFromUrl(): void {
  if (typeof window === "undefined") return;
  const qs = new URLSearchParams(window.location.search);
  qs.delete("tier");
  const s = qs.toString();
  window.history.replaceState(null, "", s ? `${window.location.pathname}?${s}` : window.location.pathname);
}

export function DeskScreen() {
  const t = useT();
  const [act, setAct] = useState("SAVE");
  const [w, setW] = useState("14");

  // Пресет активен, пока URL несёт tier=cd и оператор его не снял (tierCleared).
  const hydrated = useHydrated();
  const [tierCleared, setTierCleared] = useState(false);
  const tier: "cd" | "" = hydrated && !tierCleared ? urlTier() : "";

  const clearTier = () => {
    dropTierFromUrl();
    setTierCleared(true);
  };

  // Fallback filter chips so the bar renders before the first response arrives.
  const ACT_FALLBACK: FilterOption[] = [
    { key: "SAVE", label: t("monitor.desk.filter.act.save") },
    { key: "WINBACK", label: t("monitor.desk.filter.act.winback") },
    { key: "NUDGE", label: t("monitor.desk.filter.act.nudge") },
    { key: "CONVERT", label: t("monitor.desk.filter.act.convert") },
    { key: "NURTURE", label: t("monitor.desk.filter.act.nurture") },
    { key: "all", label: t("monitor.desk.filter.act.all") },
  ];
  const W_FALLBACK: FilterOption[] = [
    { key: "7", label: t("monitor.desk.filter.w.7") },
    { key: "14", label: t("monitor.desk.filter.w.14") },
    { key: "30", label: t("monitor.desk.filter.w.30") },
    { key: "90", label: t("monitor.desk.filter.w.90") },
    { key: "all", label: t("monitor.desk.filter.w.all") },
  ];

  const path = useMemo(
    () =>
      `/api/v1/desk?act=${encodeURIComponent(act)}&w=${encodeURIComponent(w)}` +
      (tier ? `&tier=${tier}` : ""),
    [act, w, tier],
  );
  const { state, data, error, reload } = useResource<DeskData>(path);
  const loading = state === "loading";
  const d = data;

  // API отдаёт подписи фильтров ПО-РУССКИ (player_board.ACT_FILTERS — UI-копия,
  // протёкшая в бэкенд). Ключ (SAVE/all/7/…) универсален, поэтому подпись всегда
  // берём из словаря по ключу, а label из ответа — лишь фолбэк для незнакомых.
  const localize = (opts: FilterOption[], keys: Record<string, MessageKey>): FilterOption[] =>
    opts.map((o) => (keys[o.key] ? { ...o, label: t(keys[o.key]) } : o));

  const actOpts = localize(d?.filters.act ?? ACT_FALLBACK, ACT_KEYS);
  const wOpts = localize(d?.filters.w ?? W_FALLBACK, W_KEYS);

  const cols: Column<DeskRow>[] = [
    { key: "player", header: t("monitor.desk.col.player"), id: true, render: (r) => r.player_id },
    { key: "stage", header: t("monitor.desk.col.stage"), align: "left", render: (r) => <LifecycleBadge stage={r.lifecycle} /> },
    { key: "action", header: t("monitor.desk.col.action"), align: "left", render: (r) => <ActionBadge action={r.action} /> },
    { key: "value", header: t("monitor.desk.col.value"), mono: true, render: (r) => tryAmount(r.value_try) },
    {
      key: "risk",
      header: t("monitor.desk.col.risk"),
      mono: true,
      render: (r) =>
        r.p_churn != null && r.p_churn >= 0.7 ? (
          <span className="text-neg font-semibold">{pctRatio(r.p_churn)}</span>
        ) : (
          pctRatio(r.p_churn)
        ),
    },
    { key: "ltv", header: t("monitor.desk.col.ltv"), mono: true, render: (r) => tryAmount(r.pred_ltv_d90) },
    {
      key: "dep",
      header: t("monitor.desk.col.deps"),
      mono: true,
      // деп #N · P(след) NN% — p_next_deposit из API (борд :1852)
      render: (r) => (
        <span>
          {formatInt(r.dep_count)}
          {r.p_next_deposit != null ? (
            <span className="text-stone"> · {t("monitor.pNext", { pct: pctRatio(r.p_next_deposit) })}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: "pulse",
      header: t("monitor.desk.col.pulse"),
      mono: true,
      // «нет недавней игры» вместо «0 ₺», когда за окно нет спинов (борд :1845)
      render: (r) =>
        r.recent_spins === 0 ? (
          <span className="text-stone">{t("monitor.desk.pulseNoRecent")}</span>
        ) : (
          <span title={t("monitor.desk.pulseTitle", { net: tryAmount(r.recent_net), spins: formatInt(r.recent_spins) })}>
            <span className={r.recent_net < 0 ? "text-neg" : r.recent_net > 0 ? "text-pos" : undefined}>
              {tryAmount(r.recent_net)}
            </span>
            <span className="text-stone">{t("monitor.desk.pulseSpinsSuffix", { spins: formatInt(r.recent_spins) })}</span>
          </span>
        ),
    },
    {
      key: "recency",
      header: t("monitor.desk.col.recency"),
      mono: true,
      render: (r) => (r.recency_days == null ? "—" : t("monitor.desk.recencyDays", { days: formatInt(r.recency_days) })),
    },
    {
      key: "offer",
      header: t("monitor.desk.col.offer"),
      align: "left",
      render: (r) => <OfferCell offer={r.offer} status={r.offer_status} />,
    },
    {
      key: "when",
      header: t("monitor.desk.col.when"),
      align: "left",
      // why-подсказка под «когда»: проиграл → кэшбэк / в плюсе → нудж (борд :1847/:1849)
      render: (r) => {
        const why =
          r.recent_spins === 0
            ? null
            : r.recent_net < 0
              ? t("monitor.desk.why.losing")
              : t("monitor.desk.why.winning");
        return (
          <span>
            {r.when_to || "—"}
            {why ? <span className="block text-[11px] text-stone">{why}</span> : null}
          </span>
        );
      },
    },
    {
      // Назначить оператору прямо из очереди (руководителю — не идти в Пул)
      key: "assign",
      header: "",
      align: "right",
      render: (r) => <AssignButton playerId={r.player_id} />,
    },
  ];

  return (
    <>
      <PageHeader
        title={t("monitor.desk.title")}
        accent={t("monitor.desk.accent")}
        lead={t("monitor.desk.lead")}
        right={
          <PillRow>
            <Pill live>{t("monitor.pill.liveClickhouse")}</Pill>
            {d ? <Pill>{t("monitor.pill.asOf", { date: d.meta.asof })}</Pill> : null}
          </PillRow>
        }
      />

      <ModuleHeader module="core" />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <SCardGrid className="mt-6">
            <SCard loading={loading} variant="alert" icon="🎯" label={t("monitor.desk.kpi.inFilter.label")} value={formatInt(d?.kpi.n_filter)} sub={t("monitor.desk.kpi.inFilter.sub", { act })} />
            <SCard loading={loading} icon="💰" label={t("monitor.desk.kpi.filterValue.label")} value={tryAmount(d?.kpi.value_filter)} sub={t("monitor.desk.kpi.filterValue.sub")} />
            <SCard loading={loading} variant="cream" icon="📋" label={t("monitor.desk.kpi.queue.label")} value={formatInt(d?.kpi.n_queue)} sub={t("monitor.desk.kpi.queue.sub")} />
            <SCard loading={loading} icon="👥" label={t("monitor.desk.kpi.total.label")} value={formatInt(d?.kpi.n_total)} sub={t("monitor.desk.kpi.total.sub")} />
          </SCardGrid>

          {tier ? (
            <ChipBar>
              <Chip active onClick={clearTier} title={t("monitor.desk.vipPreset.hint")}>
                {t("monitor.desk.vipPreset.chip")}
              </Chip>
            </ChipBar>
          ) : null}

          <Eyebrow>{t("monitor.desk.eyebrow.task")}</Eyebrow>
          <ChipBar>
            {actOpts.map((o) => (
              <Chip key={o.key} active={o.key === act} onClick={() => setAct(o.key)}>
                {o.label}
              </Chip>
            ))}
          </ChipBar>

          <Eyebrow>
            {t("monitor.desk.eyebrow.window")}{" "}
            <span className="text-steel font-normal normal-case tracking-normal">
              {t("monitor.desk.eyebrow.windowNote")}
            </span>
          </Eyebrow>
          <ChipBar>
            {wOpts.map((o) => (
              <Chip key={o.key} active={o.key === w} onClick={() => setW(o.key)}>
                {o.label}
              </Chip>
            ))}
          </ChipBar>

          <Panel className="mt-2">
            <DataTable
              columns={cols}
              rows={d?.rows ?? []}
              getRowKey={(r) => r.player_id}
              getRowHref={(r) => `/players/${r.player_id}`}
              state={loading ? "loading" : d && d.rows.length ? "data" : "empty"}
              emptyTitle={t("monitor.desk.empty.title")}
              emptyDescription={t("monitor.desk.empty.desc")}
            />
          </Panel>

          <Note>{t("monitor.desk.note", { window: d?.meta.window_label ?? "—" })}</Note>
        </>
      )}
    </>
  );
}
