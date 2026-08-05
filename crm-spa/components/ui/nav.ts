/**
 * Sidebar navigation structure — ported from player_board.py NAVITEMS, grouped,
 * plus the operational (call-center) and admin sections the SPA adds.
 *
 * Role gating is REAL here (implemented by B1, as invited by A2's original stub
 * comment): every item carries a `roles` allow-list built from SPA_BUILD_PLAN.md
 * §1 (the 14-role matrix). AppShell filters items through `canSee(item, role)`.
 * Items without `roles` stay visible to everyone (back-compat for /dev/ui).
 *
 * Menu visibility is a UX convenience only — the hard boundary is RLS in the DB
 * plus the Flask JWT role checks (plan §0.4). Never rely on hidden items.
 */

import type { UserRole } from "@/lib/types";
import type { MessageKey } from "@/lib/i18n";

export interface NavItem {
  key: string;
  href: string;
  /** Emoji fallback when there is no ported line icon for this key. */
  emoji: string;
  /** i18n key ("nav.*") — translated at the render point (AppShell / page.tsx launcher). */
  label: MessageKey;
  /** When set, only these roles see the item. */
  roles?: UserRole[];
}

export interface NavGroup {
  /** i18n key ("nav.group.*") — translated at the render point (AppShell). */
  title: MessageKey;
  /**
   * Optional section super-heading ("nav.section.*") rendered ABOVE this group's
   * title — a lightweight divider that visually clusters several groups into one
   * module band (Вход / Расширение / Ядро / Слой). Groups without it visually
   * belong to the section opened by the nearest preceding group that has one.
   */
  section?: MessageKey;
  items: NavItem[];
}

// ---- Reusable role sets (keep the matrix readable & single-sourced) ----
/** Do operational call-center work (own/dept players): queue, calendar. */
const OPS: UserRole[] = [
  "operator",
  "vip_manager",
  "head_department",
  "head_retention",
  "super_admin",
];
/** Retention control surfaces (desk / dept report). */
const DESK: UserRole[] = [
  "head_retention",
  "head_department",
  "super_admin",
  "director",
];
/** General analytics readers (cohorts, LTV, RFM, games, ...). */
const ANALYSTS: UserRole[] = [
  "super_admin",
  "head_retention",
  "director",
  "analyst",
  "marketing_manager",
];
/** Money surfaces (GGR, cash, withdrawals audit). */
const MONEY: UserRole[] = [
  "super_admin",
  "head_retention",
  "director",
  "finance",
  "analyst",
];
/**
 * Call-analysis module (call_analyzer_interface_spec_FINAL.md §9). Роли зеркалят
 * require_auth(roles=...) в api/call_analysis.py, чтобы не было «мёртвых» пунктов
 * меню (пункт виден ⇔ API отдаёт данные). Разбивка по экранам ниже.
 */
/** Обзор (§10.1, R_OVERVIEW): руководители + аналитик + админ. */
const CA_OVERVIEW: UserRole[] = ["head_department", "head_retention", "analyst", "super_admin"];
/** Очередь/покрытие (§10.2/§10.7, R_QUEUE/R_COVERAGE): руководители + админ (без аналитика). */
const CA_MANAGE: UserRole[] = ["head_department", "head_retention", "super_admin"];
/** Что работает (§10.6, R_WHATWORKS): глава ретеншена + админ. */
const CA_WHATWORKS: UserRole[] = ["head_retention", "super_admin"];
/** Мои звонки (§10.10, R_MYCARDS): оператор/vip — их собственный экран. */
const CA_OPERATOR: UserRole[] = ["operator", "vip_manager"];
/** Скрипт (§10.8/§10.9, R_SCRIPT_GET): глава ретеншена, админ + операторы (read-only TR). */
const CA_SCRIPT: UserRole[] = ["head_retention", "super_admin", "operator", "vip_manager"];
/** Сводка (§10.12, R_SUMMARY): владелец + глава ретеншена + админ. */
const CA_SUMMARY: UserRole[] = ["director", "head_retention", "super_admin"];
/** Marketing / bonus economy. */
const MARKETING: UserRole[] = [
  "super_admin",
  "head_retention",
  "director",
  "marketing_manager",
];
/** Everyone with an internal seat (excludes external affiliate). */
const INTERNAL: UserRole[] = [
  "super_admin",
  "director",
  "head_retention",
  "head_department",
  "operator",
  "vip_manager",
  "affiliate_manager",
  "marketing_manager",
  "analyst",
  "finance",
  "risk_officer",
  "support",
  "viewer",
];

