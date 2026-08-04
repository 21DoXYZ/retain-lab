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

// Точечно спрятать пункты/модули к запуску (пример: ["reports", "calls.nav.group"]).
// На данный момент пусто — включаем/выключаем по согласованию с клиентом.
const STATIC_DISABLED: readonly string[] = [];

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
