/**
 * Role allow-lists for the «Анализ звонков» management screens — mirror the
 * require_auth(roles=...) matrices in api/call_analysis.py 1:1. Menu/page gating
 * is a UX convenience; the Flask JWT check + DB RLS are the real boundary.
 *
 * Typed as readonly string[] on purpose: one server role — translation_reviewer
 * (§10.11, temporary access) — is NOT part of the 14-role UserRole union, so the
 * comparison is done by string. Client-safe (no next/headers) — usable from both
 * Server Component guards and client screens.
 */

export const OPERATOR_LIKE = ["operator", "vip_manager"] as const;
export const MANAGE_DEPT = ["head_department"] as const;
export const MANAGE_ALL = ["head_retention"] as const;
export const READONLY = ["analyst"] as const;
export const OWNER = ["director"] as const;
export const ADMIN = ["super_admin"] as const;
export const TRANSLATION = ["translation_reviewer"] as const;

const MANAGE = [...MANAGE_DEPT, ...MANAGE_ALL];

/** Обзор (§10.1) — R_OVERVIEW. */
export const CB_OVERVIEW: readonly string[] = [...MANAGE, ...READONLY, ...ADMIN];
/** Отчёт по оператору (§10.5) — R_REPORT (оператор — свой, гейт на сервере). */
export const CB_REPORT: readonly string[] = [...MANAGE, ...ADMIN, ...READONLY, ...OPERATOR_LIKE];
/** Покрытие (§10.7) — R_COVERAGE. */
export const CB_COVERAGE: readonly string[] = [...MANAGE, ...ADMIN];
/** Что работает (§10.6) — R_WHATWORKS. */
export const CB_WHATWORKS: readonly string[] = [...MANAGE_ALL, ...ADMIN];
/** Сводка (§10.12) — R_SUMMARY. */
export const CB_SUMMARY: readonly string[] = [...OWNER, ...MANAGE_ALL, ...ADMIN];
/** Мои звонки (§10.10) — R_MYCARDS. */
export const CB_MYCARDS: readonly string[] = [...OPERATOR_LIKE];
/** Скрипт (§10.8/§10.9) — R_SCRIPT_GET (оператор — read-only). */
export const CB_SCRIPT: readonly string[] = [...MANAGE_ALL, ...ADMIN, ...OPERATOR_LIKE];
/** Вердикт и веса (§10.13) — R_ADMIN. */
export const CB_VERDICT: readonly string[] = [...ADMIN];
/** Проверка перевода (§10.11) — R_TRANSLATION. */
export const CB_TRANSLATION: readonly string[] = [...TRANSLATION, ...ADMIN];

/** Оператор/VIP — экран рендерится по-турецки, балл скрыт при заблок. вердикте. */
export function isOperatorRole(role: string): boolean {
  return (OPERATOR_LIKE as readonly string[]).includes(role);
}

/** Кто правит разметку скрипта (§10.8) — остальным read-only (§10.9). */
export function canWriteScript(role: string): boolean {
  return ([...MANAGE_ALL, ...ADMIN] as readonly string[]).includes(role);
}
