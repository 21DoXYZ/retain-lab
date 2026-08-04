/**
 * ru · домен «card» — базовые (русские) строки. Этот файл — ИСТОЧНИК КЛЮЧЕЙ:
 * ключ обязан быть здесь, иначе он не MessageKey. Переводы — en/card.ts, tr/card.ts.
 * Ключи: "card.<имя>" (плоские, через точку). Интерполяция: {var}.
 */
export const card = {
  // CardHeader.tsx
  "card.header.playerLabel": "Игрок",
  "card.header.noDeposit": "· без депозита",
  "card.header.alsoWith": "также у:",
  "card.header.backToList": "← к списку",
  "card.header.kpi.bets": "Ставок",
  "card.header.kpi.turnover": "Оборот ₺",
  "card.header.kpi.net": "Net ₺",
  "card.header.kpi.ggr": "GGR ₺",
  "card.header.kpi.deposits": "Депозитов",
  "card.header.kpi.recency": "Давность",
  "card.header.daysShort": "{n}д",

  // CallBlock.tsx
  "card.call.title": "Звонок",
  "card.call.phoneLabel": "Телефон:",
  "card.call.phoneHiddenHint": "(скрыт — звонок только кнопкой)",
  "card.call.phoneUnavailable": "Телефон недоступен для вашей роли",
  "card.call.callButton": "📞 Позвонить",
  "card.call.todayHintLead": "Сегодня в {time} звонил",
  "card.call.todayHintTrail":
    "— {outcome}. Чтобы не задваивать касание, уточните прежде чем звонить.",
  "card.call.journalTitle": "Журнал звонков",
  "card.call.emptyTitle": "Звонков ещё не было",
  "card.call.emptyDescription": "Нажмите «Позвонить», чтобы связаться с игроком.",
  "card.call.confirmTitle": "Сегодня уже звонили",
  "card.call.confirmAnyway": "Всё равно позвонить",
  "card.call.confirmLead": "Сегодня этого игрока уже касался",
  "card.call.confirmTrail": "({outcome}). Звонить повторно?",
  "card.call.confirmFallback": "Игрока сегодня уже касались. Звонить повторно?",
  "card.call.originateError": "Не удалось инициировать звонок.",
  "card.call.saveError": "Ошибка сохранения.",

  // access.ts — CallOutcome labels
  "card.outcome.answered": "Дозвон",
  "card.outcome.noAnswer": "Недозвон",
  "card.outcome.busy": "Занято",
  "card.outcome.wrongNumber": "Неверный номер",

  // access.ts — CallResult labels
  "card.result.interested": "Заинтересован",
  "card.result.offerDeclined": "Оффер не подошёл",
  "card.result.callbackRequested": "Просил перезвонить",
  "card.result.refused": "Отказ",

  // OutcomeModal.tsx
  "card.outcomeModal.title": "Исход звонка",
  "card.outcomeModal.dialedNumber": "Набран номер:",
  "card.outcomeModal.step1": "1. Как прошёл звонок",
  "card.outcomeModal.step2": "2. Результат разговора",
  "card.outcomeModal.noAnswerNote": "Игрок остаётся в очереди — предложим запланировать следующий.",
  "card.outcomeModal.genericNote": "Исход будет зафиксирован в журнале.",

  // NotesBlock.tsx
  "card.notes.title": "📝 Заметки",
  "card.notes.hint": "история по игроку — с именами авторов",
  "card.notes.placeholder": "Что обсудили, договорённости, реакция на оффер…",
  "card.notes.addButton": "Добавить заметку",
  "card.notes.emptyTitle": "Заметок пока нет",
  "card.notes.emptyDescription": "Добавьте первую заметку выше.",
  "card.notes.editedSuffix": " · изменено",
  "card.notes.editButton": "Изменить",
  "card.notes.deleteButton": "Удалить",
  "card.notes.linkedOfferPrefix": "→ оффер:",
  "card.notes.tagLinkedOfferPrefix": "привязка к офферу:",
  "card.notes.noActiveOffer": "активный оффер не определён — тег без привязки",
  "card.notes.emptyContent": "Введите текст заметки.",
  "card.notes.editWindowExpired": "Окно редактирования (15 минут) истекло.",

  // access.ts — NoteTag labels (chips)
  "card.tag.offerDeclined": "Оффер не подошёл",
  "card.tag.otherOffer": "Предложен другой",
  "card.tag.callback": "Просил перезвонить",
  "card.tag.negative": "Негатив",
  "card.tag.returned": "Вернулся",

  // OfferBlock.tsx
  "card.offer.title": "✍️ Оффер игроку",
  "card.offer.hint": "Это журнал решения: текст и статус сохраняются и не перетираются системой. Живая подсказка «что предложить сейчас» — выше, в «Рекомендованном действии».",
  "card.offer.staleNotice": "⚠ Система сейчас рекомендует другое: «{name}»",
  "card.offer.useCurrent": "подставить текущую",
  "card.offer.subtitle": "решение отдела — что реально утверждено/отправлено игроку",
  "card.offer.notePlaceholder": "заметка оператора (необязательно)",
  "card.offer.approveButton": "✅ Утвердить",
  "card.offer.editButton": "✏️ Сохранить правку",
  "card.offer.sendButton": "📨 Отправить",
  "card.offer.declineButton": "❌ Отклонить",
  "card.offer.savedSuffix": "{label} · решение сохранено",

  // RecommendationStrip.tsx
  "card.recommendation.title": "🎯 Рекомендованное действие",
  "card.recommendation.subtitle": "движок офферов · пересчитывается при каждом открытии — что система предлагает СЕЙЧАС",
  "card.recommendation.action": "Действие",
  "card.recommendation.bonus": "Реком. бонус",
  "card.recommendation.when": "Когда",
  "card.recommendation.churnRisk": "Риск ухода (30д)",
  "card.recommendation.secondDepositProb": "P(2-й деп, 30д)",
  "card.recommendation.priorityNote":
    "приоритет = ценность × риск ухода · канал доставки — нет данных",

  // ctx-моментум («последняя форма») — баннер в блоке рекомендации (board ctx,
  // player_board.py:1435-1438 · формула мёртвой зоны ±avg_bet*20). Тексты дословно
  // из борда (без <b>-разметки). :1540 — контекст без строки в player_actions.
  "card.momentum.liveLabel": "⚡ что происходит с игроком сейчас — динамика последних игровых сессий",
  "card.momentum.contextTitle": "🎯 Контекст по игре",
  "card.momentum.down":
    "🔻 В минусе (серия проигрышей / отрицательный недавний net) → сейчас уместен кэшбэк / бонус на проигрыш, пока не ушёл от фрустрации.",
  "card.momentum.up":
    "🔺 На подъёме (недавно в плюсе) → нудж к депозиту на волне выигрыша или фриспины в любимой игре.",
  "card.momentum.flat": "➖ Ровная динамика — действуем по основному офферу.",

  // RecordingPlayer.tsx
  "card.recording.unavailable": "Запись недоступна.",
  "card.recording.playButton": "▶ Прослушать",

  // ScheduleBlock.tsx
  "card.schedule.status.planned": "запланирован",
  "card.schedule.status.done": "выполнен",
  "card.schedule.status.overdue": "просрочен",
  "card.schedule.status.missed": "пропущен",
  "card.schedule.title": "Запланировать следующий звонок",
  "card.schedule.nudgeHint": "Игрок не ответил и остаётся в очереди — запланируйте следующее касание.",
  "card.schedule.suggestionPrefix": "Обычно активен:",
  "card.schedule.applySuggestion": "Подставить слот",
  "card.schedule.autoComment": "Автослот по активности игрока",
  "card.schedule.missingDateTime": "Укажите дату и время.",
  "card.schedule.dateTimeAriaLabel": "Дата и время",
  "card.schedule.commentPlaceholder": "Комментарий (напр. «удобно в пятницу вечером»)",
  "card.schedule.submitButton": "Запланировать",
  "card.schedule.upcomingTitle": "Запланированные касания",
  "card.schedule.emptyTitle": "Нет запланированных звонков",
  "card.schedule.bySystem": "предложено системой",
  "card.schedule.suggestionAround": "{day}, около {hour}:00",

  // Shared across player-card blocks (author name / generic errors)
  "card.common.you": "Вы",
  "card.common.operatorFallback": "Оператор …{id}",
  "card.common.error": "Ошибка.",
  "card.common.loadError": "Не удалось загрузить данные.",

  // data.ts — CardDataError copy (key = CardDataError.key, resolved by the
  // catching component: NotesBlock/CallBlock/OfferBlock/ScheduleBlock/
  // RecordingPlayer). Raw Supabase/Postgres error text has no key (not ours
  // to translate) and falls back to CardDataError.message as-is.
  "card.error.rlsDenied":
    "Недостаточно прав: этот игрок не в вашей зоне (не назначен вам). Действие отклонено политикой доступа.",
  "card.error.operationalLoadFailed": "Не удалось загрузить операционные данные.",
  "card.error.noteSaveFailed": "Не удалось сохранить заметку.",
  "card.error.noteEditFailed": "Не удалось изменить заметку.",
  "card.error.noteDeleteFailed": "Не удалось удалить заметку.",
  "card.error.callOutcomeSaveFailed": "Не удалось сохранить исход звонка.",
  "card.error.scheduleSaveFailed": "Не удалось запланировать звонок.",
  "card.error.recordingNotFound": "У звонка нет записи.",
  "card.error.recordingUnavailable": "Запись недоступна ({status}).",

  // ── Подсказки KPI-плиток (board SCARD_TIP, player_board.py:1305-1320) ──────
  // Нативный title на .scard: CardHeader (6) + LTV/Ladder-плитки (9). Дословно.
  "card.tip.scard.bets": "Число ставок (bet + freespins_bet).",
  "card.tip.scard.turnover": "Оборот = Σ ставок.",
  "card.tip.scard.net": "Net игрока = выигрыши − ставки. − = слил (взгляд игрока).",
  "card.tip.scard.ggr": "GGR казино = ставки − выигрыши = −net. Доход казино от игры (до бонусов).",
  "card.tip.scard.deposits": "Число завершённых депозитов.",
  "card.tip.scard.recency": "Дней с последней ставки.",
  "card.tip.scard.tier": "Тир по депозиту 1-й недели: A<1k · B<3k · C<10k · D≥10k.",
  "card.tip.scard.depWeek1": "Σ депозитов в первые 7 дней от FTD (фича LTV-модели).",
  "card.tip.scard.forecastD90": "ML-прогноз суммы депозитов к 90-му дню по поведению 1-й недели.",
  "card.tip.scard.rangeD90": "Квантильный прогноз: P10–P90 — честный разброс (киты).",
  "card.tip.scard.headroom": "Headroom = max(0, прогноз D90 − уже внесено). 0 = прогноз уже превышен.",
  "card.tip.scard.current": "Текущая ступень = номер последнего депозита.",
  "card.tip.scard.pNextPersonal": "Персональный P(следующий депозит в 30 дн), ML (любая ступень).",
  "card.tip.scard.pNextBase": "Средняя конверсия этой ступени по всей базе. Считается только до #10 (дальше «—»).",
  "card.tip.scard.target": "Следующая ступень = депозит #(N+1).",

  // ── Расшифровки полей .fld (board CARD_TIP, player_board.py:1254-1303) ─────
  // Нативный title на каждом поле секций Профиль/Деньги/Игра/Паттерн. Дословно.
  // vip_level — из inline _viptip (player_board.py:1354).
  "card.tip.field.vip_level":
    "VIP-уровень (правила казино) по накопительным успешным депозитам в TRY: Regular <100, Silver ≥100, Gold ≥50k, Platinum ≥150k, Diamond ≥500k, Royal ≥1M. Для уровня ≥ Silver нужен хотя бы один депозит ≥ 100 TRY.",
  "card.tip.field.account_type":
    "Тип аккаунта. normal = реальный игрок; test_or_service / service / blocked — не реальные (в моделях исключаются).",
  "card.tip.field.status": "Статус аккаунта из источника.",
  "card.tip.field.country": "Страна (оценка по country_iso_estimated).",
  "card.tip.field.reg_date": "Дата регистрации.",
  "card.tip.field.tenure_days": "Возраст аккаунта = дней с регистрации.",
  "card.tip.field.affiliate_type": "Тип аффилиат-аккаунта (classic и т.п.).",
  "card.tip.field.ftd_amount": "Сумма первого депозита (FTD).",
  "card.tip.field.balance": "Баланс — снимок на момент выгрузки (не live).",
  "card.tip.field.bonus_balance": "Бонусный баланс — снимок на момент выгрузки.",
  "card.tip.field.activity_status": "Статус активности из источника.",
  "card.tip.field.dep_count": "Число завершённых депозитов (deposit + manual_deposit, status=completed).",
  "card.tip.field.dep_sum":
    "Депозиты ВКЛ. ручные (manual=бонус) — поведенческое поле для моделей. Реальный кэш → «внёс (кэш)».",
  "card.tip.field.cash_deposits":
    "Кэш-депозиты (спека казино): Σ по type=deposit, успешные. БЕЗ manual_deposit. Сверяемо с бордом.",
  "card.tip.field.withdrawals_abs":
    "Выводы (спека): Σ ABS(amount) по type=withdrawal, успешные. БЕЗ manual_withdrawal.",
  "card.tip.field.net_cash": "Чистая касса = кэш-депозиты − выводы (спека казино).",
  "card.tip.field.bonus_cost":
    "Bonus cost = Σ ABS(amount) по bonus/manual_bonus/freespin (успешные, без bonus_conversion).",
  "card.tip.field.dep_failed": "Число неуспешных депозитов (rejected / failed).",
  "card.tip.field.wd_count": "Число завершённых выводов.",
  "card.tip.field.wd_sum": "Сумма завершённых выводов = Σ amount.",
  "card.tip.field.wd_rejected": "Число отклонённых выводов.",
  "card.tip.field.bonus_count": "Число бонусных начислений.",
  "card.tip.field.bonus_sum": "Сумма выданных бонусов.",
  "card.tip.field.primary_payment_method": "Основная платёжка (без campaign-тегов).",
  "card.tip.field.deposit_recency_days": "Дней с последнего депозита.",
  "card.tip.field.bets": "Число ставок (bet + freespins_bet).",
  "card.tip.field.turnover": "Оборот = Σ bet_amount. Сколько игрок поставил всего.",
  "card.tip.field.wins_sum": "Выигрыши = Σ win_amount. Сколько игрок выиграл в игре.",
  "card.tip.field.net": "Net игрока = выигрыши − ставки. + в плюсе / − слил (со стороны ИГРОКА).",
  "card.tip.field.ggr": "GGR казино = ставки − выигрыши = −net. Доход казино от игры (до вычета бонусов).",
  "card.tip.field.avg_bet": "Средняя ставка = avg(bet_amount).",
  "card.tip.field.max_bet": "Максимальная ставка.",
  "card.tip.field.distinct_games": "Сколько разных игр = uniqExact(game_uuid).",
  "card.tip.field.active_days": "Дней с игрой = uniqExact(дата ставки).",
  "card.tip.field.recency_days": "Дней с последней ставки = dateDiff(последняя ставка, сегодня).",
  "card.tip.field.primary_provider": "Основной провайдер (агрегатор) по числу ставок.",
  "card.tip.field.freespin_ratio": "Доля фриспин-ставок = freespins_bets / bets.",
  "card.tip.field.night_share": "Доля ночной игры (час < 6 по Стамбулу) = night_bets / bets.",
  "card.tip.field.bets_per_active_day": "Интенсивность = ставки / активные дни.",
  "card.tip.field.activation_lag_days": "Скорость активации = дней между регистрацией и первой ставкой.",
  "card.tip.field.favourite_game": "Игра с наибольшим числом ставок (основная).",
  "card.tip.field.favourite_game_bets": "Сколько ставок в основной игре.",
  "card.tip.field.game_concentration": "Концентрация = доля ставок в основной игре.",
  "card.tip.field.stuck_game": "Игра, к которой игрок дольше всего возвращался.",
  "card.tip.field.stuck_game_days": "Дней до возврата в эту игру.",
  "card.tip.field.oneshot_games": "Сколько игр брошено после одного дня.",

  // Скрипт перед глазами при звонке (ScriptPeek)
  "card.call.scriptButton": "📋 Скрипт",

  // Рекомендация «когда звонить» (модуль анализа + retry-правило)
  "card.schedule.rec.retry": "🔁 Перезвонить через {hours} ч — в прошлый раз не дозвонились",
  "card.schedule.rec.bestTime": "⭐ Лучшее время: {day} около {hour} (пик активности игрока)",
  "card.schedule.rec.apply": "Взять",
  "card.call.viaButtonOnly": "звонок только кнопкой (номер скрыт)",
  "card.handoff.button": "Назначить WhatsApp",
  "card.handoff.title": "Передать игрока",
  "card.handoff.hint": "Кому передать игрока (WhatsApp-менеджер или руководитель отдела). Он получит игрока в свою работу.",
  "card.handoff.pick": "— получатель —",
  "card.handoff.cancel": "Отмена",
  "card.handoff.confirm": "Передать",
  "card.handoff.done": "Передано: {name}",
} satisfies Record<string, string>;