/**
 * Меню перестроено в 7 смысловых модулей (ТЗ этапа 1). Ни один key/href/roles не
 * изменился — поменялась только ГРУППИРОВКА. Модули собраны в 4 секции-полосы
 * через опциональное поле `section` (см. NavGroup) — рендерит AppShell.
 *
 * Секция «Вход»  → Трафик и аффилиаты · VIP-радар
 * Секция «Расширение» → Бонус-экономика · Риск и фрод
 * Секция «Ядро»  → Retention-автоматизация (+ подгруппа «Анализ звонков»)
 * Секция «Слой / фундамент» → Аналитика · Данные / API
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    // Модуль 1 — Трафик и аффилиаты. Открывает секцию «Вход».
    section: "nav.section.entry",
    title: "nav.group.traffic",
    items: [
      { key: "affiliates", href: "/affiliates", emoji: "🤝", label: "nav.affiliates", roles: ["super_admin", "head_retention", "director", "affiliate_manager", "finance", "analyst"] },
      { key: "verdicts", href: "/verdicts", emoji: "🔮", label: "nav.verdicts", roles: ["super_admin", "head_retention", "director", "affiliate_manager", "finance", "analyst"] },
      { key: "channels", href: "/channels", emoji: "📡", label: "nav.channels", roles: ANALYSTS },
      { key: "affiliate_cabinet", href: "/affiliate", emoji: "🧩", label: "nav.affiliateCabinet", roles: ["affiliate"] },
    ],
  },
  {
    // Модуль 2 — VIP-радар (в секции «Вход», без своего заголовка секции).
    title: "nav.group.vip",
    items: [
      { key: "ltv", href: "/ltv", emoji: "💎", label: "nav.ltv", roles: ANALYSTS },
      { key: "dist", href: "/dist", emoji: "📐", label: "nav.dist", roles: ANALYSTS },
      { key: "vip-risk", href: "/vip-risk", emoji: "💠", label: "nav.vipRisk", roles: DESK },
      // Пресет Пульта: те же данные /desk, отфильтрованные до китов C/D (W2-T4).
      { key: "vip-queue", href: "/desk?act=SAVE&tier=cd", emoji: "🐋", label: "nav.vipQueue", roles: DESK },
    ],
  },
  {
    // Модуль 3 — Бонус-экономика. Открывает секцию «Расширение».
    section: "nav.section.expand",
    title: "nav.group.bonuseco",
    items: [
      { key: "bonus", href: "/bonus", emoji: "🎁", label: "nav.bonus", roles: [...MARKETING, "analyst", "head_department"] },
      { key: "bonuses", href: "/bonuses", emoji: "🎯", label: "nav.bonuses", roles: [...MARKETING, "analyst"] },
      { key: "campaigns", href: "/campaigns", emoji: "📣", label: "nav.campaigns", roles: MARKETING },
      // Бонусная часть «Денег» (ТЗ §3.3.2): прямой вход в бонус-вкладку GGR (W2-T5).
      { key: "ggr-bonus", href: "/ggr#bonus", emoji: "💸", label: "nav.ggrBonus", roles: MONEY },
    ],
  },
  {
    // Модуль 4 — Риск и фрод (в секции «Расширение»). Аудит выводов — тот же /audit.
    title: "nav.group.risk",
    items: [
      { key: "risk", href: "/audit", emoji: "🚨", label: "nav.risk", roles: ["super_admin", "head_retention", "director", "finance", "risk_officer"] },
      { key: "flags", href: "/flags", emoji: "🚩", label: "nav.flags", roles: ["super_admin", "head_retention", "director", "finance", "risk_officer"] },
    ],
  },
  {
    // Модуль 5 — Retention-автоматизация. Открывает секцию «Ядро».
    section: "nav.section.core",
    title: "nav.group.core",
    items: [
      { key: "players", href: "/players", emoji: "👥", label: "nav.players", roles: ["super_admin", "head_retention", "director", "head_department", "analyst", "finance", "marketing_manager", "affiliate_manager", "risk_officer", "support", "vip_manager", "viewer"] },
      { key: "desk", href: "/desk", emoji: "🎛", label: "nav.desk", roles: DESK },
      { key: "queue", href: "/queue", emoji: "📞", label: "nav.queue", roles: OPS },
      { key: "calendar", href: "/calendar", emoji: "🗓", label: "nav.calendar", roles: OPS },
      { key: "live", href: "/live", emoji: "🔴", label: "nav.live", roles: ["super_admin", "head_retention", "director", "analyst", "marketing_manager"] },
      { key: "report", href: "/report", emoji: "📑", label: "nav.report", roles: DESK },
      { key: "actions", href: "/actions", emoji: "🎯", label: "nav.actions", roles: [...MARKETING, "analyst"] },
      // Конструктор сегментов (W4-T2). Роли как у actions (READ_ROLES api/segments.py — тот же круг).
      { key: "segments", href: "/segments", emoji: "🧩", label: "nav.segments", roles: [...MARKETING, "analyst"] },
      // Конструктор цепочек (W4-T5). Роли как у segments (READ_ROLES api/chains.py — тот же круг).
      { key: "chains", href: "/chains", emoji: "🔗", label: "nav.chains", roles: [...MARKETING, "analyst"] },
      { key: "games", href: "/games", emoji: "🎮", label: "nav.games", roles: ANALYSTS },
      { key: "exports", href: "/exports", emoji: "📋", label: "nav.exports", roles: ["super_admin", "head_retention", "head_department", "affiliate_manager"] },
    ],
  },
  {
    // Подгруппа модуля 5 — «Анализ звонков» (§9). БЕЗ section: визуально остаётся
    // внутри секции «Ядро» как подзаголовок. Пункт виден ровно тем ролям, которым
    // его API отдаёт данные (см. CA_* выше); role-наборы не тронуты.
    title: "calls.nav.group",
    items: [
      { key: "ca_overview", href: "/call-analysis", emoji: "📊", label: "calls.nav.overview", roles: CA_OVERVIEW },
      { key: "ca_queue", href: "/call-analysis/queue", emoji: "✅", label: "calls.nav.queue", roles: CA_MANAGE },
      { key: "ca_coverage", href: "/call-analysis/coverage", emoji: "📞", label: "calls.nav.coverage", roles: CA_MANAGE },
      { key: "ca_what_works", href: "/call-analysis/what-works", emoji: "💡", label: "calls.nav.whatWorks", roles: CA_WHATWORKS },
      { key: "ca_my", href: "/call-analysis/my", emoji: "🎧", label: "calls.nav.my", roles: CA_OPERATOR },
      { key: "ca_script", href: "/call-analysis/script", emoji: "📝", label: "calls.nav.script", roles: CA_SCRIPT },
      { key: "ca_summary", href: "/call-analysis/summary", emoji: "📄", label: "calls.nav.summary", roles: CA_SUMMARY },
      { key: "ca_verdict", href: "/call-analysis/verdict", emoji: "🔓", label: "calls.nav.verdict", roles: ["super_admin"] },
    ],
  },
  {
    // Модуль 6 — Аналитика. Открывает секцию «Слой / фундамент».
    // «Обзор» тянет казино-деньги (GGR/NGR) из /api/v1/money/overview → тот же круг,
    // что CASINO_MONEY_ROLES в api/money.py (без marketing/affiliate_manager/risk/
    // viewer — им API отдаёт 403). Держим 1-в-1, чтобы не было «мёртвых» пунктов меню.
    section: "nav.section.layer",
    title: "nav.group.analytics",
    items: [
      // Revenue Autopilot (SaaS-пресет): отчёт «где утекает выручка» (REBUILD §2).
      // Роли = LEAK_ROLES в api/saas.py (ANALYSTS + finance, как segmentation).
      { key: "leak-audit", href: "/leak-audit", emoji: "💸", label: "nav.leakAudit", roles: [...ANALYSTS, "finance"] },
      { key: "uplift", href: "/uplift", emoji: "📈", label: "nav.uplift", roles: [...ANALYSTS, "finance"] },
      { key: "overview", href: "/overview", emoji: "📊", label: "nav.overview", roles: MONEY },
      // Конструктор отчётов (W5-T4). Роли = REPORT_ROLES в api/reports.py (1:1):
      // MONEY (super_admin/head_retention/director/finance/analyst) + marketing_manager.
      { key: "reports", href: "/reports", emoji: "📑", label: "nav.reports", roles: [...MONEY, "marketing_manager"] },
      { key: "analytics", href: "/analytics", emoji: "📈", label: "nav.analytics", roles: ["super_admin", "head_retention", "director", "analyst", "finance", "marketing_manager"] },
      { key: "funnel", href: "/funnel", emoji: "🫗", label: "nav.funnel", roles: ANALYSTS },
      { key: "rfm", href: "/rfm", emoji: "🎯", label: "nav.rfm", roles: ANALYSTS },
      { key: "cohorts", href: "/cohorts", emoji: "🧩", label: "nav.cohorts", roles: ANALYSTS },
      { key: "archetypes", href: "/archetypes", emoji: "🧬", label: "nav.archetypes", roles: ANALYSTS },
      { key: "ggr", href: "/ggr", emoji: "📈", label: "nav.ggr", roles: MONEY },
      { key: "cash", href: "/analytics#cash", emoji: "💰", label: "nav.cash", roles: MONEY },
    ],
  },
  {
    // Модуль 7 — Данные / API (в секции «Слой / фундамент»).
    title: "nav.group.data",
    items: [
      { key: "schema", href: "/schema", emoji: "🗺", label: "nav.schema", roles: ["super_admin", "head_retention", "director", "analyst", "finance", "marketing_manager", "affiliate_manager"] },
      { key: "formulas", href: "/formulas", emoji: "📐", label: "nav.formulas", roles: ["super_admin", "head_retention", "director", "analyst", "finance", "marketing_manager", "affiliate_manager"] },
      { key: "glossary", href: "/glossary", emoji: "📖", label: "nav.glossary", roles: INTERNAL },
      { key: "signals", href: "/signals", emoji: "🧠", label: "nav.signals", roles: ["super_admin", "head_retention", "director", "risk_officer", "marketing_manager", "analyst"] },
      { key: "keys", href: "/keys", emoji: "🔑", label: "nav.keys", roles: ["super_admin"] },
      { key: "extensions", href: "/extensions", emoji: "☎️", label: "nav.extensions", roles: ["super_admin", "head_retention", "head_department"] },
      { key: "users", href: "/admin/users", emoji: "👤", label: "nav.users", roles: ["super_admin", "head_retention", "head_department"] },
    ],
  },
];

/** Role-gated visibility check. Items without `roles` are visible to all. */
export function canSee(item: NavItem, role?: string): boolean {
  if (!item.roles || item.roles.length === 0) return true;
  if (!role) return false;
  return item.roles.includes(role as UserRole);
}

/**
 * Map a pathname to the active nav key (for AppShell highlighting).
 * Exact href match wins; otherwise the longest href that prefixes the path
 * (so /player/808 → "players", /admin/users/… → "users"). "/" → players.
 */
export function activeKeyForPath(pathname: string): string | undefined {
  const items = NAV_GROUPS.flatMap((g) => g.items);

  if (pathname === "/") return undefined;   // главная = дашборд, не подсвечиваем пункты

  // exact match on the path portion of href (ignore hash)
  const exact = items.find((it) => it.href.split("#")[0] === pathname);
  if (exact) return exact.key;

  // longest non-root prefix match
  let best: NavItem | undefined;
  for (const it of items) {
    const href = it.href.split("#")[0];
    if (href !== "/" && pathname.startsWith(`${href}/`)) {
      if (!best || href.length > best.href.split("#")[0].length) best = it;
    }
  }
  return best?.key;
}
