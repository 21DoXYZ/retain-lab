"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import {
  Panel, DataTable, Banner, Pill, PillRow, Chip, ChipBar, DateInput,
  EmptyState, type Column,
} from "@/components/ui";
import { useT } from "@/lib/i18n";
import { useSection } from "./hooks";
import { Collapsible } from "./Collapsible";
import { SectionBody } from "./SectionShell";
import { fmtTry } from "./format";

/**
 * 🎁 Бонусы — ТЗ new_u/ТЗ_карточка_игрока_бонусы_и_макс_баланс.md (фича 1).
 * Сводка по статусам (выдано/активировано/отыграно/сгорело/отменено + bonus cost
 * + депозиты в окне N дней после бонуса) + таблица выдач с фильтрами
 * (статус ×N, тип ×N, период выдачи). Состояние фильтров живёт в URL
 * (b_status/b_type/b_from/b_to) — ссылку можно скинуть коллеге.
 *
 * Жизненный цикл (активирован/отыгран/сгорел) приходит из потока bonus_status;
 * пока казино его не шлёт — сервер отдаёт lifecycle_available=false и статусные
 * ячейки честно показывают «нет данных» (ТЗ: колонку не скрываем).
 * Фильтрация серверная (query-параметры эндпоинта); сводка не фильтруется.
 */

const CYCLE_STATUSES = ["issued", "activated", "wagering_completed", "expired", "cancelled"] as const;

interface BonusRow {
  ts: string;
  ts_raw: string;
  type: string;
  tx_type: string;
  name: string | null;
  amount: number | null;
  currency: string;
  status: string;
  lifecycle: boolean;
  status_at: string | null;
  wager_requirement: number | null;
  wager_multiplier: number | null;
  wagered_amount: number | null;
  dep_after: boolean;
  dep_after_count: number;
  dep_after_sum: number;
}

interface BonusSummary {
  issued: number;
  activated: number;
  wagering_completed: number;
  expired: number;
  cancelled: number;
  bonus_cost: number;
  deps_after_count: number;
  deps_after_sum: number;
}

interface BonusesData {
  player_id: number;
  count: number;
  bonuses: BonusRow[];
  window_days: number;
  lifecycle_available: boolean;
  types: string[];
  summary: BonusSummary | null;
}

/** Стартовое значение фильтра из URL (SSR-безопасно). */
function urlGet(key: string): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(key) ?? "";
}

/** Зеркалим фильтры в URL без перезагрузки (board-паттерн history.replaceState). */
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

const csv = (xs: string[]) => xs.filter(Boolean).join(",");
const uncsv = (s: string) => s.split(",").filter(Boolean);

interface UrlFilters {
  status: string[];
  type: string[];
  from: string;
  to: string;
  react: string;
}

const emptySubscribe = () => () => {};
/** true только после гидратации (SSR/первый клиентский рендер — false). */
const useHydrated = () => useSyncExternalStore(emptySubscribe, () => true, () => false);

/**
 * Оболочка: URL читаем ТОЛЬКО после гидратации — SSR-HTML и первый клиентский
 * рендер совпадают (иначе hydration mismatch при ссылке с фильтрами).
 */
export function BonusSection({ playerId }: { playerId: number }) {
  const t = useT();
  const hydrated = useHydrated();
  const init = useMemo<UrlFilters | null>(
    () =>
      hydrated
        ? {
            status: uncsv(urlGet("b_status")),
            type: uncsv(urlGet("b_type")),
            from: urlGet("b_from"),
            to: urlGet("b_to"),
            react: urlGet("b_react"),
          }
        : null,
    [hydrated],
  );
  if (!init) {
    return (
      <Collapsible title={t("analytics.bonus.title")} count={null} caption={t("analytics.bonus.caption")}>
        <div />
      </Collapsible>
    );
  }
  return <BonusSectionInner playerId={playerId} init={init} />;
}

