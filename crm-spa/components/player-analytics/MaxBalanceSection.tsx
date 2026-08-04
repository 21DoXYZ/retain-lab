"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Panel, Banner, SCard, SCardGrid, Select, Input, Button, Tabs,
  EmptyState, ErrorState, SkeletonText, Pill, PillRow,
} from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { MoneySpark } from "@/components/money/kit";
import { useT } from "@/lib/i18n";
import { useSection } from "./hooks";
import { Collapsible } from "./Collapsible";
import { fmtTry } from "./format";
import { EChart, RC } from "./Chart";

/**
 * 💹 Макс-баланс за период — ТЗ new_u/ТЗ_карточка_игрока_бонусы_и_макс_баланс.md
 * (фича 2, «закрывает рот»). Два режима:
 *   А «от депозита» (1 клик, основной для саппорта) — выбор депозита из списка,
 *     окно [депозит; следующий депозит) или «по текущий момент»;
 *   Б «произвольный период» (VIP-менеджер) — два поля дата-время (Стамбул).
 * Результат: максимальный баланс + момент достижения (обязательные), баланс на
 * конец, ставки и депозиты периода. Только РЕАЛЬНЫЙ кошелёк (balance_source=money).
 * Расчёт по клику (не авто) — окно может быть месяцами, считаем по запросу.
 */

interface DepositRow {
  ts: string;
  amount: number | null;
  status: string;
  completed: boolean;
  ts_raw: string;
}
interface DepositsData {
  player_id: number;
  count: number;
  deposits: DepositRow[];
}

interface MaxBalanceData {
  player_id: number;
  mode: "deposit" | "range";
  deposit: { ts_raw: string; amount: number; ts: string } | null;
  window: { from: string; to: string | null; open_ended: boolean };
  has_data: boolean;
  max_balance: number | null;
  peak_at: string | null;
  start_balance: number | null;
  end_balance: number | null;
  bets: number;
  no_spins: boolean;
  /** Ставки в окне были, но казино не прислало баланс (поток без остатка с 03.07). */
  spins_no_balance: number;
  deposits_count: number;
  deposits_sum: number;
  spark: number[];
  series: { labels: string[]; real: (number | null)[]; bonus: (number | null)[] } | null;
  events: BalanceEvent[];
  bonus_count: number;
  bonus_sum: number;
  wallet: string;
  /** Сводка бонусного кошелька — окно могло быть чисто бонусным (реальный пуст). */
  bonus_wallet: { n: number; max: number; peak_at: string; start: number; end: number } | null;
}

interface BalanceEvent {
  ts: string;
  kind: "deposit" | "manual_deposit" | "withdrawal" | "bonus" | string;
  amount: number;
  balance_after: number | null;
  bonus_balance_after: number | null;
  /** Тип бонуса (cashback/freespins/deposit-match/no-deposit/other) — только у бонусов. */
  btype: string | null;
  /** Платёжка депозита/вывода (papara, havale, …) — только у денежных операций. */
  method: string | null;
  /** Название/описание операции из данных казино (у бонусов — какой именно). */
  name: string | null;
}

type CalcState = "idle" | "loading" | "error" | "data";

