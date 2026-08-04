/**
 * ru · домен «automation» — конструктор сегментов (W4-T2). Ключи "automation.*".
 * ru — ИСТОЧНИК КЛЮЧЕЙ (ключ обязан быть здесь, иначе не MessageKey). Переводы —
 * en/automation.ts, tr/automation.ts. Метки полей и разделов приходят из бэкенда
 * (GET /segments/fields) — здесь только «хром» экрана: кнопки, операторы, статусы.
 */
export const automation = {
  // ── экран / список ──
  "automation.title": "Сегменты",
  "automation.lead":
    "Конструктор аудиторий: соберите условия из каталога полей — И/ИЛИ группами — и увидьте, сколько игроков подходит прямо сейчас.",
  "automation.readOnlyPill": "только просмотр",
  "automation.btn.create": "Создать сегмент",
  "automation.btn.fromTemplate": "Из шаблона",

  "automation.list.showArchived": "Показать архив",
  "automation.list.col.name": "Название",
  "automation.list.col.sysName": "Системное имя",
  "automation.list.col.count": "Участников",
  "automation.list.col.recomputed": "Пересчитан",
  "automation.list.col.author": "Автор",
  "automation.list.col.type": "Тип",
  "automation.list.col.status": "Статус",
  "automation.list.badge.trigger": "триггерный",
  "automation.list.badge.scheduled": "суточный",
  "automation.list.badge.archived": "в архиве",
  "automation.list.badge.active": "активен",
  "automation.list.author.system": "—",
  "automation.list.recomputed.never": "не считался",
  "automation.list.recomputed.now": "менее часа назад",
  "automation.list.recomputed.hours": "{n} ч назад",
  "automation.list.recomputed.days": "{n} дн назад",

  "automation.empty.title": "Ещё нет сегментов",
  "automation.empty.desc":
    "Создайте первый сегмент вручную или клонируйте готовый шаблон — кампанию, архетип или RFM-группу.",
  "automation.error.title": "Не удалось загрузить сегменты",
  "automation.error.desc": "Проверьте соединение с бэкендом и повторите.",

  // ── шаблоны (пресеты) ──
  "automation.presets.title": "Шаблоны сегментов",
  "automation.presets.desc": "Готовые определения — клонируйте и доработайте под свою задачу.",
  "automation.presets.empty": "Шаблоны недоступны.",
  "automation.presets.offer": "Оффер: {offer}",
  "automation.presets.clone": "Клонировать",
  "automation.presets.kind.campaign": "Кампания",
  "automation.presets.kind.archetype": "Архетип",
  "automation.presets.kind.rfm": "RFM",

  // ── редактор ──
  "automation.editor.newTitle": "Новый сегмент",
  "automation.editor.editTitle": "Редактирование сегмента",
  "automation.editor.cloneTitle": "Клонирование сегмента",
  "automation.editor.back": "← К списку",
  "automation.editor.readonly": "У вас нет прав на изменение сегментов — доступен только просмотр.",
  "automation.editor.section.props": "Свойства",
  "automation.editor.section.conditions": "Условия",

  "automation.editor.field.name": "Название",
  "automation.editor.field.namePlaceholder": "Напр.: Остывающие с 1 депозитом",
  "automation.editor.field.sysName": "Системное имя",
  "automation.editor.field.sysNameHint": "латиница, цифры и _, начинается с буквы (3–64)",
  "automation.editor.field.sysNameError": "Только латиница, цифры и _, начинается с буквы, 3–64 символа",
  "automation.editor.field.description": "Описание",
  "automation.editor.field.descriptionPlaceholder": "Зачем этот сегмент и как используется",
  "automation.editor.field.schedule": "Время пересчёта",
  "automation.editor.field.scheduleHint": "ежедневно, время Стамбула",
  "automation.editor.field.trigger": "Триггерный",
  "automation.editor.field.triggerLabel": "real-time вход",
  "automation.editor.field.triggerHint": "вход считается каждый цикл раннера, а не раз в сутки",

  "automation.editor.rootGroup": "Игрок подходит под ВСЕ условия (И)",
  "automation.editor.anyGroup": "Хотя бы одно из (ИЛИ)",
  "automation.editor.emptyConditions":
    "Условий пока нет — сегмент охватит всех игроков. Добавьте хотя бы одно.",
  "automation.editor.add.condition": "+ Условие",
  "automation.editor.add.notSegment": "+ НЕ в сегменте",
  "automation.editor.add.event": "+ Событие",
  "automation.editor.add.group": "+ Группа ИЛИ",
  "automation.editor.removeRow": "Удалить условие",
  "automation.editor.removeGroup": "Удалить группу",

  "automation.editor.preview.count": "Сейчас подходит {n} игроков",
  "automation.editor.preview.loading": "Считаем…",
  "automation.editor.preview.error": "Ошибка условия: {msg}",

  "automation.editor.btn.save": "Сохранить",
  "automation.editor.btn.saveCreate": "Создать",
  "automation.editor.btn.clone": "Клонировать",
  "automation.editor.btn.export": "Экспорт CSV",
  "automation.editor.btn.archive": "Архивировать",
  "automation.editor.cancel": "Отмена",
  "automation.editor.save.nameRequired": "Укажите название сегмента",
  "automation.editor.save.failed": "Не удалось сохранить сегмент",
  "automation.editor.export.error": "Не удалось выгрузить файл.",
  "automation.editor.archive.confirmTitle": "Архивировать сегмент?",
  "automation.editor.archive.confirmBody":
    "Сегмент «{name}» уйдёт в архив и перестанет пересчитываться. Восстановить можно в базе.",
  "automation.editor.archive.confirm": "Архивировать",

  // ── строка условия ──
  "automation.row.field": "Поле",
  "automation.row.fieldPlaceholder": "— выберите поле —",
  "automation.row.op": "Оператор",
  "automation.row.value": "Значение",
  "automation.row.unavailable": "· ждёт события API",
  "automation.row.between.and": "и",
  "automation.row.days": "дней",
  "automation.row.pct": "%",
  "automation.row.flag.yes": "да",
  "automation.row.flag.no": "нет",
  "automation.row.isNull": "(без значения)",
  "automation.row.enum.add": "добавить значение",
  "automation.row.enum.placeholder": "— добавить —",
  "automation.row.enum.empty": "ничего не выбрано",
  "automation.row.list.placeholder": "значения через запятую",
  "automation.row.notSegment.label": "НЕ входит в сегмент",
  "automation.row.notSegment.placeholder": "— выберите сегмент —",
  "automation.row.notSegment.none": "нет других сегментов",
  "automation.row.event.label": "Событие",
  "automation.row.event.type": "Тип события",
  "automation.row.event.within": "за посл. дней",
  "automation.row.event.op": "Оператор",
  "automation.row.event.count": "раз",

  // ── операторы условий (по типу поля) ──
  "automation.op.eq": "равно",
  "automation.op.ne": "не равно",
  "automation.op.gt": "больше",
  "automation.op.lt": "меньше",
  "automation.op.between": "в диапазоне",
  "automation.op.top_pct": "топ N%",
  "automation.op.before": "до даты",
  "automation.op.after": "после даты",
  "automation.op.days_ago_gt": "давнее чем (дней)",
  "automation.op.days_ago_lt": "новее чем (дней)",
  "automation.op.in": "любое из",
  "automation.op.not_in": "ни одно из",
  "automation.op.is": "равно",
  "automation.op.is_null": "не заполнено",
  "automation.op.contains": "содержит",

  // ── операторы события ──
  "automation.eop.gte": "≥",
  "automation.eop.gt": ">",
  "automation.eop.lte": "≤",
  "automation.eop.lt": "<",
  "automation.eop.eq": "=",
  "automation.eop.ne": "≠",

  // ── типы событий ──
  "automation.event.deposit": "депозит",
  "automation.event.withdrawal": "вывод",
  "automation.event.bonus": "бонус",
  "automation.event.bet": "ставка",
  "automation.event.session_start": "начало сессии",
  "automation.event.session_end": "конец сессии",

  // ══════════════════════════════════════════════════════════════════════════
  // Цепочки автоматизации (W4-T5) — ключи "automation.chains.*"
  // ══════════════════════════════════════════════════════════════════════════
  "automation.chains.title": "Цепочки автоматизации",
  "automation.chains.lead":
    "Сценарии касаний: триггер → шаги (бонус, сообщение, задача, тег, ожидание, условие) с контрольной группой и аналитикой по узлам.",
  "automation.chains.readOnlyPill": "только просмотр",
  "automation.chains.btn.create": "Создать цепочку",
  "automation.chains.tab.chains": "Цепочки",
  "automation.chains.tab.templates": "Шаблоны сообщений",
  "automation.chains.error.title": "Не удалось загрузить цепочки",
  "automation.chains.error.desc": "Проверьте соединение с бэкендом и повторите.",

  // ── список ──
  "automation.chains.list.col.name": "Название",
  "automation.chains.list.col.status": "Статус",
  "automation.chains.list.col.version": "Версия",
  "automation.chains.list.col.enrollments": "В цепочке сейчас",
  "automation.chains.list.col.updated": "Обновлена",
  "automation.chains.list.col.actions": "Действия",
  "automation.chains.list.badge.draft": "черновик",
  "automation.chains.list.search": "Поиск по названию…",
  "automation.chains.list.action.activate": "Активировать",
  "automation.chains.list.action.pause": "Пауза",
  "automation.chains.list.action.clone": "Клонировать",
  "automation.chains.list.action.archive": "Архив",

  "automation.chains.empty.title": "Пока нет цепочек",
  "automation.chains.empty.desc":
    "Создайте первую цепочку: выберите триггер-сегмент и соберите шаги сверху вниз.",

  // ── статусы ──
  "automation.chains.status.draft": "черновик",
  "automation.chains.status.active": "активна",
  "automation.chains.status.paused": "на паузе",
  "automation.chains.status.archived": "в архиве",

  // ── создание / клон / подтверждения (список) ──
  "automation.chains.create.title": "Новая цепочка",
  "automation.chains.create.nameLabel": "Название",
  "automation.chains.create.namePlaceholder": "Напр.: 1-й → 2-й депозит",
  "automation.chains.create.descLabel": "Описание",
  "automation.chains.create.descPlaceholder": "Для чего эта цепочка",
  "automation.chains.create.confirm": "Создать и открыть",
  "automation.chains.clone.title": "Клонировать цепочку",
  "automation.chains.clone.nameLabel": "Название новой цепочки",
  "automation.chains.clone.confirm": "Клонировать",
  "automation.chains.confirm.activate.title": "Активировать цепочку?",
  "automation.chains.confirm.activate.confirm": "Активировать",
  "automation.chains.confirm.activate.bodyDraft":
    "Цепочка «{name}» войдёт в бой и создаст версию {n}. Игроки, уже находящиеся в цепочке, продолжат по прежней версии.",
  "automation.chains.confirm.activate.bodyResume":
    "Возобновить активную рассылку «{name}» по версии {n}?",
  "automation.chains.confirm.pause.title": "Поставить на паузу?",
  "automation.chains.confirm.pause.confirm": "Пауза",
  "automation.chains.confirm.pause.body":
    "Цепочка «{name}» встанет на паузу: новые игроки перестанут входить. Уже вошедшие продолжат.",
  "automation.chains.confirm.archive.title": "Архивировать цепочку?",
  "automation.chains.confirm.archive.confirm": "Архивировать",
  "automation.chains.confirm.archive.body":
    "Цепочка «{name}» уйдёт в архив и больше не будет исполняться. Редактирование станет недоступно.",

  // ── редактор: шапка / вкладки ──
  "automation.chains.editor.title": "Цепочка",
  "automation.chains.editor.loading": "Загрузка цепочки…",
  "automation.chains.editor.back": "← К списку",
  "automation.chains.editor.readonly":
    "У вас нет прав на изменение цепочек — доступен только просмотр.",
  "automation.chains.editor.archivedNote": "Цепочка в архиве — редактирование недоступно.",
  "automation.chains.editor.versionPill": "версия {n}",
  "automation.chains.tab.editor": "Редактор",
  "automation.chains.tab.stats": "Статистика",

  // ── редактор: секции ──
  "automation.chains.editor.section.props": "Свойства",
  "automation.chains.editor.section.trigger": "Триггер",
  "automation.chains.editor.section.goal": "Контроль и цель",
  "automation.chains.editor.section.nodes": "Шаги",

  // ── редактор: поля ──
  "automation.chains.editor.field.name": "Название",
  "automation.chains.editor.field.namePlaceholder": "Напр.: 1-й → 2-й депозит",
  "automation.chains.editor.field.nameLocked": "имя меняется только у черновика",
  "automation.chains.editor.field.description": "Описание",
  "automation.chains.editor.field.descriptionPlaceholder": "Для чего эта цепочка",
  "automation.chains.editor.field.controlPct": "Контрольная группа, %",
  "automation.chains.editor.field.controlPctHint":
    "0–50, дефолт 16 — им НЕ шлём касания, чтобы измерить эффект",
  "automation.chains.editor.field.goalEvent": "Целевое событие",
  "automation.chains.editor.field.attribution": "Окно атрибуции, дней",
  "automation.chains.editor.field.attributionHint": "1–90 — за сколько дней засчитываем цель",

  // ── редактор: шаги ──
  "automation.chains.editor.emptyNodes":
    "Шагов пока нет. Добавьте первый шаг — действие, ожидание или условие.",
  "automation.chains.editor.add.action": "+ Действие",
  "automation.chains.editor.add.wait": "+ Ожидание",
  "automation.chains.editor.add.condition": "+ Условие",
  "automation.chains.editor.incompleteConditions":
    "Заполните условие в шагах: {ids} — иначе цепочку нельзя активировать.",

  // ── редактор: кнопки / заметки ──
  "automation.chains.editor.btn.saveDraft": "Сохранить черновик",
  "automation.chains.editor.btn.activate": "Активировать",
  "automation.chains.editor.btn.pause": "Пауза",
  "automation.chains.editor.btn.clone": "Клонировать",
  "automation.chains.editor.btn.archive": "Архивировать",
  "automation.chains.editor.cancel": "Отмена",
  "automation.chains.editor.savedNote": "Черновик сохранён — версия {n}.",
  "automation.chains.editor.pausedNote": "Цепочка поставлена на паузу.",
  "automation.chains.editor.saveFailed": "Не удалось сохранить цепочку",
  "automation.chains.editor.activateFailed": "Не удалось активировать цепочку",
  "automation.chains.editor.cloneFailed": "Не удалось клонировать цепочку",

  // ── редактор: модалки ──
  "automation.chains.editor.activate.title": "Активировать цепочку?",
  "automation.chains.editor.activate.confirm": "Активировать",
  "automation.chains.editor.activate.body":
    "Цепочка войдёт в бой и создаст версию {n}. Игроки, уже находящиеся в цепочке, продолжат по прежней версии.",
  "automation.chains.editor.archive.title": "Архивировать цепочку?",
  "automation.chains.editor.archive.confirm": "Архивировать",
  "automation.chains.editor.archive.body": "Цепочка «{name}» уйдёт в архив и перестанет исполняться.",
  "automation.chains.editor.clone.title": "Клонировать цепочку",
  "automation.chains.editor.clone.nameLabel": "Название новой цепочки",
  "automation.chains.editor.clone.confirm": "Клонировать",

  // ── триггер ──
  "automation.chains.trigger.kind": "Тип триггера",
  "automation.chains.trigger.kind.segment": "Сегмент",
  "automation.chains.trigger.kind.event": "Событие",
  "automation.chains.trigger.kind.schedule": "Расписание",
  "automation.chains.trigger.phase3b": "фаза 3б",
  "automation.chains.trigger.segment": "Сегмент входа",
  "automation.chains.trigger.segment.placeholder": "— выберите сегмент —",
  "automation.chains.trigger.segment.none": "Сначала создайте сегмент на вкладке «Сегменты».",
  "automation.chains.trigger.reentry": "Повторный вход, дней",
  "automation.chains.trigger.reentryHint": "0–365 — через сколько дней игрок может войти снова",
  "automation.chains.trigger.event": "Тип события",
  "automation.chains.trigger.cron": "Расписание (cron)",
  "automation.chains.trigger.event.deposit": "депозит",
  "automation.chains.trigger.event.deposit_failed": "неудачный депозит",
  "automation.chains.trigger.event.bet": "ставка",
  "automation.chains.trigger.event.login": "вход в аккаунт",
  "automation.chains.trigger.event.session_start": "начало сессии",
  "automation.chains.trigger.event.session_end": "конец сессии",
  "automation.chains.trigger.event.cashier_opened": "открыл кассу",

  // ── узел: шапка ──
  "automation.chains.node.kind.action": "Действие",
  "automation.chains.node.kind.wait": "Ожидание",
  "automation.chains.node.kind.condition": "Условие",
  "automation.chains.node.moveUp": "Выше",
  "automation.chains.node.moveDown": "Ниже",
  "automation.chains.node.remove": "Удалить шаг",

  // ── узел: действие ──
  "automation.chains.action.label": "Что делаем",
  "automation.chains.action.bonus_grant": "Начислить бонус",
  "automation.chains.action.send_message": "Отправить сообщение",
  "automation.chains.action.desk_task": "Задача в Пульт",
  "automation.chains.action.player_tag": "Поставить тег",
  "automation.chains.action.bonus.label": "Бонус",
  "automation.chains.action.bonus.hint": "«По модели» подберёт бонус автоматически (player_bonus_ml)",
  "automation.chains.bonus.ml_recommended": "По модели (авто)",
  "automation.chains.bonus.first_deposit_bonus": "Бонус на 1-й депозит",
  "automation.chains.bonus.second_deposit_reload": "Релоад на 2-й депозит",
  "automation.chains.bonus.vip_offer": "VIP-оффер",
  "automation.chains.bonus.freespins": "Фриспины",
  "automation.chains.bonus.reload_cashback": "Кэшбэк-релоад",
  "automation.chains.action.channel.label": "Канал",
  "automation.chains.channel.casino_webhook": "Вебхук казино",
  "automation.chains.channel.email": "Email",
  "automation.chains.channel.telegram": "Telegram",
  "automation.chains.action.template.label": "Шаблон",
  "automation.chains.action.template.placeholder": "— выберите шаблон —",
  "automation.chains.action.template.none":
    "Нет шаблонов для этого канала — создайте на вкладке «Шаблоны сообщений».",
  "automation.chains.action.params.label": "Параметры подстановки",
  "automation.chains.action.params.hint": "Значения для плейсхолдеров шаблона. Доступно: {vars}",
  "automation.chains.action.params.add": "+ Параметр",
  "automation.chains.action.params.empty": "Без параметров",
  "automation.chains.action.params.key": "ключ",
  "automation.chains.action.params.value": "значение",
  "automation.chains.action.reason.label": "Причина назначения",
  "automation.chains.action.reason.hint": "Зачем передаём игрока живому оператору на Пульт",
  "automation.chains.action.reason.placeholder": "Напр.: VIP на грани оттока",
  "automation.chains.action.tag.label": "Тег",
  "automation.chains.action.tag.hint": "Метка игрока для последующей сегментации",
  "automation.chains.action.tag.placeholder": "Напр.: chain_winback",

  // ── узел: ожидание ──
  "automation.chains.wait.mode.label": "Режим ожидания",
  "automation.chains.wait.mode.hint":
    "фикс — на N часов; событие — до события/таймаута; по модели — медиана паузы (ML)",
  "automation.chains.waitMode.fixed": "Фиксированное",
  "automation.chains.waitMode.event": "До события",
  "automation.chains.waitMode.ml": "По модели",
  "automation.chains.wait.hours.fixed": "Часов ожидания",
  "automation.chains.wait.hours.fallback": "Фолбэк, часов",
  "automation.chains.wait.window.label": "Окно отправки",
  "automation.chains.wait.window.hint": "Слать только в это время (часовой пояс игрока)",
  "automation.chains.wait.window.enable": "Ограничить окном",
  "automation.chains.wait.window.from": "с",
  "automation.chains.wait.window.to": "до",

  // ── узел: условие ──
  "automation.chains.condition.if": "Если игрок подходит под условие:",
  "automation.chains.condition.then": "то",
  "automation.chains.condition.else": "иначе",
  "automation.chains.condition.target.next": "следующий шаг",
  "automation.chains.condition.target.exitConverted": "выход · цель достигнута",
  "automation.chains.condition.target.exit": "выход",

  // ── статистика ──
  "automation.chains.stats.error.title": "Не удалось загрузить статистику",
  "automation.chains.stats.error.desc": "Проверьте соединение и повторите.",
  "automation.chains.stats.pending.title": "Статистики пока нет",
  "automation.chains.stats.pending.desc":
    "Статистика появится после запуска исполнителя цепочек.",
  "automation.chains.stats.col.node": "Шаг",
  "automation.chains.stats.col.entered": "Вошло",
  "automation.chains.stats.col.passed": "Прошло",
  "automation.chains.stats.col.dropped": "Выпало",
  "automation.chains.stats.col.reasons": "Причины выпадения",
  "automation.chains.stats.goal.main": "Конверсия · основная",
  "automation.chains.stats.goal.control": "Конверсия · контроль",
  "automation.chains.stats.goal.uplift": "Аплифт",
  "automation.chains.stats.goal.sub": "{conv} из {n} игроков",
  "automation.chains.stats.goal.upliftSub": "основная минус контрольная",

  // ── шаблоны сообщений ──
  "automation.chains.tpl.lead":
    "Шаблоны сообщений с языковыми версиями (ru/en/tr). Подставляются шагом «Отправить сообщение».",
  "automation.chains.tpl.create": "Создать шаблон",
  "automation.chains.tpl.col.name": "Название",
  "automation.chains.tpl.col.channel": "Канал",
  "automation.chains.tpl.col.langs": "Языки",
  "automation.chains.tpl.col.updated": "Обновлён",
  "automation.chains.tpl.empty.title": "Пока нет шаблонов",
  "automation.chains.tpl.empty.desc":
    "Создайте шаблон, чтобы использовать его в шаге «Отправить сообщение».",
  "automation.chains.tpl.error.title": "Не удалось загрузить шаблоны",
  "automation.chains.tpl.newTitle": "Новый шаблон",
  "automation.chains.tpl.editTitle": "Редактирование шаблона",
  "automation.chains.tpl.field.name": "Название",
  "automation.chains.tpl.field.namePlaceholder": "Напр.: Приветствие 1-й депозит",
  "automation.chains.tpl.field.channel": "Канал",
  "automation.chains.tpl.field.bodyPlaceholder": "Текст сообщения на выбранном языке",
  "automation.chains.tpl.field.varsHint": "Плейсхолдеры: {vars}",
  "automation.chains.tpl.save": "Сохранить",
  "automation.chains.tpl.delete": "Удалить",
  "automation.chains.tpl.delete.confirm": "Удалить шаблон «{name}»? Действие необратимо.",
  "automation.chains.tpl.nameRequired": "Укажите название шаблона",
  "automation.chains.tpl.saveFailed": "Не удалось сохранить шаблон",
} satisfies Record<string, string>;
