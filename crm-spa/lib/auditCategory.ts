"use client";

import { useCallback } from "react";
import { useT, type MessageKey } from "./i18n";

/**
 * Перевод категории списания, приходящей С БЭКЕНДА русской подписью.
 *
 * `CAT` в player_board.py:3108 — multiIf по тексту notes → ФИКСИРОВАННЫЙ набор
 * из 8 русских подписей. Это стабильный КОД, а не свободный текст: переводим по
 * нему (тот же приём, что dow.ts и статусы оффера). Русская подпись из API —
 * ключ, не то, что видит турецкий/английский оператор.
 *
 * Незнакомую категорию отдаём как есть — не ломаем график из-за словаря.
 */
const CAT_KEY: Record<string, MessageKey> = {
  "🧪 тест-операции": "money.audit.cat.test",
  "лишний выигрыш (сверх лимита)": "money.audit.cat.excessWin",
  "истёкший бонус": "money.audit.cat.expiredBonus",
  "нечестный выигрыш": "money.audit.cat.unfairWin",
  "нарушение правил/промо": "money.audit.cat.ruleViolation",
  "бонус без депозита": "money.audit.cat.noDepositBonus",
  "(без пометки)": "money.audit.cat.unmarked",
  "прочее": "money.audit.cat.other",
};

/** `catLabel("прочее")` → «Diğer» / «Other» / «прочее» по текущей локали. */
export function useAuditCategory(): (raw: string | null | undefined) => string {
  const t = useT();
  return useCallback(
    (raw: string | null | undefined): string => {
      if (!raw) return "";
      const key = CAT_KEY[raw.trim()];
      return key ? t(key) : raw;
    },
    [t],
  );
}