export function MaxBalanceSection({ playerId }: { playerId: number }) {
  const t = useT();
  // список депозитов — для режима А; 403 (роль без списка) → остаётся режим Б
  // limit=200: последних 30 может не хватить — хвост бывает целиком в дыре
  // потока (июль), и все окна режима А оказываются «нет данных»
  const deposits = useSection<DepositsData>(`/api/v1/players/${playerId}/deposits?limit=200`);
  const depositsDenied = deposits.state === "error" && deposits.status === 403;

  const [mode, setMode] = useState<"deposit" | "range">("deposit");
  const [depTs, setDepTs] = useState("");
  const [fromV, setFromV] = useState("");
  const [toV, setToV] = useState("");
  const [state, setState] = useState<CalcState>("idle");
  const [res, setRes] = useState<MaxBalanceData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);   // сворачиваемый (запрос владельца)
  const rootRef = useRef<HTMLDivElement | null>(null);

  const completedDeps = (deposits.data?.deposits ?? []).filter((d) => d.completed);

  function calc(depOverride?: string) {
    setFormErr(null);
    setCopied(false);
    const qs = new URLSearchParams();
    const ts = depOverride ?? depTs;
    if (depOverride || mode === "deposit") {
      if (!ts) {
        setFormErr(t("analytics.maxbal.pickDepositFirst"));
        return;
      }
      qs.set("deposit_ts", ts);
    } else {
      if (!fromV || !toV) {
        setFormErr(t("analytics.maxbal.needBothDates"));
        return;
      }
      if (fromV >= toV) {                      // ТЗ: «от > до» — валидация, не считать
        setFormErr(t("analytics.maxbal.badRange"));
        return;
      }
      qs.set("from", fromV);
      qs.set("to", toV);
    }
    setState("loading");
    setErr(null);
    flaskFetch<MaxBalanceData>(`/api/v1/players/${playerId}/max-balance?${qs.toString()}`)
      .then((d) => {
        setRes(d);
        setState("data");
      })
      .catch((e: unknown) => {
        setErr(flaskErrorText(e, t, "common.loadFailed"));
        setState("error");
      });
  }

  const calcRef = useRef(calc);
  useEffect(() => {
    calcRef.current = calc;   // всегда свежий calc для внешнего события (не в рендере)
  });
  const onDepositPick = useCallback((e: Event) => {
    const ts = (e as CustomEvent<string>).detail;
    if (!ts) return;
    setOpen(true);                          // мост из депозитов раскрывает секцию
    setMode("deposit");
    setDepTs(ts);
    calcRef.current(ts);
    rootRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);
  useEffect(() => {
    window.addEventListener("maxbal:deposit", onDepositPick);
    return () => window.removeEventListener("maxbal:deposit", onDepositPick);
  }, [onDepositPick]);

  /** Та самая фраза-аргумент: показывается предпросмотром и уходит в буфер. */
  function argumentText(r: MaxBalanceData): string {
    return [
      r.deposit ? t("analytics.maxbal.copyDeposit", { sum: fmtTry(r.deposit.amount), ts: r.deposit.ts }) : null,
      r.max_balance !== null
        ? t("analytics.maxbal.copyMax", { sum: fmtTry(r.max_balance), ts: r.peak_at ?? "" })
        : t("analytics.maxbal.copyRealEmpty"),
      r.max_balance !== null ? t("analytics.maxbal.copyEnd", { sum: fmtTry(r.end_balance) }) : null,
      // чисто бонусное окно: аргумент честно опирается на бонусный кошелёк
      r.max_balance === null && r.bonus_wallet
        ? t("analytics.maxbal.copyBonusPeak", { sum: fmtTry(r.bonus_wallet.max), ts: r.bonus_wallet.peak_at })
        : null,
    ].filter(Boolean).join(" · ");
  }

  function copyArgument(r: MaxBalanceData) {
    navigator.clipboard?.writeText(argumentText(r)).then(() => setCopied(true)).catch(() => {});
  }

  return (
    <div ref={rootRef}>
      <Collapsible
        title={t("analytics.maxbal.title")}
        caption={t("analytics.maxbal.caption")}
        open={open}
        onToggle={setOpen}
      >
      <Panel>
        <Tabs
          tabs={[
            ...(depositsDenied ? [] : [{ key: "deposit", label: t("analytics.maxbal.tabDeposit") }]),
            { key: "range", label: t("analytics.maxbal.tabRange") },
          ]}
          value={depositsDenied ? "range" : mode}
          onChange={(k) => setMode(k as "deposit" | "range")}
        />

        <div className="flex flex-wrap items-center gap-2 mt-3">
          {mode === "deposit" && !depositsDenied ? (
            deposits.state === "loading" ? (
              <SkeletonText lines={1} />
            ) : (
              <Select
                className="!w-auto min-w-[260px]"
                value={depTs}
                onChange={(e) => setDepTs(e.target.value)}
                aria-label={t("analytics.maxbal.pickDeposit")}
              >
                <option value="">{t("analytics.maxbal.pickDeposit")}…</option>
                {completedDeps.map((d) => (
                  <option key={d.ts_raw} value={d.ts_raw}>
                    {d.ts} · {fmtTry(d.amount)}
                  </option>
                ))}
              </Select>
            )
          ) : (
            <>
              <Input
                type="datetime-local"
                className="!w-auto"
                value={fromV}
                aria-label={t("analytics.maxbal.from")}
                onChange={(e) => setFromV(e.target.value)}
              />
              <span className="text-steel">—</span>
              <Input
                type="datetime-local"
                className="!w-auto"
                value={toV}
                aria-label={t("analytics.maxbal.to")}
                onChange={(e) => setToV(e.target.value)}
              />
            </>
          )}
          <Button onClick={() => calc()} disabled={state === "loading"}>
            {t("analytics.maxbal.calc")}
          </Button>
        </div>
        {formErr ? <div className="text-neg text-[13px] mt-2">{formErr}</div> : null}
        {mode === "deposit" && !depositsDenied && deposits.state === "data" && completedDeps.length === 0 ? (
          <div className="text-steel text-[13px] mt-2">{t("analytics.maxbal.noDeposits")}</div>
        ) : null}
      </Panel>

      {/* ── результат ── */}
      {state === "loading" ? (
        <Panel className="mt-3">
          <SkeletonText lines={3} />
        </Panel>
      ) : null}
      {state === "error" ? (
        <Panel className="mt-3">
          <ErrorState description={err ?? undefined} onRetry={() => calc()} />
        </Panel>
      ) : null}
      {state === "data" && res ? (
        !res.has_data ? (
          <Panel className="mt-3">
            <EmptyState
              title={t("analytics.maxbal.noData")}
              description={
                res.spins_no_balance > 0
                  ? t("analytics.maxbal.noBalanceStream", { n: res.spins_no_balance })
                  : t("analytics.maxbal.noDataHint")
              }
            />
          </Panel>
        ) : (
          <div className="mt-3">
            <SCardGrid>
              <SCard
                variant="cream"
                label={t("analytics.maxbal.resultMax")}
                value={res.max_balance !== null ? fmtTry(res.max_balance) : "—"}
                sub={
                  res.max_balance === null
                    ? t("analytics.maxbal.realEmpty")
                    : res.peak_at
                      ? t("analytics.maxbal.resultPeak", { ts: res.peak_at })
                      : undefined
                }
                spark={res.spark.length > 1 ? <MoneySpark values={res.spark} /> : undefined}
              />
              <SCard
                label={t("analytics.maxbal.resultEnd")}
                value={res.end_balance !== null ? fmtTry(res.end_balance) : "—"}
                sub={res.window.open_ended ? t("analytics.maxbal.openEnded") : undefined}
              />
            </SCardGrid>
            <PillRow className="mt-2">
              {res.deposit ? (
                <Pill>{t("analytics.maxbal.resultDeposit")}: {fmtTry(res.deposit.amount)} · {res.deposit.ts}</Pill>
              ) : null}
              <Pill>
                {t("analytics.maxbal.resultWindow")}: {res.window.from} — {res.window.to ?? t("analytics.maxbal.openEnded")}
              </Pill>
              <Pill>{t("analytics.maxbal.resultBets")}: {res.bets}</Pill>
              <Pill>
                {t("analytics.maxbal.resultDeps", { n: res.deposits_count, sum: fmtTry(res.deposits_sum) })}
              </Pill>
              {res.bonus_count > 0 ? (
                <Pill>{t("analytics.maxbal.resultBonuses", { n: res.bonus_count, sum: fmtTry(res.bonus_sum) })}</Pill>
              ) : null}
              <Pill>{t("analytics.maxbal.wallet")}</Pill>
            </PillRow>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => copyArgument(res)}>
                {t("analytics.maxbal.copyBtn")}
              </Button>
              {copied ? (
                <span className="text-pos text-[13px]">{t("analytics.maxbal.copied")}</span>
              ) : (
                <span className="text-[12px] text-stone">{t("analytics.maxbal.copyHint")}</span>
              )}
            </div>
            {/* предпросмотр: видно, ЧТО именно уйдёт в буфер */}
            <div className="mt-1 max-w-[760px] rounded-[8px] border border-hair bg-surface px-3 py-2 text-[12.5px] leading-relaxed text-steel">
              «{argumentText(res)}»
            </div>
            <WalletJourney res={res} />
            <EventsJournal events={res.events} />
            {res.no_spins && res.max_balance !== null ? (
              <Banner className="mt-3">
                {t("analytics.maxbal.noSpins", { sum: fmtTry(res.max_balance) })}
              </Banner>
            ) : null}
          </div>
        )
      ) : null}
      </Collapsible>
    </div>
  );
}


