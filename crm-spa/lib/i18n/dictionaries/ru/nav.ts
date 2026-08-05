/**
 * ru · домен «nav» — базовые (русские) строки. Этот файл — ИСТОЧНИК КЛЮЧЕЙ:
 * ключ обязан быть здесь, иначе он не MessageKey. Переводы — en/nav.ts, tr/nav.ts.
 * Ключи: "nav.<имя>" (плоские, через точку). Интерполяция: {var}.
 */
export const nav = {
  // Section super-headings (components/ui/nav.ts NAV_GROUPS[].section) — полосы модулей
  "nav.section.entry": "Вход",
  "nav.section.expand": "Расширение",
  "nav.section.core": "Ядро",
  "nav.section.layer": "Слой / фундамент",

  // Group titles — 7 модулей (components/ui/nav.ts NAV_GROUPS[].title)
  "nav.group.traffic": "📡 Трафик и аффилиаты",
  "nav.group.vip": "🐋 VIP-радар",
  "nav.group.bonuseco": "🎁 Бонус-экономика",
  "nav.group.risk": "🛡 Риск и фрод",
  "nav.group.core": "⚡ Retention-автоматизация",
  "nav.group.analytics": "📊 Аналитика",
  "nav.group.data": "🧱 Данные / API",

  // Legacy group titles — сохранены для обратной совместимости словаря (не используются в NAV_GROUPS)
  "nav.group.work": "Моя работа",
  "nav.group.cabinet": "Кабинет",
  "nav.group.retention": "Ретеншн-отдел",
  "nav.group.main": "Главное",
  "nav.group.marketing": "Маркетинг",
  "nav.group.money": "Деньги и риск",
  "nav.group.integration": "Интеграция",
  "nav.group.admin": "Администрирование",

  // Item labels (components/ui/nav.ts NAV_GROUPS[].items[].label)
  "nav.queue": "Моя очередь",
  "nav.calendar": "Календарь звонков",
  "nav.affiliateCabinet": "Мои игроки",
  "nav.desk": "Пульт (очередь)",
  "nav.vipRisk": "VIP-риск",
  "nav.live": "Играют сейчас",
  "nav.report": "Отчёт отдела",
  "nav.exports": "Проверка выгрузок",
  "nav.overview": "Обзор",
  "nav.players": "Игроки",
  "nav.affiliates": "Аффилиаты",
  "nav.analytics": "Аналитика",
  "nav.ltv": "LTV-прогноз",
  "nav.dist": "Распределения",
  "nav.funnel": "Воронка депозитов",
  "nav.rfm": "RFM-сегменты",
  "nav.cohorts": "Все когорты",
  "nav.archetypes": "Архетипы",
  "nav.games": "Игры",
  "nav.schema": "Схема данных",
  "nav.formulas": "Формулы расчётов",
  "nav.glossary": "Словарь обозначений",
  "nav.actions": "Действия / Офферы",
  "nav.bonus": "Бонусы: эффект",
  "nav.bonuses": "Бонусы: каталог",
  "nav.campaigns": "Кампании",
  "nav.ggr": "GGR и доход",
  "nav.cash": "Деньги",
  "nav.risk": "Аудит выводов",
  "nav.signals": "Сигналы модели",
  "nav.keys": "Ключи интеграции",
  "nav.extensions": "Внутренние номера",
  "nav.users": "Пользователи",
  "nav.verdicts": "Вердикты по источникам",
  "nav.channels": "Каналы (срезы)",
  "nav.vipQueue": "Очередь VIP",
  "nav.ggrBonus": "Бонус-выдачи (GGR)",
  "nav.flags": "Лента флагов",
  "nav.segments": "Сегменты",
  "nav.chains": "Цепочки",
  "nav.reports": "Конструктор отчётов",
} satisfies Record<string, string>;