function BonusSectionInner({ playerId, init }: { playerId: number; init: UrlFilters }) {
  const t = useT();
  const [statusF, setStatusF] = useState<string[]>(init.status);
  const [typeF, setTypeF] = useState<string[]>(init.type);
  const [fromF, setFromF] = useState<string>(init.from);
  const [toF, setToF] = useState<string>(init.to);
  const [reactF, setReactF] = useState<string>(init.react);

  const path = useMemo(() => {
    const qs = new URLSearchParams();
    if (statusF.length) qs.set("status", csv(statusF));
    if (typeF.length) qs.set("type", csv(typeF));
    if (fromF) qs.set("from", fromF);
    if (toF) qs.set("to", toF);
    if (reactF) qs.set("reaction", reactF);
    const s = qs.toString();
    return `/api/v1/players/${playerId}/bonuses${s ? `?${s}` : ""}`;
  }, [playerId, statusF, typeF, fromF, toF, reactF]);

  const section = useSection<BonusesData>(path);
  const hasFilters = statusF.length > 0 || typeF.length > 0 || !!fromF || !!toF || !!reactF;

  const STATUS_LABEL: Record<string, string> = {
    issued: t("analytics.bonus.statusIssued"),
    activated: t("analytics.bonus.statusActivated"),
    wagering_completed: t("analytics.bonus.statusWagered"),
    expired: t("analytics.bonus.statusExpired"),
    cancelled: t("analytics.bonus.statusCancelled"),
  };

  function toggle(list: string[], set: (v: string[]) => void, key: string, value: string) {
    const next = list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
    set(next);
    urlSync({ [key]: csv(next) });
  }

  function resetFilters() {
    setStatusF([]);
    setTypeF([]);
    setFromF("");
    setToF("");
    setReactF("");
    urlSync({ b_status: "", b_type: "", b_from: "", b_to: "", b_react: "" });
  }

  function toggleReact(v: string) {
    const next = reactF === v ? "" : v;
    setReactF(next);
    urlSync({ b_react: next });
  }

  const noData = <span className="text-stone">{t("analytics.bonus.noLifecycle")}</span>;

  const COLS: Column<BonusRow>[] = [
    { key: "ts", header: t("analytics.bonus.colIssued"), mono: true, render: (b) => b.ts },
    {
      key: "type",
      header: t("analytics.bonus.colName"),
      align: "left",
      render: (b) => (
        <span>
          {b.type}
          {b.name ? <span className="text-stone"> · {b.name}</span> : null}
        </span>
      ),
    },
    { key: "amt", header: t("analytics.bonus.colAmount"), mono: true, render: (b) => fmtTry(b.amount) },
    {
      key: "wager",
      header: t("analytics.bonus.colWager"),
      mono: true,
      render: (b) =>
        b.lifecycle && b.wager_requirement
          ? `${fmtTry(b.wagered_amount)} / ${fmtTry(b.wager_requirement)}`
          : noData,
    },
    {
      key: "status",
      header: t("analytics.bonus.colStatus"),
      render: (b) => (
        <Pill className={b.lifecycle ? undefined : "text-stone"}>
          {STATUS_LABEL[b.status] ?? b.status}
        </Pill>
      ),
    },
    {
      key: "statusAt",
      header: t("analytics.bonus.colStatusAt"),
      mono: true,
      render: (b) => (b.lifecycle && b.status_at ? b.status_at : noData),
    },
    {
      key: "reaction",
      header: t("analytics.bonus.colReaction", { d: section.data?.window_days ?? 7 }),
      render: (b) =>
        b.dep_after ? (
          <span className="text-pos">
            {t("analytics.bonus.reactionYes", { n: b.dep_after_count, sum: fmtTry(b.dep_after_sum) })}
          </span>
        ) : (
          <span className="text-steel">{t("analytics.bonus.reactionNo")}</span>
        ),
    },
  ];

  return (
    <Collapsible
      title={t("analytics.bonus.title")}
      count={section.data?.summary?.issued ?? section.data?.count ?? null}
      caption={t("analytics.bonus.caption")}
      defaultOpen={hasFilters /* пришли по ссылке с фильтрами — сразу раскрываем */}
    >
      <SectionBody
        section={section}
        isEmpty={(d) => d.bonuses.length === 0 && !hasFilters}
        emptyTitle={t("analytics.bonus.empty")}
      >
        {(d) => (
          <>
            {/* ── сводная строка (ТЗ 1.1) — по всем бонусам, фильтры на неё не влияют ── */}
            {d.summary ? (
              <>
                <PillRow className="mb-1">
                  <Pill>{t("analytics.bonus.summaryIssued")} {d.summary.issued}</Pill>
                  <Pill>{t("analytics.bonus.summaryActivated")} {d.lifecycle_available ? d.summary.activated : t("analytics.bonus.noLifecycle")}</Pill>
                  <Pill>{t("analytics.bonus.summaryWagered")} {d.lifecycle_available ? d.summary.wagering_completed : t("analytics.bonus.noLifecycle")}</Pill>
                  <Pill>{t("analytics.bonus.summaryExpired")} {d.lifecycle_available ? d.summary.expired : t("analytics.bonus.noLifecycle")}</Pill>
                  <Pill>{t("analytics.bonus.summaryCancelled")} {d.lifecycle_available ? d.summary.cancelled : t("analytics.bonus.noLifecycle")}</Pill>
                </PillRow>
                <div className="text-[13px] text-steel mb-2">
                  {t("analytics.bonus.summaryCost")}: <span className="font-mono text-ink">{fmtTry(d.summary.bonus_cost)}</span>
                  {" · "}
                  {t("analytics.bonus.summaryDeps", {
                    n: d.summary.deps_after_count,
                    sum: fmtTry(d.summary.deps_after_sum),
                    d: d.window_days,
                  })}
                </div>
              </>
            ) : null}

            {/* ── фильтры (ТЗ 1.3): статус ×N · тип ×N · период выдачи; живут в URL ── */}
            <ChipBar className="my-2">
              {CYCLE_STATUSES.map((s) => (
                <Chip key={s} active={statusF.includes(s)}
                      onClick={() => toggle(statusF, setStatusF, "b_status", s)}>
                  {STATUS_LABEL[s]}
                </Chip>
              ))}
              <span className="text-stone">·</span>
              {d.types.map((tp) => (
                <Chip key={tp} active={typeF.includes(tp)}
                      onClick={() => toggle(typeF, setTypeF, "b_type", tp)}>
                  {tp}
                </Chip>
              ))}
              <Chip active={reactF === "yes"} onClick={() => toggleReact("yes")}>
                {t("analytics.bonus.filterReactYes")}
              </Chip>
              <Chip active={reactF === "no"} onClick={() => toggleReact("no")}>
                {t("analytics.bonus.filterReactNo")}
              </Chip>
              <DateInput
                className="!h-[34px] !w-auto text-[12.5px]"
                value={fromF}
                aria-label={t("analytics.bonus.filterFrom")}
                onChange={(e) => { setFromF(e.target.value); urlSync({ b_from: e.target.value }); }}
              />
              <DateInput
                className="!h-[34px] !w-auto text-[12.5px]"
                value={toF}
                aria-label={t("analytics.bonus.filterTo")}
                onChange={(e) => { setToF(e.target.value); urlSync({ b_to: e.target.value }); }}
              />
              {hasFilters ? (
                <Chip onClick={resetFilters}>{t("analytics.bonus.filterReset")}</Chip>
              ) : null}
            </ChipBar>

            {/* ── таблица (ТЗ 1.2), новые сверху ── */}
            {d.bonuses.length === 0 ? (
              <Panel>
                <EmptyState
                  title={t("analytics.bonus.emptyFiltered")}
                  description={t("analytics.bonus.emptyFilteredHint")}
                />
              </Panel>
            ) : (
              <Panel>
                <DataTable
                  columns={COLS}
                  rows={d.bonuses}
                  getRowKey={(b, i) => `${b.ts_raw}-${i}`}
                  state="data"
                />
              </Panel>
            )}
            {!d.lifecycle_available ? (
              <Banner className="mt-3">{t("analytics.bonus.lifecycleBanner")}</Banner>
            ) : null}
          </>
        )}
      </SectionBody>
    </Collapsible>
  );
}
