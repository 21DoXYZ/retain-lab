import type { MessageKey } from "@/lib/i18n";

type TFn = (key: MessageKey, vars?: Record<string, string | number>) => string;

/**
 * Локализованная метка поля конструктора (метрики/разреза). Бэкенд
 * (describe_fields) отдаёт `label` по-русски — для TR/EN переводим по ключу
 * `reports.field.<key>`. Если ключа нет в словаре (t вернёт сам ключ) —
 * откатываемся на бэкенд-label, чтобы не показать сырой ключ.
 */
export function fieldLabel(t: TFn, key: string, fallback: string): string {
  const mk = `reports.field.${key}` as MessageKey;
  const val = t(mk);
  return val === mk ? fallback : val;
}
