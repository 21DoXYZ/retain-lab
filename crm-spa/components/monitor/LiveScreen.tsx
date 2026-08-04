"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  PageHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Panel,
  Chip,
  ChipBar,
  Pill,
  PillRow,
  LifecycleBadge,
  ActionBadge,
  Spinner,
  Skeleton,
  EmptyState,
  ErrorState,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { usePolling, pctRatio, tryAmount, agoLabel, OfferCell, Note } from "./kit";
import { AssignButton } from "./AssignButton";
import type { LiveData, LiveRow } from "./types";

/**
 * /live — «Играют сейчас» (paritet с live() борда). Показывает текущую сессию
 * каждого активного игрока за окно w минут. Реалтайм реализован ОПРОСОМ (polling)
 * этого эндпоинта каждые 20 сек — не SSE (см. api/monitor.py: "polling-обновление
 * на фронте"). Прежние данные остаются на экране между опросами, чтобы таблица не
 * «моргала». Смена окна перезапрашивает сразу. Роли: LIVE_ROLES.
 */

const POLL_MS = 20_000; // meta.poll_seconds = 20 в api/monitor.py
const WINDOWS = [15, 30, 60, 180] as const;

/** Выравнивание ячейки как в DataTable: явный align, иначе первая — влево. */
function cellAlign(col: Column<LiveRow>, index: number): string {
  const align = col.align ?? (index === 0 ? "left" : "right");
  return align === "left" ? "text-left" : "text-right";
}

