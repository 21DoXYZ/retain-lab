/**
 * ru — BASE dictionary. This file is the source of truth for the KEY SET: every
 * key any screen uses must exist here (with a Russian value). en/tr are Partial
 * of this shape and fall back to ru per-key (see ../messages.ts).
 *
 * Convention: flat, dot-namespaced keys `"<area>.<name>"`. Interpolation with
 * `{var}` placeholders — see t("calendar.suggest.activeAt", { day, hour }).
 *
 * How to add strings (any agent): add the key here first (ru value), then
 * optionally translate it in en.ts / tr.ts. Missing/empty translations render
 * the ru value, so the app is never broken by an untranslated key.
 */

export const base = {
  // ── common / shared states ─────────────────────────────────────────────
  "common.retry": "Повторить",
  "common.loadFailed": "Не удалось загрузить",
  "common.saveFailed": "Не удалось сохранить",
  "common.loadFailedDesc": "Попробуйте обновить. Если повторяется — сообщите администратору.",
  "common.accessTitle": "Раздел недоступен для вашей роли",
  "common.accessDesc": "Обратитесь к руководителю, если доступ нужен по работе.",
  "common.dash": "—",

  // ── ветки «нет доступа» серверных page.tsx (рендерит ui/AccessDenied) ────
  // Живут в base, а не в доменных словарях: серверные страницы принадлежат
  // разным доменам, а компонент отказа один — так ключи не расползаются.
  "access.queue.title": "Моя очередь",
  "access.queue.desc":
    "Личная очередь доступна операторам и руководителям ретеншена. Для вашей роли рабочий раздел откроется в меню слева.",
  "access.pool.title": "Пул игроков",
  "access.pool.desc":
    "Распределение игроков доступно главе ретеншена и главам отделов. Для вашей роли рабочий раздел откроется в меню слева.",
  "access.calendar.desc":
    "Раздел доступен операторам и руководителям отделов. Обратитесь к руководителю, если доступ нужен по работе.",
  "access.affiliate.desc":
    "Это личный кабинет внешнего аффилиата. Ваша роль работает с другими разделами — откройте их в меню слева.",

  // ── лаунчер «/» (серверная страница, переводит через getMessages) ────────
  "home.greeting": "Здравствуйте, {name}",
  "home.yourRole": "Ваша роль:",
  "home.leadTail": "Разделы ниже и меню слева отфильтрованы под ваш доступ.",
  "home.sections": "Доступные разделы",
  "home.yourSection": "ваш рабочий раздел",
  "home.empty": "Для вашей роли рабочий раздел откроется в меню слева, когда он будет готов.",

  // ── language switcher ──────────────────────────────────────────────────
  "lang.aria": "Язык интерфейса",

  // ── weekday short names (index 0 = понедельник) ────────────────────────
  "day.0": "Пн",
  "day.1": "Вт",
  "day.2": "Ср",
  "day.3": "Чт",
  "day.4": "Пт",
  "day.5": "Сб",
  "day.6": "Вс",

  // ── calendar ───────────────────────────────────────────────────────────
  "calendar.title": "Календарь звонков",
  "calendar.lead.operator": "Ваш план на сегодня. Просроченные касания — сверху.",
  "calendar.lead.head": "Дисциплина отдела: запланировано / выполнено / просрочено по операторам.",
  "calendar.section.overdue": "Просроченные",
  "calendar.section.today": "Сегодня по времени",
  "calendar.autoplan.title": "Авто-план: игроки без запланированного касания",
  "calendar.autoplan.hint":
    "Система подбирает слот по тепловой карте активности игрока. Подтвердить и создать план можно в карточке игрока.",
  "calendar.summary.title": "Сводка по операторам",
  "calendar.badge.system": "предложено системой",
  "calendar.badge.overdue": "просрочено",
  "calendar.col.time": "Время",
  "calendar.col.player": "Игрок",
  "calendar.col.stage": "Стадия",
  "calendar.col.comment": "Комментарий",
  "calendar.col.suggested": "Рекомендованный слот",
  "calendar.col.operator": "Оператор",
  "calendar.col.planned": "Запланировано",
  "calendar.col.done": "Выполнено",
  "calendar.col.overdue": "Просрочено",
  "calendar.col.total": "Всего",
  "calendar.empty.today.title": "На сегодня звонков не запланировано",
  "calendar.empty.today.desc": "Запланируйте следующее касание в карточке игрока — оно появится здесь.",
  "calendar.empty.autoplan.title": "Все назначенные игроки уже в плане",
  "calendar.empty.autoplan.desc": "Нет назначенных игроков без запланированного касания.",
  "calendar.empty.summary.title": "Нет данных по операторам",
  "calendar.empty.summary.desc": "Как только появятся запланированные звонки, сводка заполнится.",
  "calendar.suggest.activeAt": "обычно активен: {day} ~{hour}:00",
  "calendar.suggest.fallback": "слот по умолчанию (нет данных активности)",
  "calendar.suggest.loading": "подбираем слот…",
  "calendar.openCard": "Открыть карточку",

  // ── affiliate cabinet ──────────────────────────────────────────────────
  "affiliate.title": "Мои игроки",
  "affiliate.lead": "Игроки вашего кода {code}. Стадии и сигналы модели — без сводных цифр казино.",
  "affiliate.col.player": "Игрок",
  "affiliate.col.stage": "Стадия",
  "affiliate.col.vip": "VIP",
  "affiliate.col.country": "Страна",
  "affiliate.col.signal": "Сигнал",
  "affiliate.col.notes": "Заметки",
  "affiliate.empty.title": "Пока нет игроков",
  "affiliate.empty.desc": "Как только за вашим кодом закрепят игроков, они появятся здесь.",
  "affiliate.signal.cooling": "остывает",
  "affiliate.signal.atRisk": "под риском",
  "affiliate.signal.churn": "риск оттока",
  "affiliate.signal.active": "активен",
  "affiliate.signal.dormant": "спит",
  "affiliate.signal.churned": "ушёл",
  "affiliate.signal.new": "новый",
  "affiliate.signal.unknown": "—",
  "affiliate.card.title": "Карточка игрока",
  "affiliate.card.loadError": "Не удалось загрузить карточку",
  "affiliate.card.stage": "Стадия",
  "affiliate.card.vip": "VIP-уровень",
  "affiliate.card.recommendation": "Рекомендация модели",
  "affiliate.card.churnRisk": "Риск оттока",
  "affiliate.card.recommendedAction": "Рекоменд. действие",
  "affiliate.card.offer": "Оффер",
  "affiliate.card.action": "Действие",
  "affiliate.card.contact": "Контакт",
  "affiliate.card.noContact": "нет контакта",
  "affiliate.card.signal": "Сигнал модели",
  "affiliate.card.noSignal": "Сигнал модели недоступен (нет свежих данных активности).",
  "affiliate.card.contactNone": "Контакт игрока в системе отсутствует — работайте по своим каналам.",
  "affiliate.card.loading": "Загружаем сигналы…",
  "affiliate.call": "Позвонить",
  "affiliate.calling": "Звоним…",
  "affiliate.callStarted": "Звонок инициирован",
  "affiliate.callFailed": "Не удалось инициировать звонок",
  "affiliate.notes.title": "Заметки",
  "affiliate.notes.placeholder": "Что обсудили, договорённости, по каким каналам…",
  "affiliate.notes.save": "Сохранить заметку",
  "affiliate.notes.saving": "Сохраняем…",
  "affiliate.notes.empty": "Заметок пока нет.",
  "affiliate.notes.saveFailed": "Не удалось сохранить заметку",
  "affiliate.notes.loadFailed": "Не удалось загрузить заметки",
  "affiliate.notes.you": "вы",
  "affiliate.notes.team": "команда казино",
  "affiliate.close": "Закрыть",
  "affiliate.open": "Открыть",

  // ── /login — вне (app), собственный I18nProvider в app/(auth)/layout.tsx ──
  "login.tagline": "Колл-центр · аналитика",
  "login.title": "Вход в систему",
  "login.subtitle": "Войдите под своей учётной записью",
  "login.emailLabel": "Логин (e-mail)",
  "login.passwordLabel": "Пароль",
  "login.submit": "Войти",
  "login.invalidCredentials": "Неверный логин или пароль",
  "login.blocked": "Учётная запись заблокирована. Обратитесь к руководителю.",

  // Ошибки транспорта flaskFetch (lib/api.ts) — наша копирайт-строка,
  // в отличие от текста ошибки, пришедшего от бэкенда.
  "api.error.server": "Ошибка сервера ({status})",
  "api.error.badResponse": "Некорректный ответ сервера",
  "api.error.failed": "Запрос не выполнен ({status})",
  "api.error.network": "Сеть недоступна",
  "compare.toggle": "Сравнить с прошлым периодом",
  "compare.caption": "Сравнение с {from} — {to} (предыдущий период такой же длины).",
  "compare.vsPrev": "к прошлому периоду",
  "compare.noBase": "нет базы",
  "money.overview.withdrawals.subRatio": "{pct}% от депозитов (выводы/депозиты)",
  "geo.title": "По странам: выводы / депозиты",
  "geo.col.country": "Страна",
  "geo.col.deposits": "Депозиты",
  "geo.col.withdrawals": "Выводы",
  "geo.col.ratio": "Выв/Деп",
  "geo.col.depositors": "Депозиторов",
  "geo.ratioHint": "Ratio выводы/депозиты — метрика здоровья гео: сколько внесённого утекает обратно. Выше ~67% (красным) — гео близко к убыточному.",
  "ext.title": "Внутренние",
  "ext.accent": "номера",
  "ext.lead": "Сопоставьте каждому оператору его Tegsoft-extension (SIP-номер). Звонок идёт через интеграционный аккаунт entegreapi + этот extension. Токен опционален (нужен, только если у учётки оператора включён отдельный API-доступ).",
  "ext.warnMissing": "{n} оператор(ов) без extension — они не смогут звонить.",
  "ext.tableCaption": "Операторы и их номера",
  "ext.colOperator": "Оператор",
  "ext.colRole": "Роль",
  "ext.colExt": "Extension",
  "ext.placeholder": "напр. 2001",
  "ext.save": "Сохранить",
  "ext.clear": "Сбросить",
  "ext.colToken": "Токен TG-Soft",
  "ext.tokenKeep": "оставьте пустым — не менять",
  "ext.tokenNew": "вставьте токен",
  "ext.tokenSet": "✓ задан",
  "ext.tokenNone": "не задан",
  "ext.colLogin": "Логин (usercode)",
  "ext.colPassword": "Пароль",
  "ext.loginPlaceholder": "логин в Tegsoft",
  "ext.pwKeep": "оставьте пустым — не менять",
  "ext.pwNew": "пароль оператора",
  "ext.pwSet": "✓ задан",
  "ext.pwNone": "не задан",
  "ext.reset": "Сбросить",
  "ext.resetConfirm": "Сбросить ext, логин и пароль оператора «{name}»?",
  "ext.test": "Тест",
  "ext.testPrompt": "Номер для тестового звонка (цифры/+, напр. 905551234567):",
  "ext.testOk": "Тест-звонок запущен: поднимаем ext {ext}, соединяем с {dest}. Проверьте телефон.",
} satisfies Record<string, string>;