/**
 * «Как менялся баланс»: строка-вехи по обоим кошелькам (старт → пик → конец) +
 * компактный график. Линии — верхняя огибающая корзин (максимум): вопрос
 * пользователя «сколько было», а не «сколько осталось к концу корзины».
 * Бонусный кошелёк показываем только если он в периоде вообще был ненулевым.
 */
function WalletJourney({ res }: { res: MaxBalanceData }) {
  const t = useT();
  const s = res.series;
  if (!s || s.labels.length < 2) return null;
  const real = s.real.filter((v): v is number => v != null);
  const bonus = s.bonus.filter((v): v is number => v != null);
  const bonusActive = bonus.length > 0 && Math.max(...bonus) > 0;

  return (
    <div className="mt-3">
      <div className="text-[13px] text-steel">
        <span className="text-ink">{t("analytics.maxbal.pathReal", {
          start: fmtTry(real[0] ?? null),
          peak: fmtTry(real.length ? Math.max(...real) : null),
          end: fmtTry(real.length ? real[real.length - 1] : null),
        })}</span>
        {bonusActive ? (
          <span> · {t("analytics.maxbal.pathBonus", {
            start: fmtTry(bonus[0]),
            peak: fmtTry(Math.max(...bonus)),
            end: fmtTry(bonus[bonus.length - 1]),
          })}</span>
        ) : null}
      </div>
      <Panel className="mt-2">
        <EChart
          height={190}
          option={{
            grid: { left: 56, right: 12, top: 26, bottom: 22 },
            legend: {
              top: 0,
              itemWidth: 14,
              textStyle: { fontSize: 11, color: RC.steel },
              data: [t("analytics.maxbal.walletReal"), ...(bonusActive ? [t("analytics.maxbal.walletBonus")] : [])],
            },
            tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "—" : `${Math.round(Number(v))} ₺`) },
            xAxis: {
              type: "category",
              data: s.labels,
              axisLabel: { fontSize: 10, color: RC.steel },
              axisLine: { lineStyle: { color: RC.hair } },
            },
            yAxis: {
              type: "value",
              axisLabel: { fontSize: 10, color: RC.steel },
              splitLine: { lineStyle: { color: RC.hair } },
            },
            series: [
              {
                name: t("analytics.maxbal.walletReal"),
                type: "line",
                data: s.real,
                connectNulls: true,
                showSymbol: false,
                lineStyle: { color: RC.primary, width: 2 },
                itemStyle: { color: RC.primary },
                areaStyle: { color: RC.primary, opacity: 0.06 },
              },
              ...(bonusActive
                ? [{
                    name: t("analytics.maxbal.walletBonus"),
                    type: "line" as const,
                    data: s.bonus,
                    connectNulls: true,
                    showSymbol: false,
                    lineStyle: { color: RC.steel, width: 1.5, type: "dashed" as const },
                    itemStyle: { color: RC.steel },
                  }]
                : []),
            ],
          }}
        />
      </Panel>
    </div>
  );
}