export function LiveScreen() {
  const t = useT();
  const router = useRouter();
  const [win, setWin] = useState<number>(30);

  const path = useMemo(() => `/api/v1/live?w=${win}`, [win]);
  const { state, data, error, refreshing, reload } = usePolling<LiveData>(path, POLL_MS, t("monitor.fetchError"));
  const loading = state === "loading";
  const d = data;

  const agoUnits = { sec: t("monitor.ago.sec"), min: t("monitor.ago.min"), h: t("monitor.ago.h") };

  const cols: Column<LiveRow>[] = [
    {
      key: "player",
      header: t("monitor.live.col.player"),
      id: true,
      render: (r) => (
        <span className="inline-flex items-center gap-1.5">
          {r.alert ? <span title={t("monitor.live.alertTitle")}>🚨</span> : null}
          {r.player_id}
        </span>
      ),
    },
    {
      key: "ago",
      header: t("monitor.live.col.ago"),
      mono: true,
      render: (r) => (
        <span className="text-stone">
          {agoLabel(r.ago_seconds, agoUnits)} {t("monitor.ago.suffix")}
        </span>
      ),
    },
    { key: "game", header: t("monitor.live.col.game"), align: "left", render: (r) => r.cur_game || "—" },
    {
      key: "net",
      header: t("monitor.live.col.net"),
      mono: true,
      render: (r) => (
        <span className={r.cur_net < 0 ? "text-neg font-semibold" : r.cur_net > 0 ? "text-pos" : undefined}>
          {tryAmount(r.cur_net)}
        </span>
      ),
    },
    { key: "spins", header: t("monitor.live.col.spins"), mono: true, render: (r) => formatInt(r.cur_spins) },
    { key: "dur", header: t("monitor.live.col.dur"), mono: true, render: (r) => t("monitor.live.durMin", { n: formatInt(r.cur_dur) }) },
    {
      // «деп #N · P(след) NN%» — dep_count + p_next_deposit из API (борд :1952/:1946)
      key: "deps",
      header: t("monitor.live.col.deps"),
      mono: true,
      render: (r) => (
        <span>
          {t("monitor.live.depCount", { n: formatInt(r.dep_count) })}
          {r.p_next_deposit != null ? (
            <span className="text-stone"> · {t("monitor.pNext", { pct: pctRatio(r.p_next_deposit) })}</span>
          ) : null}
        </span>
      ),
    },
    { key: "stage", header: t("monitor.live.col.stage"), align: "left", render: (r) => <LifecycleBadge stage={r.lifecycle} /> },
    { key: "action", header: t("monitor.live.col.action"), align: "left", render: (r) => <ActionBadge action={r.action} /> },
    { key: "risk", header: t("monitor.live.col.risk"), mono: true, render: (r) => pctRatio(r.p_churn) },
    { key: "ltv", header: t("monitor.live.col.ltv"), mono: true, render: (r) => tryAmount(r.pred_ltv_d90) },
    {
      // «Что делать СЕЙЧАС» — смысловой центр экрана (борд :1940-1944)
      key: "now",
      header: t("monitor.live.col.now"),
      align: "left",
      render: (r) =>
        r.cur_net < 0 ? (
          <span className="font-medium text-ink">
            {t("monitor.live.now.losingLead")}{" "}
            <b className="font-semibold">{t("monitor.live.now.losingCta")}</b>
          </span>
        ) : r.cur_net > 0 ? (
          <span className="text-ink">{t("monitor.live.now.winning")}</span>
        ) : (
          <span className="text-stone">{t("monitor.live.now.flat")}</span>
        ),
    },
    { key: "offer", header: t("monitor.live.col.offer"), align: "left", render: (r) => <OfferCell offer={r.offer} /> },
    // Назначить оператору прямо из «Играют сейчас» — ловим момент, не уходя в Пул.
    { key: "assign", header: "", align: "right", render: (r) => <AssignButton playerId={r.player_id} /> },
  ];

  return (
    <>
      <PageHeader
        title={t("monitor.live.title")}
        accent={t("monitor.live.accent")}
        lead={t("monitor.live.lead")}
        right={
          <PillRow>
            <Pill live>
              <span className="inline-flex items-center gap-1.5">
                {refreshing ? <Spinner size={12} /> : <span className="w-2 h-2 rounded-full bg-white/90 inline-block" />}
                {t("monitor.live.pill.polling", { sec: POLL_MS / 1000 })}
              </span>
            </Pill>
            {d ? <Pill>{t("monitor.live.pill.window", { n: d.meta.window_min })}</Pill> : null}
          </PillRow>
        }
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <SCardGrid className="mt-6">
            <SCard loading={loading} variant="alert" icon="🚨" label={t("monitor.live.kpi.alert.label")} value={formatInt(d?.kpi.n_alert)} sub={t("monitor.live.kpi.alert.sub")} />
            <SCard loading={loading} variant="cream" icon="🔴" label={t("monitor.live.kpi.now.label")} value={formatInt(d?.kpi.n_now)} sub={t("monitor.live.kpi.now.sub", { n: d?.meta.window_min ?? win })} />
            <SCard loading={loading} icon="📋" label={t("monitor.live.kpi.shown.label")} value={formatInt(d?.kpi.shown)} sub={t("monitor.live.kpi.shown.sub")} />
            <SCard loading={loading} icon="⏱" label={t("monitor.live.kpi.poll.label")} value={t("monitor.live.kpi.poll.value", { sec: POLL_MS / 1000 })} sub={t("monitor.live.kpi.poll.sub")} />
          </SCardGrid>

          <Eyebrow>
            {t("monitor.live.eyebrow.window")}{" "}
            <span className="text-steel font-normal normal-case tracking-normal">
              {t("monitor.live.eyebrow.windowNote")}
            </span>
          </Eyebrow>
          <ChipBar>
            {WINDOWS.map((m) => (
              <Chip key={m} active={m === win} onClick={() => setWin(m)}>
                {t("monitor.live.chip.window", { n: m })}
              </Chip>
            ))}
          </ChipBar>

          {/*
            Таблица собрана из примитивов (не DataTable), чтобы подсветить
            строку-алерт фоном #fff1f2 (борд :1947) — DataTable не даёт задать
            стиль на строку. Разметка ячеек 1:1 с DataTable.
          */}
          <Panel className="mt-2">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13.5px]">
                <thead>
                  <tr>
                    {cols.map((col, i) => (
                      <th
                        key={col.key}
                        className={cn(
                          "font-normal text-steel text-[11px] uppercase tracking-[0.5px]",
                          "bg-surface px-3.5 py-[11px] border-b border-hair whitespace-nowrap sticky top-0",
                          cellAlign(col, i),
                        )}
                      >
                        {col.header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    Array.from({ length: 6 }).map((_, r) => (
                      <tr key={`sk-${r}`}>
                        {cols.map((col, i) => (
                          <td key={col.key} className="px-3.5 py-[11px] border-b border-hair">
                            <Skeleton className={cn("h-3.5", i === 0 ? "w-28" : "w-16 ml-auto")} />
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : d && d.rows.length ? (
                    d.rows.map((row) => {
                      const go = () => router.push(`/players/${row.player_id}`);
                      return (
                        <tr
                          key={row.player_id}
                          onClick={go}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") go();
                          }}
                          tabIndex={0}
                          // inline-style бьёт hover, как inline-фон строки в HTML-борде
                          style={row.alert ? { background: "#fff1f2" } : undefined}
                          className="cursor-pointer transition-colors hover:bg-cream"
                        >
                          {cols.map((col, i) => (
                            <td
                              key={col.key}
                              className={cn(
                                "px-3.5 py-[11px] border-b border-hair whitespace-nowrap",
                                cellAlign(col, i),
                                (col.mono || col.id) && "font-mono",
                                col.id && "text-primary font-medium",
                                col.className,
                              )}
                            >
                              {col.render(row)}
                            </td>
                          ))}
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={cols.length} className="p-0">
                        <EmptyState
                          title={t("monitor.live.empty.title")}
                          description={t("monitor.live.empty.desc")}
                        />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Panel>

          <Note>
            {t("monitor.live.note", { asof: d?.meta.asof ?? "—", sec: POLL_MS / 1000 })}
          </Note>
        </>
      )}
    </>
  );
}
