/**
 * ru · домен «ui» — базовые (русские) строки. Этот файл — ИСТОЧНИК КЛЮЧЕЙ:
 * ключ обязан быть здесь, иначе он не MessageKey. Переводы — en/ui.ts, tr/ui.ts.
 * Ключи: "ui.<имя>" (плоские, через точку). Интерполяция: {var}.
 */
export const ui = {
  // States.tsx — EmptyState / ErrorState defaults
  "ui.empty.title": "Ничего не найдено",
  "ui.error.title": "Не удалось загрузить",
  "ui.error.description": "Попробуйте обновить. Если повторяется — сообщите администратору.",
  "ui.error.retry": "Повторить",

  // Collapsible.tsx — toggle cue
  "ui.collapsible.expand": "нажми, чтобы развернуть ▾",
  "ui.collapsible.collapse": "свернуть ▴",

  // Modal.tsx
  "ui.modal.close": "Закрыть",

  // Generic reusable actions (used across card.* screens too)
  "ui.cancel": "Отмена",
  "ui.save": "Сохранить",

  // Badge.tsx / badges.ts — lifecycle stage
  "ui.badge.lifecycle.active": "активен",
  "ui.badge.lifecycle.cooling": "остывает",
  "ui.badge.lifecycle.atRisk": "под риском",
  "ui.badge.lifecycle.dormant": "спящий",
  "ui.badge.lifecycle.churned": "отток",
  "ui.badge.lifecycle.never": "не играл",
  "ui.badge.lifecycleTip.active": "Ставил в последние 7 дней",
  "ui.badge.lifecycleTip.cooling": "Последняя ставка 8–30 дней назад",
  "ui.badge.lifecycleTip.atRisk": "Последняя ставка 31–60 дней назад",
  "ui.badge.lifecycleTip.dormant": "Последняя ставка 61–90 дней назад",
  "ui.badge.lifecycleTip.churned": "Последняя ставка больше 90 дней назад",
  "ui.badge.lifecycleTip.never": "Ни одной ставки",

  // Badge.tsx / badges.ts — account type
  "ui.badge.accountType.service": "🛡 служебный/админ",
  "ui.badge.accountType.testOrService": "🧪 тест",
  "ui.badge.accountType.blocked": "⛔ заблокирован",

  // Badge.tsx / badges.ts — LTV early tier
  "ui.badge.tier.a": "A · <1k/нед",
  "ui.badge.tier.b": "B · 1–3k",
  "ui.badge.tier.c": "C · 3–10k",
  "ui.badge.tier.d": "D · 10k+ 🐋",

  // Badge.tsx — "beats the casino" marker
  "ui.badge.beatsCasino.tooltip":
    "обыгрывает казино: в плюсе по кассе и по игре — бонусы не рекомендуются",
  "ui.badge.beatsCasino.ariaLabel": "обыгрывает казино",

  // шапка приложения (UserMenu)
  "ui.signOut": "Выйти",

  // ── бейдж рекомендованного действия (движок офферов) ─────────────────────
  // API (retention.player_actions.action) отдаёт «КОД · пояснение по-русски».
  // Код универсален, а пояснение локализуем: турецкий оператор иначе прочитает
  // «NURTURE · растить» и не поймёт. Ключ выбирается по коду (ActionBadge);
  // незнакомый код падает на сырое значение из API. RU — дословно как в витрине.
  "ui.badge.action.SAVE": "SAVE · удержать",
  "ui.badge.action.WINBACK": "WINBACK · вернуть",
  "ui.badge.action.NUDGE": "NUDGE · 2-й депозит",
  "ui.badge.action.CONVERT": "CONVERT · первый депозит",
  "ui.badge.action.NURTURE": "NURTURE · растить",
  "ui.badge.action.MONITOR": "MONITOR · игрок в плюсе (ревью)",
  "ui.badge.action.observe": "наблюдать",
  "ui.freshness.badge": "данные до {ts}",
  "ui.freshness.hint": "Досюда дозагружены данные: деньги — {money}, игра — {game}. Дальше — не «игрок молчит», а конец данных.",

} satisfies Record<string, string>;