/**
 * Журнал изменений периода (запрос владельца: «текстом, не только графиком»):
 * каждая денежная операция окна — когда, что и сколько; бонусы подсвечены,
 * баланс после операции — если казино его прислало. До 300 строк, скролл.
 */
const EV_STYLE: Record<string, { bg: string; fg: string }> = {
  deposit: { bg: "#f0fdf4", fg: "#166534" },
  manual_deposit: { bg: "#fef9c3", fg: "#854d0e" },
  withdrawal: { bg: "#fee2e2", fg: "#991b1b" },
  bonus: { bg: "#f5f3ff", fg: "#5b21b6" },
};

function EventsJournal({ events }: { events: BalanceEvent[] }) {
  const t = useT();
  if (!events.length) return null;
  const label = (k: string) =>
    k === "deposit" ? t("analytics.maxbal.ev.deposit")
    : k === "manual_deposit" ? t("analytics.maxbal.ev.manualDeposit")
    : k === "withdrawal" ? t("analytics.maxbal.ev.withdrawal")
    : t("analytics.maxbal.ev.bonus");
  return (
    <div className="mt-3">
      <div className="text-[12.5px] uppercase tracking-[0.5px] text-steel mb-1.5">
        {t("analytics.maxbal.eventsTitle")} · {events.length}
      </div>
      <Panel className="max-h-[300px] overflow-y-auto">
        <ul className="divide-y divide-hair">
          {events.map((e, i) => {
            const st = EV_STYLE[e.kind] ?? { bg: "#f1f5f9", fg: "#475569" };
            const neg = e.kind === "withdrawal";
            return (
              <li key={i} className="py-1.5 flex items-center gap-3 text-[13px]">
                <span className="font-mono text-steel w-[86px] flex-none">{e.ts}</span>
                <span className="rounded-full px-2 py-0.5 text-[11.5px] flex-none"
                      style={{ background: st.bg, color: st.fg }}>
                  {label(e.kind)}
                </span>
                <span className={`font-mono ${neg ? "text-neg" : "text-pos"}`}>
                  {neg ? "−" : "+"}{fmtTry(e.amount)}
                </span>
                {/* бонус: тип · название; депозит/вывод: платёжка · комментарий */}
                {e.btype || e.method || e.name ? (
                  <span className="text-[12px] text-steel min-w-0 truncate">
                    {[e.kind === "bonus" ? e.btype : e.method, e.name].filter(Boolean).join(" · ")}
                  </span>
                ) : null}
                {e.balance_after != null ? (
                  <span className="ml-auto text-[12px] text-stone">
                    {t("analytics.maxbal.ev.balanceAfter")}: {fmtTry(e.balance_after)}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </Panel>
    </div>
  );
}
