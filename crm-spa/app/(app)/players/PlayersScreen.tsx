"use client";

import { Suspense, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { flaskFetch } from "@/lib/api";
import {
  PageHeader,
  Panel,
  DataTable,
  Chip,
  ChipBar,
  Button,
  Input,
  Badge,
  LifecycleBadge,
  AccountTypeBadge,
  BeatsCasinoBadge,
  ErrorState,
  Modal,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useResource } from "@/components/money/kit";
import { useRole } from "@/lib/role-context";
import { useT, type MessageKey } from "@/lib/i18n";
import type { UserRole } from "@/lib/types";
import type { CampaignsResponse } from "@/components/marketing/types";
import { downloadSegment, DownloadError } from "./download";
import { BulkAssignBar } from "./BulkAssignBar";
import { removeFromOperator } from "@/components/queue/mutations";

/** Кто раздаёт игроков (зеркало ASSIGN_ROLES в AssignButton / api). */
const ASSIGN_ROLES = new Set<UserRole>(["super_admin", "head_retention", "head_department"]);

/**
 * /players — «Игроки» (agent F1, paritet со страницей / живого борда :8050).
 * Список всей базы: фильтры-чипсы (тип аккаунта / стадия / депозит / VIP /
 * кол-центр), поиск по ID, сортировка по колонкам, пагинация, метки 🎯
 * (обыгрывает казино) и 📤 (уже выгружен в кол-центр), экспорт сегмента CSV/XLSX.
 * Данные из /api/v1/players (api/players_analytics.py). Клик по строке →
 * карточка /players/<id> (B3).
 *
 * Drill-down фильтры seg/game/aff приходят из URL (кампании/игры/аффилиаты
 * линкуют сюда) — бэкенд их поддерживает в pb._players_filter (борд :1021-1034),
 * фронт читает их из useSearchParams и рисует баннер сегмента/игры (борд :1097-1106).
 */

const f = formatInt;

interface PlayerRow {
  player_id: number;
  lifecycle: string;
  is_depositor: boolean;
  bets: number;
  turnover: number;
  net: number;
  recency_days: number | null;
  dep_count: number;
  dep_sum: number;
  bonus_sum: number;
  distinct_games: number;
  churned_30d: boolean;
  account_type: string;
  net_cash: number;
  beats_casino: boolean;
  exported_at: string | null;
}

interface PlayersListData {
  items: PlayerRow[];
  total: number;
  page: number;
  per_page: number;
  has_next: boolean;
  sort: string;
  dir: string;
  filters: Record<string, string>;
  sorts: string[];
}

const LIFE_CHIPS: [string, MessageKey][] = [
  ["active", "players.chip.life.active"],
  ["cooling", "players.chip.life.cooling"],
  ["at_risk", "players.chip.life.at_risk"],
  ["dormant", "players.chip.life.dormant"],
  ["churned", "players.chip.life.churned"],
  ["never", "players.chip.life.never"],
];
const ACCT_CHIPS: [string, MessageKey][] = [
  ["normal", "players.chip.acct.normal"],
  ["service", "players.chip.acct.service"],
  ["test_or_service", "players.chip.acct.test_or_service"],
  ["blocked", "players.chip.acct.blocked"],
  ["all", "players.chip.acct.all"],
];
const DEP_CHIPS: [string, MessageKey][] = [
  ["yes", "players.chip.dep.yes"],
  ["no", "players.chip.dep.no"],
];
const VIP_CHIPS: [string, MessageKey, MessageKey][] = [
  ["1", "players.chip.vip.1.label", "players.chip.vip.1.title"],
  ["2", "players.chip.vip.2.label", "players.chip.vip.2.title"],
  ["3", "players.chip.vip.3.label", "players.chip.vip.3.title"],
  ["4", "players.chip.vip.4.label", "players.chip.vip.4.title"],
  ["5", "players.chip.vip.5.label", "players.chip.vip.5.title"],
];
const EXP_CHIPS: [string, MessageKey, MessageKey][] = [
  ["no", "players.chip.exp.no.label", "players.chip.exp.no.title"],
  ["yes", "players.chip.exp.yes.label", "players.chip.exp.yes.title"],
];

/** Roles that may pull the whole-segment export (mirror EXPORT_ROLES base). */
const EXPORT_UI_ROLES: readonly UserRole[] = [
  "super_admin",
  "head_retention",
  "head_department",
  "director",
  "finance",
];

/** Cream callout above the list (board .banner), with a reset link on the right.
 * Used for the seg/game drill-down banners (board player_board.py:1097-1106). */
function DrillCallout({ children, onReset }: { children: ReactNode; onReset: () => void }) {
  const t = useT();
  return (
    <div className="bg-cream border border-beige border-l-[3px] border-l-primary rounded-card px-[18px] py-[15px] text-[13.5px] leading-relaxed mb-3 flex items-center justify-between gap-3">
      <div>{children}</div>
      <button
        type="button"
        onClick={onReset}
        className="text-steel whitespace-nowrap hover:underline cursor-pointer flex-none"
      >
        {t("players.list.drillReset")}
      </button>
    </div>
  );
}

/** Segment banner — resolves the seg key to its icon/name/who/offer from
 * /api/v1/campaigns (same source as the campaigns cards). For roles without
 * marketing access the fetch 403s → we degrade to just the key. Board :1098-1102. */
function SegBanner({ segKey, onReset }: { segKey: string; onReset: () => void }) {
  const t = useT();
  const { data } = useResource<CampaignsResponse>("/api/v1/campaigns");
  const seg = data?.segments.find((s) => s.key === segKey);
  return (
    <DrillCallout onReset={onReset}>
      {seg ? (
        <>
          <span className="mr-1">{seg.icon}</span>
          <b>
            {t("players.list.segBanner.prefix")} {seg.name}
          </b>{" "}
          — {seg.who} · 💡 <b>{t("players.list.drillOffer")}</b> {seg.offer}
        </>
      ) : (
        <b>
          {t("players.list.segBanner.prefix")} {segKey}
        </b>
      )}
    </DrillCallout>
  );
}

/** Game banner — фильтр в URL это game_uuid (хеш), а для показа берём gname
 *  (имя игры), если пришло из ссылки; иначе показываем сам параметр (board :1103-1106). */
function GameBanner({ label, onReset }: { label: string; onReset: () => void }) {
  const t = useT();
  return (
    <DrillCallout onReset={onReset}>
      🎮 <b>{t("players.list.gameBanner.prefix")}</b> {label} · 💡{" "}
      <b>{t("players.list.drillOffer")}</b> {t("players.list.gameBanner.offer")}
    </DrillCallout>
  );
}

function PlayersScreenInner() {
  const t = useT();
  const me = useRole();
  const canExport = EXPORT_UI_ROLES.includes(me.role);
  const canAssign = ASSIGN_ROLES.has(me.role);

  // Массовое назначение (задача клиента): выбор пачки игроков чекбоксами.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const toggleOne = (pid: number) =>
    setSelected((s) => {
      const n = new Set(s);
      n.has(pid) ? n.delete(pid) : n.add(pid);
      return n;
    });
  const clearSelected = () => {
    setSelected(new Set());
    setSelectCap(null);
  };
  // «Выбрать всех по фильтру» — тянет id всей выборки (не только страницы) с
  // бэкенда и разом отмечает, чтобы раздать 100-300 игроков одним действием.
  const [selectingAll, setSelectingAll] = useState(false);
  const [selectCap, setSelectCap] = useState<number | null>(null); // сработал лимит → сколько показано

  // Drill-down фильтры приходят один раз из URL (seg/game/aff). Дальше живут в
  // state — сброс баннера чистит и state, и параметр в адресе (router.replace).
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const [qDraft, setQDraft] = useState("");
  const [q, setQ] = useState("");
  // Исключение игроков конкретного аффилиата (запрос клиента): вводится кодом,
  // применяется по той же кнопке «Найти». Бэкенд — pb._players_filter (?xaff=).
  const [xaffDraft, setXaffDraft] = useState("");
  const [xaff, setXaff] = useState("");
  const [at, setAt] = useState("normal");
  const [life, setLife] = useState("");
  const [dep, setDep] = useState("");
  const [vip, setVip] = useState("");
  const [exp, setExp] = useState("");
  const [seg, setSeg] = useState(() => searchParams.get("seg") ?? "");
  const [game, setGame] = useState(() => searchParams.get("game") ?? "");
  // gname — имя игры для баннера (game в фильтре это uuid-хеш, его показывать нельзя)
  const [gname] = useState(() => searchParams.get("gname") ?? "");
  const [aff, setAff] = useState(() => searchParams.get("aff") ?? "");
  const [sort, setSort] = useState("turnover");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);

  const [exporting, setExporting] = useState<"csv" | "xlsx" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const exportQuery = useMemo(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    p.set("at", at);
    if (life) p.set("life", life);
    if (dep) p.set("dep", dep);
    if (vip) p.set("vip", vip);
    if (exp) p.set("exp", exp);
    // drill-down фильтры — в списке И в экспорте (борд expq :1107)
    if (seg) p.set("seg", seg);
    if (game) p.set("game", game);
    if (aff) p.set("aff", aff);
    if (xaff) p.set("xaff", xaff);
    return p.toString();
  }, [q, at, life, dep, vip, exp, seg, game, aff, xaff]);

  const path = useMemo(() => {
    const p = new URLSearchParams(exportQuery);
    p.set("sort", sort);
    p.set("dir", dir);
    if (page) p.set("p", String(page));
    return `/api/v1/players?${p.toString()}`;
  }, [exportQuery, sort, dir, page]);

  const { state, data, error, reload } = useResource<PlayersListData>(path);

  /** Drop a drill-down param (seg/game/aff): clear the filter and strip it from
   * the URL so a refresh doesn't bring it back. */
  function clearDrill(key: "seg" | "game" | "aff", set: (v: string) => void) {
    set("");
    setPage(0);
    const next = new URLSearchParams(searchParams.toString());
    next.delete(key);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  function toggle(cur: string, key: string, set: (v: string) => void) {
    set(cur === key ? "" : key);
    setPage(0);
  }
  function submitSearch(e: FormEvent) {
    e.preventDefault();
    setQ(qDraft.trim());
    setXaff(xaffDraft.trim());
    setPage(0);
  }
  function toggleSort(col: string) {
    const nd = sort === col && dir === "desc" ? "asc" : "desc";
    setSort(col);
    setDir(nd);
    setPage(0);
  }
  function sortHead(label: string, col: string): ReactNode {
    const on = sort === col;
    const arrow = on ? (dir === "desc" ? " ▾" : " ▴") : "";
    return (
      <button
        type="button"
        onClick={() => toggleSort(col)}
        className="inline-flex items-center gap-0.5 cursor-pointer hover:text-primary uppercase tracking-[0.5px]"
      >
        {label}
        {arrow}
      </button>
    );
  }
  async function runExport(fmt: "csv" | "xlsx") {
    setExportError(null);
    setExporting(fmt);
    try {
      await downloadSegment(fmt, exportQuery);
    } catch (err) {
      if (err instanceof DownloadError) {
        setExportError(
          err.code === "forbidden"
            ? t("players.list.export.forbidden")
            : t("players.list.export.httpError", { status: err.status }),
        );
      } else {
        setExportError(t("players.list.exportError"));
      }
    } finally {
      setExporting(null);
    }
  }

  async function selectAllByFilter() {
    setSelectingAll(true);
    try {
      const res = await flaskFetch<{ ids: number[]; total: number; capped: boolean; cap: number }>(
        `/api/v1/players/ids?${exportQuery}&sort=${sort}&dir=${dir}`,
      );
      setSelected(new Set(res.ids));
      setSelectCap(res.capped ? res.cap : null);
    } catch {
      // молча — выбор не меняется, кнопка вернётся в исходное
    } finally {
      setSelectingAll(false);
    }
  }

  const columns: Column<PlayerRow>[] = [
    {
      key: "id",
      header: "ID",
      id: true,
      render: (r) => (
        <>
          {r.player_id}
          <AccountTypeBadge type={r.account_type} />
          {r.beats_casino ? (
            <>
              {" "}
              <BeatsCasinoBadge />
            </>
          ) : null}
          {r.exported_at ? (
            <>
              {" "}
              <Badge bg="#e0e7ff" fg="#4338ca" title={t("players.list.exportedTitle")}>
                📤 {r.exported_at}
              </Badge>
            </>
          ) : null}
        </>
      ),
    },
    { key: "life", header: t("players.list.col.stage"), align: "left", render: (r) => <LifecycleBadge stage={r.lifecycle} /> },
    { key: "bets", header: sortHead(t("players.list.col.bets"), "bets"), mono: true, render: (r) => f(r.bets) },
    { key: "turnover", header: sortHead(t("players.list.col.turnover"), "turnover"), mono: true, render: (r) => f(r.turnover) },
    {
      key: "net",
      header: sortHead("Net", "net"),
      mono: true,
      render: (r) => <span className={r.net < 0 ? "text-neg" : "text-pos"}>{f(r.net)}</span>,
    },
    {
      key: "recency",
      header: sortHead("Recency", "recency_days"),
      mono: true,
      render: (r) =>
        r.recency_days == null ? "—" : `${f(r.recency_days)}${t("players.list.daysShort")}`,
    },
    { key: "dep_count", header: t("players.list.col.dep"), mono: true, render: (r) => f(r.dep_count) },
    { key: "dep_sum", header: sortHead(t("players.list.col.depSum"), "dep_sum"), mono: true, render: (r) => f(r.dep_sum) },
    { key: "bonus_sum", header: sortHead(t("players.list.col.bonusSum"), "bonus_sum"), mono: true, render: (r) => f(r.bonus_sum) },
    { key: "games", header: t("players.list.col.games"), mono: true, render: (r) => f(r.distinct_games) },
    {
      key: "churn",
      header: t("players.list.col.churn"),
      mono: true,
      render: (r) => (r.churned_30d ? "🔴" : "·"),
    },
  ];

  const items = data?.items ?? [];

  // «Видно, у кого уже есть оператор» (запрос клиента): подгружаем назначения
  // текущей страницы из crm.player_assignments (RLS: super_admin/head_retention —
  // все, head_department — по своему отделу) + имена операторов. Ключ по id
  // страницы, чтобы не дёргать на каждый ре-рендер.
  const [assigns, setAssigns] = useState<Map<number, { id: string; name: string }[]>>(new Map());
  // Бамп → перезагрузить назначения колонки после массового назначения/отвязки
  // (id страницы не меняются, поэтому нужен явный триггер).
  const [assignsNonce, setAssignsNonce] = useState(0);
  // Игрок + оператор, которого отвязываем (подтверждение перед удалением привязки).
  const [pendingUnassign, setPendingUnassign] = useState<
    { playerId: number; operatorId: string; name: string } | null
  >(null);
  const [unassigning, setUnassigning] = useState(false);
  const idsKey = items.map((r) => r.player_id).join(",");
  useEffect(() => {
    if (!canAssign || items.length === 0) {
      setAssigns(new Map());
      return;
    }
    let cancelled = false;
    const ids = items.map((r) => r.player_id);
    (async () => {
      const sb = createClient().schema("crm");
      const { data: rows } = await sb
        .from("player_assignments")
        .select("casino_player_id, operator_id")
        .in("casino_player_id", ids);
      const opIds = [...new Set((rows ?? []).map((r) => r.operator_id as string))];
      const nameById = new Map<string, string>();
      if (opIds.length) {
        const { data: users } = await sb
          .from("crm_users")
          .select("id, full_name")
          .in("id", opIds);
        (users ?? []).forEach((u) => nameById.set(u.id as string, u.full_name as string));
      }
      const m = new Map<number, { id: string; name: string }[]>();
      (rows ?? []).forEach((r) => {
        const pid = r.casino_player_id as number;
        const opId = r.operator_id as string;
        const arr = m.get(pid) ?? [];
        arr.push({ id: opId, name: nameById.get(opId) ?? "—" });
        m.set(pid, arr);
      });
      if (!cancelled) setAssigns(m);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, canAssign, assignsNonce]);

  // Отвязать оператора от игрока (запрос клиента). removeFromOperator удаляет
  // привязку под RLS (assign_delete: super_admin/главы) + пишет audit. Локально
  // убираем бейдж без перезагрузки страницы.
  async function doUnassign() {
    if (!pendingUnassign) return;
    const { playerId, operatorId } = pendingUnassign;
    setUnassigning(true);
    const res = await removeFromOperator({ actorId: me.id, operatorId, playerIds: [playerId] });
    setUnassigning(false);
    if (res.ok) {
      setAssigns((prev) => {
        const n = new Map(prev);
        const arr = (n.get(playerId) ?? []).filter((o) => o.id !== operatorId);
        if (arr.length) n.set(playerId, arr);
        else n.delete(playerId);
        return n;
      });
      setPendingUnassign(null);
    }
  }

  // Колонка «Оператор» — кто уже назначен + «×» отвязать (для раздающих игроков).
  const assignColumn: Column<PlayerRow> = {
    key: "_assignee",
    header: t("players.list.col.operator"),
    align: "left",
    sortable: false,
    render: (r) => {
      const ops = assigns.get(r.player_id);
      if (!ops || ops.length === 0) return <span className="text-steel">—</span>;
      return (
        <span className="inline-flex flex-wrap gap-1">
          {ops.map((o) => (
            <span
              key={o.id}
              className="inline-flex items-center gap-1 rounded-full bg-[#dcfce7] pl-2 pr-1 py-0.5 text-[12px] font-medium text-[#15803d]"
            >
              {o.name}
              <button
                type="button"
                title={t("players.assign.unassign")}
                aria-label={t("players.assign.unassign")}
                onClick={(e) => {
                  e.stopPropagation();
                  setPendingUnassign({ playerId: r.player_id, operatorId: o.id, name: o.name });
                }}
                className="flex h-4 w-4 items-center justify-center rounded-full text-[#15803d] hover:bg-[#bbf7d0] cursor-pointer"
              >
                ×
              </button>
            </span>
          ))}
        </span>
      );
    },
  };

  // Чекбокс-колонка для массового назначения (только раздающим игроков).
  const allOnPage = items.length > 0 && items.every((r) => selected.has(r.player_id));
  const selectColumn: Column<PlayerRow> = {
    key: "_sel",
    header: (
      <input
        type="checkbox"
        aria-label={t("players.bulk.selectAll")}
        checked={allOnPage}
        onChange={() =>
          setSelected((s) => {
            const n = new Set(s);
            if (allOnPage) items.forEach((r) => n.delete(r.player_id));
            else items.forEach((r) => n.add(r.player_id));
            return n;
          })
        }
      />
    ),
    align: "left",
    sortable: false,
    render: (r) => (
      <input
        type="checkbox"
        checked={selected.has(r.player_id)}
        onClick={(e) => e.stopPropagation()}
        onChange={() => toggleOne(r.player_id)}
      />
    ),
  };
  // Для раздающих: чекбокс + ID + «Оператор» + остальное; прочим — как было.
  const gridColumns = canAssign
    ? [selectColumn, columns[0], assignColumn, ...columns.slice(1)]
    : columns;
  const tableState = state === "loading" && !data ? "loading" : items.length ? "data" : "empty";
  const total = data?.total ?? 0;
  const per = data?.per_page ?? 50;

  return (
    <>
      <PageHeader
        title={t("players.list.title")}
        accent={`· ${data ? f(total) : "…"}`}
        lead={t("players.list.lead")}
      />

      {/* баннеры активного сегмента / игры (борд :1097-1106) */}
      {seg || game ? (
        <div className="mt-4">
          {seg ? <SegBanner segKey={seg} onReset={() => clearDrill("seg", setSeg)} /> : null}
          {game ? <GameBanner label={gname || game} onReset={() => clearDrill("game", setGame)} /> : null}
        </div>
      ) : null}

      {/* поиск + тип аккаунта */}
      <form onSubmit={submitSearch} className="mt-5 flex flex-wrap items-center gap-2">
        <Input
          value={qDraft}
          onChange={(e) => setQDraft(e.target.value)}
          placeholder={t("players.list.searchPlaceholder")}
          className="w-[170px]"
        />
        <Input
          value={xaffDraft}
          onChange={(e) => setXaffDraft(e.target.value)}
          placeholder={t("players.list.excludeAffPlaceholder")}
          title={t("players.list.excludeAffTitle")}
          className="w-[150px]"
        />
        <Button type="submit">{t("players.list.find")}</Button>
        <span className="ml-2 text-steel text-[12.5px]">{t("players.list.typeLabel")}</span>
        {ACCT_CHIPS.map(([k, labelKey]) => (
          <Chip
            key={k}
            active={at === k}
            onClick={() => {
              setAt(k);
              setPage(0);
            }}
          >
            {t(labelKey)}
          </Chip>
        ))}
      </form>

      {/* стадия / депозит / VIP / кол-центр + экспорт */}
      <ChipBar className="items-center">
        <span className="text-steel text-[12.5px]">{t("players.list.stageLabel")}</span>
        {LIFE_CHIPS.map(([k, labelKey]) => (
          <Chip key={k} active={life === k} onClick={() => toggle(life, k, setLife)}>
            {t(labelKey)}
          </Chip>
        ))}
        {DEP_CHIPS.map(([k, labelKey]) => (
          <Chip key={k} active={dep === k} onClick={() => toggle(dep, k, setDep)}>
            {t(labelKey)}
          </Chip>
        ))}
        <span className="ml-2 text-steel text-[12.5px]">{t("players.list.vipLabel")}</span>
        {VIP_CHIPS.map(([k, labelKey, titleKey]) => (
          <Chip key={k} active={vip === k} title={t(titleKey)} onClick={() => toggle(vip, k, setVip)}>
            {t(labelKey)}
          </Chip>
        ))}
        <span className="ml-2 text-steel text-[12.5px]">{t("players.list.callCenterLabel")}</span>
        {EXP_CHIPS.map(([k, labelKey, titleKey]) => (
          <Chip key={k} active={exp === k} title={t(titleKey)} onClick={() => toggle(exp, k, setExp)}>
            {t(labelKey)}
          </Chip>
        ))}
        {canExport ? (
          <span className="ml-auto flex items-center gap-1.5">
            <span className="text-steel text-[12.5px]" title={t("players.list.exportSegmentTitle")}>
              {t("players.list.exportSegmentLabel")}
            </span>
            <Button size="sm" variant="ghost" loading={exporting === "csv"} onClick={() => runExport("csv")}>
              ⬇ CSV
            </Button>
            <Button size="sm" variant="ghost" loading={exporting === "xlsx"} onClick={() => runExport("xlsx")}>
              ⬇ Excel
            </Button>
          </span>
        ) : null}
      </ChipBar>

      {exportError ? <p className="mb-3 text-[13px] text-neg">{exportError}</p> : null}

      {state === "error" && !data ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          {canAssign ? (
            <div className="mb-3 flex flex-wrap items-center gap-2 text-[13px]">
              <Button size="sm" variant="ghost" loading={selectingAll} onClick={selectAllByFilter}>
                {t("players.bulk.selectAllFilter", { n: f(total) })}
              </Button>
              {selected.size > 0 ? (
                <>
                  <span className="text-steel">{t("players.bulk.selected", { n: selected.size })}</span>
                  <button
                    type="button"
                    className="text-steel hover:underline cursor-pointer"
                    onClick={clearSelected}
                  >
                    {t("players.bulk.clear")}
                  </button>
                </>
              ) : null}
              {selectCap != null ? (
                <span className="text-[12.5px] text-amber-700">
                  {t("players.bulk.capped", { cap: f(selectCap) })}
                </span>
              ) : null}
            </div>
          ) : null}
          {canAssign && selected.size > 0 ? (
            <BulkAssignBar
              playerIds={[...selected]}
              onClear={clearSelected}
              onDone={() => {
                clearSelected();
                setAssignsNonce((n) => n + 1); // обновить колонку «Оператор»
                reload();
              }}
            />
          ) : null}
          <Panel>
            <DataTable
              columns={gridColumns}
              rows={items}
              getRowKey={(r) => r.player_id}
              getRowHref={(r) => `/players/${r.player_id}`}
              state={tableState}
              emptyTitle={t("players.list.emptyTitle")}
              emptyDescription={t("players.list.emptyDescription")}
            />
          </Panel>

          <div className="mt-4 flex items-center justify-center gap-4 text-[13px] text-steel">
            <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
              {t("players.list.prev")}
            </Button>
            <span className="font-mono">
              {total
                ? t("players.list.range", {
                    from: page * per + 1,
                    to: Math.min((page + 1) * per, total),
                    total: f(total),
                  })
                : "—"}
            </span>
            <Button
              size="sm"
              variant="ghost"
              disabled={!data?.has_next}
              onClick={() => setPage((p) => p + 1)}
            >
              {t("players.list.next")}
            </Button>
          </div>
        </>
      )}

      {/* Подтверждение отвязки оператора от игрока */}
      <Modal
        open={pendingUnassign != null}
        onClose={() => setPendingUnassign(null)}
        title={t("players.assign.unassignTitle")}
        widthClass="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingUnassign(null)}>
              {t("ui.cancel")}
            </Button>
            <Button variant="brand" loading={unassigning} onClick={doUnassign}>
              {t("players.assign.unassign")}
            </Button>
          </>
        }
      >
        <div className="text-[13.5px] text-slate">
          {pendingUnassign
            ? t("players.assign.unassignBody", {
                name: pendingUnassign.name,
                id: pendingUnassign.playerId,
              })
            : null}
        </div>
      </Modal>
    </>
  );
}

/** useSearchParams requires a Suspense boundary in the App Router; page.tsx is
 * owned elsewhere, so we wrap here (mirrors app/(auth)/login/page.tsx). */
export function PlayersScreen() {
  return (
    <Suspense fallback={null}>
      <PlayersScreenInner />
    </Suspense>
  );
}
