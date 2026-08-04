// Экран «Лента флагов» модуля Риск и фрод (W2-T3). Ключи "risk.*". ru — базовый набор ключей.
export const risk = {
  "risk.flags.title": "Лента флагов",
  "risk.flags.lead": "Единая очередь «требует проверки» — сигналы из аудита, аффилиатов и бонусов в одном списке.",

  // Плашки-пилюли шапки
  "risk.flags.pill.total": "{n} на проверке",
  "risk.flags.pill.checked": "проверено {mins} мин назад",
  "risk.flags.pill.checkedNow": "проверено только что",

  // Плитки по видам (клик = фильтр ленты)
  "risk.flags.tile.hint": "Клик — фильтр ленты по этому виду",
  "risk.flags.tile.active": "фильтр активен",
  "risk.flags.kind.no_deposit_withdrawal.label": "Вывод без депозита",
  "risk.flags.kind.no_deposit_withdrawal.sub": "ручные списания > 50k ₺ при депозите < 10% от вывода",
  "risk.flags.kind.suspicious_operator.label": "Оператор под вопросом",
  "risk.flags.kind.suspicious_operator.sub": "≥ 40% списаний без внятной пометки",
  "risk.flags.kind.affiliate_players_win.label": "Игроки бьют игры",
  "risk.flags.kind.affiliate_cash_drain.label": "Касса в минусе",
  "risk.flags.kind.affiliate_players_win.sub": "реальный GGR источника в минусе",
  "risk.flags.kind.affiliate_cash_drain.sub": "выводы больше депозитов",
  "risk.flags.kind.bonus_abuse.label": "Бонусный абуз",
  "risk.flags.kind.bonus_abuse.sub": "архетип «🎁 Бонусник» в плюсе на фриспинах",

  // Колонки таблицы
  "risk.flags.col.kind": "Вид",
  "risk.flags.col.entity": "Сущность",
  "risk.flags.col.amount": "Сумма ₺",
  "risk.flags.col.severity": "Важность",
  "risk.flags.col.details": "Детали",

  // Сущности (ссылки на карточки)
  "risk.flags.entity.player": "Игрок #{id}",
  "risk.flags.entity.operator": "Оператор {id}",
  "risk.flags.entity.affiliate": "Источник {id}",

  // Детали строки по видам
  "risk.flags.details.no_deposit_withdrawal": "внесено {deposited} ₺ · {ops} опер.",
  "risk.flags.details.suspicious_operator": "непонятных {unclear}% · {ops} опер.",
  "risk.flags.details.adminBadge": "админ/служебный",
  "risk.flags.details.affiliate": "{players} игроков · FTD {ftd}",
  "risk.flags.details.bonus_abuse": "фриспины {freespin}%",

  // Важность (severity)
  "risk.flags.sev.3": "крупный (≥ 100k ₺)",
  "risk.flags.sev.2": "заметный (≥ 20k ₺)",
  "risk.flags.sev.1": "мелкий",

  // Фильтр
  "risk.flags.filter.reset": "Сбросить фильтр",

  // Пояснительный баннер
  "risk.flags.banner.severity": "Важность: 🔴 крупный (≥ 100k ₺) · 🟡 заметный (≥ 20k ₺) · ⚪ мелкий.",
  "risk.flags.banner.sources": "Источники: аудит списаний, вердикты аффилиатов, архетип «Бонусник». Клик по плитке фильтрует ленту.",

  // Пусто «всё чисто» (ТЗ §4.1) + пусто по фильтру
  "risk.flags.empty.clear.title": "Флагов нет — всё чисто",
  "risk.flags.empty.clear.desc": "Ни одного сигнала на проверку. Последняя проверка {mins} мин назад.",
  "risk.flags.empty.clear.descNow": "Ни одного сигнала на проверку. Последняя проверка только что.",
  "risk.flags.empty.kind.title": "Нет флагов этого вида",
  "risk.flags.empty.kind.desc": "По выбранному виду сейчас пусто. Сбросьте фильтр, чтобы увидеть остальные.",

  // Состояния маршрута (loading / error)
  "risk.flags.loading.lead": "Собираем сигналы на проверку…",
  "risk.flags.error.title": "Не удалось загрузить ленту флагов",
  "risk.flags.error.desc": "Проверьте соединение и повторите попытку.",
} satisfies Record<string, string>;
