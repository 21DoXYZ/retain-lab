/**
 * ru · домен «segmentation» — базовые (русские) строки. Этот файл — ИСТОЧНИК КЛЮЧЕЙ:
 * ключ обязан быть здесь, иначе он не MessageKey. Переводы — en/segmentation.ts, tr/segmentation.ts.
 * Ключи: "segmentation.<имя>" (плоские, через точку). Интерполяция: {var}.
 *
 * Экраны: /rfm (RfmView), /dist (DistView), /funnel (FunnelView),
 * /cohorts (CohortsView), /archetypes (ArchetypesView).
 *
 * Термины модели НЕ переводятся нигде (RU/EN/TR): названия RFM-сегментов
 * (Champions/Loyal/At-Risk/…) и архетипов/когорт приходят из API как данные —
 * см. types.ts (RfmSegment.seg, Archetype.name/desc, CohortItem.title и т.д.) —
 * и в этом словаре не участвуют.
 */
export const segmentation = {
  // ── /rfm ──────────────────────────────────────────────────────────────
  "segmentation.rfm.title": "RFM-сегменты",
  "segmentation.rfm.accent": "· Recency · Frequency · Monetary",
  "segmentation.rfm.lead":
    "Классическая сегментация по трём осям: как давно играл, как часто и на какие суммы. По каждой оси игрок получает балл от 1 до 5, из их сочетания складывается сегмент. Это правило по прошлому поведению, а не прогноз модели.",
  "segmentation.rfm.card.coverage.label": "Охват RFM",
  "segmentation.rfm.card.coverage.sub": "из {base} normal · {never} не играли (нет ставок)",
  "segmentation.rfm.card.r.label": "R — Recency (давность)",
  "segmentation.rfm.card.r.sub": "как давно играл · меньше = выше балл",
  "segmentation.rfm.card.f.label": "F — Frequency (частота)",
  "segmentation.rfm.card.f.sub": "активных дней",
  "segmentation.rfm.card.m.label": "M — Monetary (деньги)",
  "segmentation.rfm.card.m.sub": "оборот ставок",
  "segmentation.rfm.chart.title": "Размер сегментов",
  "segmentation.rfm.chart.caption": "число игроков по RFM-сегментам",
  "segmentation.rfm.col.segment": "Сегмент",
  "segmentation.rfm.col.players": "Игроков",
  "segmentation.rfm.col.pctBase": "% базы",
  "segmentation.rfm.col.avgTurn": "Ср. оборот",
  "segmentation.rfm.col.avgRecency": "Ср. recency",
  "segmentation.rfm.col.avgRecencyTitle": "дней с последней ставки",
  "segmentation.rfm.col.avgDays": "Ср. дней",
  "segmentation.rfm.col.avgDaysTitle": "активных дней",
  "segmentation.rfm.col.meaning": "Что значит",
  "segmentation.rfm.col.action": "Действие",
  "segmentation.rfm.daySuffix": "д",
  "segmentation.rfm.banner.pre": "RFM требует ось Monetary (оборот), поэтому считается только по",
  "segmentation.rfm.banner.playedWord": "игравшим",
  "segmentation.rfm.banner.mid": "; кто не сделал ни ставки — отдельной строкой внизу",
  "segmentation.rfm.banner.convergeTo": " (сходится к {base})",
  // board rfm() :2172-2173 — «Пульте» вынесено отдельным ключом ради ссылки на /desk
  "segmentation.rfm.banner.post":
    ". RFM — для общей картины и кампаний; для точной приоритизации «кому что дать» — движок офферов на ",
  "segmentation.rfm.banner.deskLink": "Пульте",
  "segmentation.rfm.banner.deskTail": ".",

  // ── /dist ─────────────────────────────────────────────────────────────
  "segmentation.dist.title": "Распределения",
  "segmentation.dist.accent": "· перцентили и концентрация",
  "segmentation.dist.lead":
    "Как ценность и риск распределены по базе. Видно концентрацию: киты держат большую часть денег — поэтому среднее обманывает.",
  "segmentation.dist.card.top10.label": "Топ-10% держат",
  "segmentation.dist.card.top10.sub": "всей прогнозной ценности LTV",
  "segmentation.dist.card.median.label": "Медиана депозитов",
  "segmentation.dist.card.median.sub": "P90 {p90} · P99 {p99}",
  "segmentation.dist.card.max.label": "Макс депозит",
  "segmentation.dist.card.max.sub": "разброс огромный",
  "segmentation.dist.ltvDeciles.title": "Децили по прогнозному LTV",
  "segmentation.dist.ltvDeciles.note": "над {n} игроками с LTV-прогнозом (депозиторы) · D1 = топ-10%, D10 = низ",
  "segmentation.dist.col.decile": "Дециль",
  "segmentation.dist.col.players": "Игроков",
  "segmentation.dist.col.avgLtv": "Средний LTV",
  "segmentation.dist.col.sum": "Сумма",
  "segmentation.dist.col.pctValue": "% всей ценности",
  "segmentation.dist.chart.title": "Концентрация ценности",
  "segmentation.dist.chart.caption": "% всей прогнозной ценности LTV по децилям (D1 = топ-10%)",
  // board dist() :1990 — как читать децили LTV
  "segmentation.dist.ltvDeciles.help.pre": "📖 ",
  "segmentation.dist.ltvDeciles.help.b1": "Дециль",
  "segmentation.dist.ltvDeciles.help.mid": " = база делится на 10 равных групп по 10%. ",
  "segmentation.dist.ltvDeciles.help.b2": "D1 = топ-10%",
  "segmentation.dist.ltvDeciles.help.post":
    " самых ценных, D10 = самые мелкие. Колонка «% всей ценности» показывает, сколько денег держит группа — видно, что верхушка держит почти всё (концентрация на китах).",
  "segmentation.dist.churnDeciles.title": "Децили по риску ухода",
  "segmentation.dist.churnDeciles.note": "среди {n} активных игроков с churn-скором (не вся база)",
  "segmentation.dist.col.avgRisk": "Ср. риск",
  "segmentation.dist.col.range": "Диапазон",
  // board dist() :1996 — как читать децили риска ухода
  "segmentation.dist.churnDeciles.help.pre": "📖 ",
  "segmentation.dist.churnDeciles.help.b1": "Как читать:",
  "segmentation.dist.churnDeciles.help.mid": " активные игроки поделены на 10 групп по риску ухода. ",
  "segmentation.dist.churnDeciles.help.b2": "D1 = самый низкий риск",
  "segmentation.dist.churnDeciles.help.post":
    " (скорее останутся), D10 = самый высокий (скорее уйдут). «Ср. риск» — средняя вероятность ухода в группе.",
  "segmentation.dist.churnWhy.title": "Почему churn не по всей базе — куда делись остальные",
  "segmentation.dist.col.group": "Группа",
  "segmentation.dist.col.whyWhat": "Почему / что с ними делать",
  "segmentation.dist.total": "Итого",
  "segmentation.dist.wholeBaseNormal": "вся база normal",
  // board dist() :2012 — churn осмыслен только для живых + ссылка на движок на Пульте (/desk)
  "segmentation.dist.churnWhy.help.pre":
    "churn-риск осмыслен только для живых: ушедших — возвращать, не игравших — конвертировать, разовых — онбордить. Это и делает движок на ",
  "segmentation.dist.churnWhy.help.link": "Пульте",
  "segmentation.dist.churnWhy.help.post": ".",
  "segmentation.dist.depositPercentiles.title": "Перцентили суммы депозитов",
  "segmentation.dist.depositPercentiles.note": "по {n} депозиторам (dep_count>0)",
  "segmentation.dist.col.percentile": "Перцентиль",
  "segmentation.dist.col.sumTry": "Сумма ₺",
  "segmentation.dist.banner.pre": "«P90 = 11 000» значит",
  "segmentation.dist.banner.bold1": "90% депозиторов внесли меньше 11 000 ₺",
  "segmentation.dist.banner.mid": ", и только 10% — больше.",
  "segmentation.dist.banner.bold2": "P50 = медиана",
  "segmentation.dist.banner.post":
    "(типичный игрок). Верхушка (P99) держит несоизмеримо больше — поэтому «среднее» обманывает: его задирают киты.",

  // ── /funnel ───────────────────────────────────────────────────────────
  "segmentation.funnel.title": "Воронка депозитов",
  "segmentation.funnel.accent": "· где теряем",
  "segmentation.funnel.lead":
    "Путь игрока: регистрация → первая ставка → 1-й депозит → 2-й → … → 10-й. Где теряете больше всего, видно в колонке «конверсия шага».",
  "segmentation.funnel.col.stage": "Этап",
  "segmentation.funnel.col.players": "Игроков",
  "segmentation.funnel.col.pctReg": "% от рег",
  "segmentation.funnel.col.stepConv": "Конверсия шага",
  "segmentation.funnel.col.funnelBar": "Воронка",
  "segmentation.funnel.chart.title": "Воронка",
  "segmentation.funnel.chart.caption": "доля игроков на каждом этапе",
  "segmentation.funnel.emptyTitle": "Нет данных воронки",

  // ── /cohorts ──────────────────────────────────────────────────────────
  "segmentation.cohorts.title": "Все когорты",
  "segmentation.cohorts.defaultSubtitle": "36 срезов",
  "segmentation.cohorts.lead":
    "Каталог всех способов разбить базу на группы — для кампаний и анализа. Клик по сегменту открывает список его игроков.",
  "segmentation.cohorts.loading": "Загрузка срезов…",
  "segmentation.cohorts.noData": "нет данных",
  "segmentation.cohorts.banner.asOf": "Данные на {date}.",
  "segmentation.cohorts.channelsMoved": "Срезы каналов переехали → Каналы",

  // ── /channels (W2-T5) — срезы группы «B · Канал», переехали в модуль Трафик ─
  "segmentation.channels.title": "Каналы: срезы по трафику",
  "segmentation.channels.subtitle": "тип аффилиата, топ-источники, бонус-кампании",
  "segmentation.channels.lead":
    "Откуда приходят игроки: аффилиаты, источники регистрации, бонус-кампании.",
  "segmentation.channels.empty.title": "Нет срезов по каналам",
  "segmentation.channels.empty.desc": "За текущий срез данных группа «Канал» пуста.",
  "segmentation.channels.error.desc": "Не удалось загрузить срезы каналов.",

  // ── /archetypes ───────────────────────────────────────────────────────
  "segmentation.archetypes.title": "Архетипы игроков",
  "segmentation.archetypes.accent": "· похожие по поведению",
  "segmentation.archetypes.lead.withCount": "{n} реальных игроков сгруппированы в типажи по тому, как и во что играют",
  "segmentation.archetypes.lead.fallback": "Игроки сгруппированы в типажи по тому, как и во что играют.",
  "segmentation.archetypes.stat.avgBet": "ср.ставка",
  "segmentation.archetypes.stat.activeDays": "акт. дней",
  "segmentation.archetypes.stat.games": "игр",
  "segmentation.archetypes.stat.depositors": "депозиторов",
  "segmentation.archetypes.stat.turnover": "оборот",
} satisfies Record<string, string>;
