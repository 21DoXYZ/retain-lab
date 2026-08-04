"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import {
  PageHeader,
  SCard,
  SCardGrid,
  Banner,
  Chip,
  ChipBar,
  DataTable,
  Badge,
  Pill,
  PillRow,
  ErrorState,
  EmptyState,
  type Column,
  type TableState,
} from "@/components/ui";
import { formatInt, formatMoney } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { useFlaskData } from "@/components/marketing/useFlaskData";

/**
 * /flags — «Лента флагов» модуля Риск и фрод (W2-T3). Единая очередь «требует
 * проверки»: агрегирует уже посчитанные сигналы из /audit (крупные списания без
 * депозита, операторы с непонятными списаниями), /affiliates (игроки бьют игры /
 * касса в минусе) и архетипа «Бонусник» в плюсе. Данные — /api/v1/risk/flags.
 * Роли: AUDIT_ROLES (director/finance/risk_officer/head_retention/super_admin).
 *
 * Клик по плитке вида фильтрует ленту и синхронизируется с URL (?kind=), а
 * бэкенд возвращает топ-200 выбранного вида — поэтому фильтр не «режет» уже
 * загруженную выборку, а перезапрашивает срез.
 */

type FlagKind =
  | "no_deposit_withdrawal"
  | "suspicious_operator"
  | "affiliate_players_win"
  | "affiliate_cash_drain"
  | "bonus_abuse";

const KINDS: readonly FlagKind[] = [
  "no_deposit_withdrawal",
  "suspicious_operator",
  "affiliate_players_win",
  "affiliate_cash_drain",
  "bonus_abuse",
];

interface KindMeta {
  emoji: string;
  labelKey: MessageKey;
  subKey: MessageKey;
  bg: string;
  fg: string;
}

// Цвета — только из существующей палитры бейджей (badges/lifecycle), новых нет.
const KIND_META: Record<FlagKind, KindMeta> = {
  no_deposit_withdrawal: {
    emoji: "💸",
    labelKey: "risk.flags.kind.no_deposit_withdrawal.label",
    subKey: "risk.flags.kind.no_deposit_withdrawal.sub",
    bg: "#fee2e2",
    fg: "#991b1b",
  },
  suspicious_operator: {
    emoji: "🕵️",
    labelKey: "risk.flags.kind.suspicious_operator.label",
    subKey: "risk.flags.kind.suspicious_operator.sub",
    bg: "#fef9c3",
    fg: "#854d0e",
  },
  affiliate_players_win: {
    emoji: "🔴",
    labelKey: "risk.flags.kind.affiliate_players_win.label",
    subKey: "risk.flags.kind.affiliate_players_win.sub",
    bg: "#dbeafe",
    fg: "#1e40af",
  },
  affiliate_cash_drain: {
    emoji: "📉",
    labelKey: "risk.flags.kind.affiliate_cash_drain.label",
    subKey: "risk.flags.kind.affiliate_cash_drain.sub",
    bg: "#f1f5f9",
    fg: "#475569",
  },
  bonus_abuse: {
    emoji: "🎁",
    labelKey: "risk.flags.kind.bonus_abuse.label",
    subKey: "risk.flags.kind.bonus_abuse.sub",
    bg: "#dcfce7",
    fg: "#166534",
  },
};

const SEV_EMOJI: Record<number, string> = { 3: "🔴", 2: "🟡", 1: "⚪" };
const ENTITY_KEY: Record<FlagRow["entity"], MessageKey> = {
  player: "risk.flags.entity.player",
  operator: "risk.flags.entity.operator",
  affiliate: "risk.flags.entity.affiliate",
};

interface FlagRow {
  kind: FlagKind;
  entity: "player" | "operator" | "affiliate";
  id: string | number;
  label: string;
  amount_try: number;
  count: number;
  severity: 1 | 2 | 3;
  href: string;
  details: Record<string, unknown>;
}

interface FlagsData {
  rows: FlagRow[];
  totals: { by_kind: Record<FlagKind, number>; total: number };
  kind: FlagKind | null;
  checked_at: string;
}

