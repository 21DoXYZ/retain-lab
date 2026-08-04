/**
 * ru · домен «calls» — ЯДРО модуля «Анализ звонков»: очередь (§10.2), карточка
 * звонка (§10.3), правка (§10.4), вкладка в карточке игрока (§9).
 * Управленческие экраны (обзор/покрытие/сводка/скрипт/вердикт) — домен callsboard.
 *
 * Правило §11: системных слов (ASR, LLM, SNR, диаризация, needs_human) в
 * интерфейсе НЕТ. Слово «галлюцинация» не используется никогда (§11.7).
 * Термины строго из §11; критерии — 9 канонических (§8).
 */
export const calls = {
  "calls.module.title": "Анализ звонков",

  // ── Раздел меню (components/ui/nav.ts) ──────────────────────────────────
  "calls.nav.group": "Анализ звонков",
  "calls.nav.overview": "Обзор",
  "calls.nav.queue": "Очередь",
  "calls.nav.coverage": "Покрытие",
  "calls.nav.whatWorks": "Что работает",
  "calls.nav.my": "Мои звонки",
  "calls.nav.script": "Скрипт",
  "calls.nav.summary": "Сводка",
  "calls.nav.verdict": "Вердикт и веса",

  // ── Общее ───────────────────────────────────────────────────────────────
  "calls.common.you": "Вы",
  "calls.common.player": "Игрок {id}",
  "calls.common.loadError": "Не удалось загрузить данные. Повторите.",
  "calls.common.retry": "Повторить",
  "calls.common.close": "Закрыть",

  // ── Критерии рубрики (§8, канонические) ──────────────────────────────────
  "calls.criteria.open_identify": "Представился",
  "calls.criteria.rapport": "Контакт",
  "calls.criteria.discovery": "Выявление",
  "calls.criteria.offer_presented": "Назвал оффер",
  "calls.criteria.offer_value": "Ценность оффера",
  "calls.criteria.objection_handling": "Отработка возражений",
  "calls.criteria.alt_offer": "Альтернатива",
  "calls.criteria.next_step": "Следующий шаг",
  "calls.criteria.tone": "Тон",

  // ── Вердикт и балл (§11.2) ────────────────────────────────────────────────
  "calls.verdict.pass": "ПРОШЁЛ",
  "calls.verdict.needsReview": "НУЖНА ПРОВЕРКА",
  "calls.verdict.fail": "ПРОВАЛ",
  "calls.verdict.locked": "вердикт заблокирован",
  "calls.verdict.criterionUnscored": "Нужна проверка",

  // ── Состояние звонка (§11.1) — человеческие слова, без ASR/LLM ───────────
  "calls.status.inQueue": "В очереди",
  "calls.status.transcribing": "Распознаём речь…",
  "calls.status.scoring": "Оцениваем…",
  "calls.status.completed": "Готово",
  "calls.status.needsReview": "Ждёт проверки",
  "calls.status.manualReview": "Плохая запись — нужно прослушать",
  "calls.status.asrFailed": "Речь не распозналась",
  "calls.status.llmFailed": "Оценка не получена",
  "calls.status.error": "Сбой обработки",

  // ── Флаги подлинности (§11.4) — повод послушать, не обвинение ─────────────
  "calls.flag.too_short": "Короткий дозвон — {sec} сек",
  "calls.flag.no_player_speech": "Игрок не говорил",
  "calls.flag.mark_mismatch_no_answer": "Отмечено «не дозвонился», но разговор был",
  "calls.flag.mark_mismatch_claimed": "Отмечено «поговорил», но игрок не говорил",
  "calls.flag.repeated_pattern": "Серия коротких: {n} подряд",
  "calls.flag.random_review": "Случайная проверка",

  // ── Возражения и исход (§11.3) ───────────────────────────────────────────
  "calls.objection.no_money": "Нет денег",
  "calls.objection.no_time": "Нет времени",
  "calls.objection.lost_before": "Много проиграл",
  "calls.objection.distrust": "Не доверяет",
  "calls.objection.other": "Другое",
  "calls.outcome.accepted": "Принял",
  "calls.outcome.refused": "Отказался",
  "calls.outcome.countered": "Предложил своё",
  "calls.outcome.no_offer": "Оффер не звучал",
  "calls.outcome.unclear": "Неясно",

  // ── Обязательные фразы (§8, §10.3) ───────────────────────────────────────
  "calls.phrase.recording": "Предупреждение о записи",
  "calls.phrase.age": "Возраст 18+",
  "calls.phrase.responsible": "Ответственная игра",

  // ── Очередь (§10.2) ──────────────────────────────────────────────────────
  "calls.queue.title": "Очередь проверки",
  "calls.queue.lead": "Что подтвердить или поправить; какие звонки послушать лично.",
  "calls.queue.chip.all": "Все",
  "calls.queue.chip.modelUnsure": "Модель не уверена",
  "calls.queue.chip.fails": "Провалы",
  "calls.queue.chip.badRecording": "Плохая запись",
  "calls.queue.chip.compliance": "Обязательные фразы",
  "calls.queue.chip.needsReview": "Требуют проверки",
  "calls.queue.chip.disputed": "Оспорено оператором",
  "calls.queue.chip.randomReview": "Случайная проверка",
  "calls.queue.series": "Серия коротких: {n} подряд",
  "calls.queue.seriesRange": "{n} подряд, {lo}–{hi} сек",
  "calls.queue.action.listen": "Прослушать",
  "calls.queue.action.review": "Проверить",
  "calls.queue.action.resolve": "Разобрать",
  "calls.queue.disputedReason": "Оператор не согласен",
  "calls.queue.empty.title": "Очередь пуста.",
  "calls.queue.empty.desc": "Все дозвоны за сегодня разобраны.",
  "calls.queue.empty.action": "Смотреть все звонки",
  "calls.queue.col.id": "Звонок",
  "calls.queue.col.operator": "Оператор",
  "calls.queue.col.time": "Длит.",
  "calls.queue.col.score": "Балл",
  "calls.queue.col.reason": "Причина",

  // ── Карточка звонка (§10.3) ──────────────────────────────────────────────
  "calls.card.backToQueue": "Очередь",
  "calls.card.position": "{i} из {n}",
  "calls.card.prev": "Пред",
  "calls.card.next": "След",
  "calls.card.notFound": "Звонок не найден.",
  "calls.card.scoreLabel": "Балл",
  "calls.card.criteria": "Критерии",
  "calls.card.versions": "Скрипт v{script} · Рубрика v{rubric} · {model}",
  "calls.card.needsCheck": "Нужна проверка",
  "calls.card.needsCheckTip": "Модель не смогла оценить этот критерий уверенно (неточный расчёт). Критерий исключён из подсчёта, остальные веса пересчитаны.",
  "calls.card.confirm": "Подтвердить",
  "calls.card.correct": "Поправить",
  "calls.card.reconcileTip": "Подтверждения без разбора в сверку не идут — иначе цифра согласия ничего не значит.",
  "calls.card.reviewTime": "На разборе: {t}",
  "calls.card.confirmed": "Подтверждено — идёт в сверку.",
  "calls.card.confirmedNotCounted": "Просмотрено, но в сверку не пойдёт — слишком быстро.",
  "calls.card.confirmError": "Не удалось подтвердить. Повторите.",
  "calls.card.humanOverride": "{model} (модель) → {human} ({name}, {date})",
  "calls.card.offerOutcome": "Исход оффера",
  "calls.card.objections": "Возражения",
  "calls.card.analystNote": "Режим чтения: подтверждать и править может руководитель.",

  // ── Транскрипт (§10.3, §13) ──────────────────────────────────────────────
  "calls.transcript.title": "Разговор",
  "calls.transcript.langRu": "Русский",
  "calls.transcript.langEn": "English",
  "calls.transcript.original": "Оригинал TR",
  "calls.transcript.loading": "Загружаем перевод…",
  "calls.transcript.translationPanel": "Перевод",
  "calls.transcript.spine": "Оригинал · таймкоды",
  "calls.transcript.roleAgent": "ОПЕРАТОР",
  "calls.transcript.rolePlayer": "ИГРОК",
  "calls.transcript.unavailable": "Транскрипта пока нет.",
  "calls.transcript.translationUnavailable": "Перевод сейчас недоступен. Оригинал на турецком доступен.",

  // ── Полоса обязательных фраз (§10.3) ─────────────────────────────────────
  "calls.compliance.title": "Обязательные фразы",
  "calls.compliance.count": "{present} из {total}",
  "calls.compliance.notSpoken": "не прозвучало",
  "calls.compliance.listenFull": "Прослушать звонок",
  "calls.compliance.note": "Полоса не влияет на балл: качество продажи и обязательные фразы — разные вопросы.",

  // ── Плеер (§10.3) ────────────────────────────────────────────────────────
  "calls.audio.play": "Играть",
  "calls.audio.pause": "Пауза",
  "calls.audio.unavailable": "Запись недоступна.",
  "calls.audio.loading": "Загружаем запись…",
  "calls.audio.keysHint": "Пробел — играть/пауза · ←/→ — перемотка ±5 сек",

  // ── Правка оценки (§10.4) ────────────────────────────────────────────────
  "calls.override.title": "Поправить оценку · {id}",
  "calls.override.criterion": "Критерий",
  "calls.override.model": "Модель",
  "calls.override.you": "Вы",
  "calls.override.total": "Итог: {model} → {human}",
  "calls.override.willRecalc": "Итог пересчитается при сохранении.",
  "calls.override.reason": "Причина (обязательно)",
  "calls.override.reasonPlaceholder": "Например: возражение отработано — модель не распознала турецкую идиому.",
  "calls.override.toReconciliation": "Правка попадёт в сверку модели.",
  "calls.override.cancel": "Отмена",
  "calls.override.save": "Сохранить",
  "calls.override.saveError": "Не удалось сохранить правку. Повторите.",

  // ── Вкладка «Звонки» в карточке игрока (§9) ──────────────────────────────
  "calls.tab.title": "Звонки — анализ",
  "calls.tab.hint": "История звонков игрока с оценками анализатора.",
  "calls.tab.empty": "Звонков пока нет.",
  "calls.tab.emptyDesc": "Здесь появится история звонков этого игрока с разбором.",
  "calls.tab.score": "Балл",
  "calls.tab.noScore": "нет данных",
  "calls.tab.analysisLink": "Анализ →",
  "calls.tab.mappingNote": "Оценки анализатора появятся, когда звонки CRM свяжутся с разбором.",

  // Реакция после звонка (минуты до депа/игры)
  "calls.card.reaction.title": "После звонка:",
  "calls.card.reaction.deposit": "депозит через {min} мин",
  "calls.card.reaction.noDeposit": "депозита не было (7 дней)",
  "calls.card.reaction.played": "вернулся в игру через {min} мин",
  "calls.card.reaction.noPlay": "в игру не вернулся",
} satisfies Record<string, string>;
