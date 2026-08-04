// Экран «Вердикты по источникам» и вкладка «Каналы» модуля Трафик (W2-T2/T5). Ключи "traffic.*". ru — базовый набор ключей.
export const traffic = {
  // ── экран «Вердикты по источникам» (W2-T2) ──
  "traffic.verdicts.title": "Вердикты по источникам",
  "traffic.verdicts.lead":
    "Прогноз качества когорты на 5-й день: какие источники дают ценных игроков, а какие — фрод. Решение по источнику: масштабировать, наблюдать или отключить.",
  "traffic.verdicts.pill.asOf": "данные на {date}",
  "traffic.verdicts.pill.median": "медиана LTV D90: {v}",

  "traffic.verdicts.tab.source": "Источники",
  "traffic.verdicts.tab.affiliate": "Аффилиаты",

  "traffic.verdicts.days.label": "Период когорты",
  "traffic.verdicts.days.opt": "{n} дн",

  // колонки таблицы (ТЗ §3.1)
  "traffic.verdicts.col.source": "Источник",
  "traffic.verdicts.col.affiliate": "Аффилиат",
  "traffic.verdicts.col.players": "Игроков (7д)",
  "traffic.verdicts.col.playersTitle": "Регистраций за период (в скобках — за последние 7 дней)",
  "traffic.verdicts.col.ftd": "FTD",
  "traffic.verdicts.col.ftdTitle": "Игроков с первым депозитом",
  "traffic.verdicts.col.deposits": "Депозиты",
  "traffic.verdicts.col.depositsTitle": "Сумма депозитов когорты (кэш, спека казино)",
  "traffic.verdicts.col.predSum": "Прогноз LTV D90, Σ",
  "traffic.verdicts.col.predSumTitle": "Суммарный прогноз депозитов за 90 дней по скоренным игрокам",
  "traffic.verdicts.col.predAvg": "на игрока",
  "traffic.verdicts.col.predAvgTitle": "Средний прогноз LTV D90 на скоренного игрока",
  "traffic.verdicts.col.confidence": "Уверенность",
  "traffic.verdicts.col.verdict": "Вердикт",

  // вердикты
  "traffic.verdicts.verdict.scale": "масштабировать",
  "traffic.verdicts.verdict.watch": "наблюдать",
  "traffic.verdicts.verdict.disable": "отключить",
  "traffic.verdicts.verdict.maturing": "зреет · вердикт через {n} дн",
  "traffic.verdicts.verdict.maturingSmall": "зреет · мало данных",

  // уверенность
  "traffic.verdicts.conf.high": "высокая",
  "traffic.verdicts.conf.mid": "средняя",
  "traffic.verdicts.conf.low": "низкая",

  // легенда / как читать
  "traffic.verdicts.legend.label": "Как читать:",
  "traffic.verdicts.legend.scale": "прогноз заметно выше медианы и FTD-rate не ниже базового — лить больше",
  "traffic.verdicts.legend.watch": "в пределах нормы — наблюдать",
  "traffic.verdicts.legend.disable": "игроки бьют игры (GGR < 0) или прогноз вдвое ниже медианы — отключить",
  "traffic.verdicts.legend.maturing": "когорта моложе 5 дней или меньше 10 игроков — рано судить",
  "traffic.verdicts.legend.draft": "Пороги черновые — согласовать с Василием.",

  // состояния
  "traffic.verdicts.empty.title": "За период нет новых регистраций",
  "traffic.verdicts.empty.desc": "В выбранном окне когорт нет — увеличьте период или дождитесь новых регистраций.",
  "traffic.verdicts.error.title": "Не удалось загрузить вердикты",
  "traffic.verdicts.error.desc": "Проверьте соединение с аналитическим бэкендом и повторите.",
} satisfies Record<string, string>;