// ── URL ?kind= — читаем ТОЛЬКО после гидратации (SSR-HTML без kind разошёлся бы
// с первым клиентским рендером). useSyncExternalStore — гидрат-флаг без
// setState-в-effect (react-hooks strict, паттерн DeskScreen). ────────────────
const emptySubscribe = () => () => {};
const useHydrated = () => useSyncExternalStore(emptySubscribe, () => true, () => false);

// «Текущее время» как внешний стор: тик раз в минуту, getSnapshot кэширован
// (обновляется только подпиской) → чистый рендер без Date.now() в теле
// компонента (react-hooks/purity). Нужно для «проверено N мин назад».
let _nowMs = Date.now();
function subscribeMinute(cb: () => void): () => void {
  const id = setInterval(() => {
    _nowMs = Date.now();
    cb();
  }, 60000);
  return () => clearInterval(id);
}
const useNowMs = () => useSyncExternalStore(subscribeMinute, () => _nowMs, () => _nowMs);

function urlKind(): FlagKind | null {
  if (typeof window === "undefined") return null;
  const k = new URLSearchParams(window.location.search).get("kind");
  return k && (KINDS as readonly string[]).includes(k) ? (k as FlagKind) : null;
}

/** Записать/снять kind в URL без перезагрузки (board history.replaceState). */
function writeKindToUrl(kind: FlagKind | null): void {
  if (typeof window === "undefined") return;
  const qs = new URLSearchParams(window.location.search);
  if (kind) qs.set("kind", kind);
  else qs.delete("kind");
  const s = qs.toString();
  window.history.replaceState(null, "", s ? `${window.location.pathname}?${s}` : window.location.pathname);
}

