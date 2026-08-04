"use client";

/**
 * Режим очереди (§10.2): порядок звонков передаётся из очереди в карточку через
 * sessionStorage (не тащим длинный список в URL). Карточка находит свой индекс
 * по id — устойчиво к дублям и не ломается при перезагрузке. Активируется
 * query-флагом ?queue=1; без него карточка — обычный самостоятельный экран.
 */
const KEY = "ca_queue_ids";

export function storeQueueIds(ids: string[]): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(ids));
  } catch {
    // приватный режим / нет sessionStorage — просто без навигации по очереди
  }
}

export function readQueueIds(): string[] {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}
