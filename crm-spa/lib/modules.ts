/**
 * Отключение модулей/пунктов меню (правка Васи — «возможность отключать модули
 * в меню»). Позволяет к запуску спрятать недоделанные модули, не удаляя код.
 *
 * Ключи берутся из components/ui/nav.ts:
 *   • item.key       — один пункт (напр. "reports", "ca_overview", "cohorts");
 *   • group.title    — целый модуль/группа (напр. "nav.group.analytics",
 *                      "calls.nav.group").
 * Отключённое прячется и из сайдбара (AppShell), и из лаунчера (app/(app)/page).
 *
 * Два источника (объединяются):
 *   1. STATIC_DISABLED ниже — правится в коде + редеплой;
 *   2. env NEXT_PUBLIC_DISABLED_MODULES="reports,calls.nav.group" — правится в
 *      .env без правки кода (инлайнится при сборке).
 *
 * ВАЖНО: это UX-скрытие, НЕ граница безопасности. Доступ по-прежнему режут RLS
 * в БД и проверки ролей во Flask (как и role-гейтинг nav). Отключённый модуль,
 * открытый по прямому URL, всё равно упрётся в API-гейт.
 */

// SaaS-пресет Revenue Autopilot (REBUILD-TASK.md §2): казино-модули выключены
// флагами, код не удаляется. /pool в меню отсутствует (доступен только прямым
// URL) — на nav-уровне скрывать нечего.
const STATIC_DISABLED: readonly string[] = [
  "games",
  "ggr",
  "ggr-bonus",
  "vip-risk",
  "vip-queue",
  "affiliates",
  "verdicts",
  "affiliate_cabinet",
  "risk",
  "live",
  "calls.nav.group",
  // Фидбек владельца «куча кнопок, ничего не понятно»: для MVP наружу смотрит
  // короткое меню (дашборд + revenue-экраны + автоматизация + ключи). Всё
  // скрытое живо и доступно по прямому URL; вернуть пункт = убрать строку.
  "channels",
  "players",
  "bonus",
  "bonuses",
  // Конструкторы сегментов/цепочек завязаны на казино-витрины (player_features,
  // casino_player_id) - на SaaS-данных каталог полей пуст, экраны мёртвые.
  "segments",
  "chains",
  "analytics",
  "funnel",
  "ltv",
  "dist",
  "flags",
  "desk",
  "queue",
  "calendar",
  "report",
  "actions",
  "exports",
  "overview",
  "reports",
  "rfm",
  "cohorts",
  "archetypes",
  "cash",
  "schema",
  "formulas",
  "glossary",
  "signals",
  "extensions",
];

function fromEnv(): string[] {
  const raw = process.env.NEXT_PUBLIC_DISABLED_MODULES ?? "";
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Набор отключённых ключей (item.key ∪ group.title). */
export const DISABLED_MODULES: ReadonlySet<string> = new Set<string>([
  ...STATIC_DISABLED,
  ...fromEnv(),
]);

/** Пункт меню включён? (false → прячем из сайдбара/лаунчера). */
export function isNavKeyEnabled(key: string): boolean {
  return !DISABLED_MODULES.has(key);
}

/** Группа/модуль включён целиком? */
export function isGroupEnabled(groupTitle: string): boolean {
  return !DISABLED_MODULES.has(groupTitle);
}