export function FlagsScreen() {
  const t = useT();
  const hydrated = useHydrated();
  // override === undefined → следуем URL; иначе — явный выбор оператора.
  const [override, setOverride] = useState<FlagKind | null | undefined>(undefined);
  const kind: FlagKind | null = override !== undefined ? override : hydrated ? urlKind() : null;

  const path = kind ? `/api/v1/risk/flags?kind=${kind}` : "/api/v1/risk/flags";
  const { state, data, error, reload } = useFlaskData<FlagsData>(path);

  const toggleKind = (k: FlagKind) => {
    const next = kind === k ? null : k;
    writeKindToUrl(next);
    setOverride(next);
  };

  const byKind = data?.totals.by_kind;
  const total = data?.totals.total ?? 0;
  const tilesLoading = state === "loading" && !data;
  const allClear = state === "data" && !!data && total === 0;

  // «последняя проверка N мин назад» — из checked_at против стора-времени.
  const nowMs = useNowMs();
  const mins = data
    ? Math.max(0, Math.round((nowMs - new Date(data.checked_at).getTime()) / 60000))
    : 0;

  const rows = data?.rows ?? [];
  const tableState: TableState =
    state === "loading" ? "loading" : rows.length === 0 ? "empty" : "data";

  function detailsText(r: FlagRow): string {
    const d = r.details;
    if (r.kind === "no_deposit_withdrawal") {
      return t("risk.flags.details.no_deposit_withdrawal", {
        deposited: formatInt(Number(d.deposited ?? 0)),
        ops: formatInt(Number(d.ops ?? r.count)),
      });
    }
    if (r.kind === "suspicious_operator") {
      const base = t("risk.flags.details.suspicious_operator", {
        unclear: formatInt(Number(d.unclear_pct ?? 0)),
        ops: formatInt(Number(d.ops_count ?? r.count)),
      });
      return d.is_admin ? `${base} · ${t("risk.flags.details.adminBadge")}` : base;
    }
    if (r.kind === "bonus_abuse") {
      return t("risk.flags.details.bonus_abuse", {
        freespin: formatInt(Number(d.freespin_ratio ?? 0) * 100),
      });
    }
    // affiliate_players_win / affiliate_cash_drain
    return t("risk.flags.details.affiliate", {
      players: formatInt(Number(d.players ?? r.count)),
      ftd: formatInt(Number(d.ftd ?? 0)),
    });
  }

  const columns: Column<FlagRow>[] = [
    {
      key: "kind",
      header: t("risk.flags.col.kind"),
      align: "left",
      render: (r) => {
        const m = KIND_META[r.kind];
        return (
          <Badge bg={m.bg} fg={m.fg}>
            {m.emoji} {t(m.labelKey)}
          </Badge>
        );
      },
    },
    {
      key: "entity",
      header: t("risk.flags.col.entity"),
      align: "left",
      render: (r) => (
        <Link href={r.href} className="text-primary font-medium hover:underline">
          {t(ENTITY_KEY[r.entity], { id: String(r.id) })}
        </Link>
      ),
    },
    {
      key: "amount",
      header: t("risk.flags.col.amount"),
      mono: true,
      render: (r) => <span className="text-neg">{formatMoney(r.amount_try)}</span>,
    },
    {
      key: "severity",
      header: t("risk.flags.col.severity"),
      align: "left",
      render: (r) => (
        <span title={t(`risk.flags.sev.${r.severity}` as MessageKey)} className="cursor-help text-[15px]">
          {SEV_EMOJI[r.severity]}
        </span>
      ),
    },
    {
      key: "details",
      header: t("risk.flags.col.details"),
      align: "left",
      render: (r) => <span className="text-steel">{detailsText(r)}</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title={t("risk.flags.title")}
        accent={data ? `· ${formatInt(total)}` : undefined}
        lead={t("risk.flags.lead")}
        right={
          <PillRow>
            {data ? <Pill>{t("risk.flags.pill.total", { n: formatInt(total) })}</Pill> : null}
            {data ? (
              <Pill live>
                {mins === 0
                  ? t("risk.flags.pill.checkedNow")
                  : t("risk.flags.pill.checked", { mins: String(mins) })}
              </Pill>
            ) : null}
          </PillRow>
        }
      />

      {state === "error" ? (
        <div className="mt-6">
          <ErrorState
            title={t("risk.flags.error.title")}
            description={error ?? t("risk.flags.error.desc")}
            onRetry={reload}
          />
        </div>
      ) : (
        <>
          <div className="mt-[18px]">
            <SCardGrid className="lg:grid-cols-5">
              {KINDS.map((k) => {
                const m = KIND_META[k];
                const active = kind === k;
                return (
                  <button
                    key={k}
                    type="button"
                    className="text-left cursor-pointer"
                    onClick={() => toggleKind(k)}
                    title={t("risk.flags.tile.hint")}
                  >
                    <SCard
                      icon={m.emoji}
                      label={t(m.labelKey)}
                      value={byKind ? formatInt(byKind[k]) : "—"}
                      sub={active ? t("risk.flags.tile.active") : t(m.subKey)}
                      loading={tilesLoading}
                      className={active ? "ring-2 ring-primary" : undefined}
                    />
                  </button>
                );
              })}
            </SCardGrid>
          </div>

          <Banner>
            {t("risk.flags.banner.severity")}
            <br />
            {t("risk.flags.banner.sources")}
          </Banner>

          {kind ? (
            <ChipBar>
              <Chip active onClick={() => toggleKind(kind)}>
                {KIND_META[kind].emoji} {t(KIND_META[kind].labelKey)}
                {byKind ? ` (${formatInt(byKind[kind])})` : ""} ✕
              </Chip>
              <span className="text-[12.5px] text-steel">{t("risk.flags.filter.reset")}</span>
            </ChipBar>
          ) : null}

          {allClear ? (
            <div className="mt-4">
              <EmptyState
                title={t("risk.flags.empty.clear.title")}
                description={
                  mins === 0
                    ? t("risk.flags.empty.clear.descNow")
                    : t("risk.flags.empty.clear.desc", { mins: String(mins) })
                }
              />
            </div>
          ) : (
            <div className="mt-4 overflow-hidden rounded-card border border-hair bg-canvas">
              <DataTable
                columns={columns}
                rows={rows}
                state={tableState}
                getRowKey={(r) => `${r.kind}:${r.id}`}
                emptyTitle={t("risk.flags.empty.kind.title")}
                emptyDescription={t("risk.flags.empty.kind.desc")}
              />
            </div>
          )}
        </>
      )}
    </>
  );
}
