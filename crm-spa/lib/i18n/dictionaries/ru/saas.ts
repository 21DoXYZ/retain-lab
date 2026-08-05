/**
 * ru · домен «saas» — экраны SaaS-пресета Revenue Autopilot (leak-audit и далее).
 * Базовые (русские) строки — источник ключей; переводы en/saas.ts, tr/saas.ts.
 */
export const saas = {
  "nav.leakAudit": "Утечки выручки",

  "saas.leak.title": "Аудит утечек",
  "saas.leak.lead":
    "Где подписочная выручка утекает прямо сейчас - несписания, мёртвые триалы, тихие отмены, недобор апгрейдов.",
  "saas.leak.headline": "Вы теряете ~{amount}/мес",
  "saas.leak.dunning": "Несписания (dunning)",
  "saas.leak.dunningSub": "{count} юзеров - MRR под угрозой сейчас",
  "saas.leak.silent": "Тихие отмены (30 дней)",
  "saas.leak.silentSub": "{count} ушли без попытки удержания",
  "saas.leak.upgrades": "Недобор апгрейдов",
  "saas.leak.upgradesSub": "{count} power-юзеров у лимита плана",
  "saas.leak.deadTrials": "Мёртвые триалы",
  "saas.leak.deadTrialsSub": "{count} истекли без оплаты - потенциал",

  "nav.uplift": "Инкремент кампаний",

  "saas.uplift.title": "Uplift-отчёт",
  "saas.uplift.lead":
    "Честный замер: конверсия target против holdout по каждой кампании - в долларах инкремента.",
  "saas.uplift.total": "Инкремент за период: {amount}",
  "saas.uplift.col.campaign": "Кампания",
  "saas.uplift.col.target": "Target",
  "saas.uplift.col.holdout": "Holdout",
  "saas.uplift.col.check": "Средний чек",
  "saas.uplift.col.incremental": "Инкремент",
  "saas.uplift.col.goal": "Цель",
  "saas.uplift.na": "n/a - пустой holdout",
  "saas.uplift.groupN": "n={n}",
  "saas.uplift.empty.title": "Отчётов ещё нет",
  "saas.uplift.empty.desc": "Первый uplift-отчёт появится после недельного прогона кампаний (Пн 08:00).",

  "saas.home.tagline":
    "Revenue Autopilot следит за каждым юзером, сам шлёт нужное касание и честно меряет инкремент. Начни с трёх экранов ниже.",
  "saas.home.kpi.mrr": "MRR",
  "saas.home.kpi.leak": "Утекает в месяц",
  "saas.home.kpi.users": "Юзеров под наблюдением",
  "saas.home.kpi.atRisk": "Под риском сейчас",
  "saas.home.kpi.atRiskSub": "dunning + остывающие",
  "saas.home.start": "С чего начать",
  "saas.home.start.leak.title": "Где утекают деньги",
  "saas.home.start.leak.desc": "Несписания, тихие отмены, мёртвые триалы - в долларах за месяц.",
  "saas.home.start.users.title": "Юзеры и стадии",
  "saas.home.start.users.desc": "Каждый юзер: стадия жизненного цикла и рекомендованное действие.",
  "saas.home.start.uplift.title": "Что заработали кампании",
  "saas.home.start.uplift.desc": "Конверсия против контрольной группы - честный инкремент в $.",
  "saas.home.machine": "Автопилот сейчас",
  "saas.home.machine.body":
    "{active} юзеров в кампаниях · {holdout} в контроле · {touches} касаний за 7 дней · режим dry-run (письма не уходят, пока не включишь автопилот)",
  "saas.home.setup": "Подключение",
  "saas.home.setup.stripe": "Stripe клиента",
  "saas.home.setup.stripe.on": "подключён",
  "saas.home.setup.stripe.off": "демо-данные - жду ключи",
  "saas.home.setup.snippet": "Сниппет на сайте",
  "saas.home.setup.snippet.on": "события идут",
  "saas.home.setup.snippet.off": "не установлен",
  "saas.home.setup.autopilot": "Автопилот",
  "saas.home.setup.autopilot.off": "dry-run (безопасно)",
  "saas.home.allSections": "Все разделы",

  "nav.saasOffers": "Офферы",

  "saas.users.title": "Юзеры",
  "saas.users.lead": "Каждый юзер: стадия, рекомендованное действие, ценность на кону и скоры.",
  "saas.users.all": "Все",
  "saas.users.col.user": "Юзер",
  "saas.users.col.plan": "План",
  "saas.users.col.mrr": "MRR",
  "saas.users.col.stage": "Стадия",
  "saas.users.col.action": "Действие",
  "saas.users.col.atStake": "На кону",
  "saas.users.col.churn": "P(churn)",
  "saas.users.col.ltv": "LTV",
  "saas.users.col.lastSeen": "Был(а)",
  "saas.users.empty.title": "Юзеров пока нет",
  "saas.users.empty.desc": "Подключи Stripe и сниппет - юзеры появятся здесь со стадиями и действиями.",

  "saas.offers.title": "Офферы",
  "saas.offers.lead": "Каталог стимулов: что даём, чем исполняем, лимиты и сколько раз выдано. Контроль {pct}% на каждую кампанию.",
  "saas.offers.col.offer": "Оффер",
  "saas.offers.col.executor": "Исполнитель",
  "saas.offers.col.monetary": "Монетарный",
  "saas.offers.col.cost": "COGS",
  "saas.offers.col.limit": "Лимит/30д",
  "saas.offers.col.issued": "Выдано",
  "saas.offers.col.holdout": "Holdout",
  "saas.offers.col.rejected": "Отбито",
  "saas.offers.yes": "да",
  "saas.offers.no": "нет",

  "nav.channelsSetup": "Каналы",

  "saas.channels.title": "Каналы",
  "saas.channels.lead":
    "Каждое касание уходит от имени вашего бренда: письма с вашего поддомена, SMS и Viber с вашего имени отправителя, Telegram через вашего бота. Инфраструктура и доставка - на нас.",
  "saas.channels.col.contacts": "Контакты",
  "saas.channels.col.consented": "С согласием",

  "saas.channels.name.email": "Email",
  "saas.channels.name.sms": "SMS",
  "saas.channels.name.viber": "Viber",
  "saas.channels.name.telegram": "Telegram",
  "saas.channels.name.whatsapp": "WhatsApp",

  "saas.channels.state.active": "подключён",
  "saas.channels.state.pending_dns": "ждём DNS",
  "saas.channels.state.pending_approval": "на регистрации",
  "saas.channels.state.awaiting_provider": "ждёт платформу",
  "saas.channels.state.sender_needed": "укажите отправителя",
  "saas.channels.state.not_connected": "не подключён",
  "saas.channels.state.coming_soon": "скоро",

  "saas.channels.copy": "Копировать",
  "saas.channels.copied": "Скопировано",

  "saas.channels.email.domainLabel": "Поддомен отправки",
  "saas.channels.email.domainHint":
    "Отдельный поддомен вашего домена, например mail.вашбренд.com - письма подписываются им, основной домен не затрагивается.",
  "saas.channels.email.connect": "Подключить",
  "saas.channels.email.awaitingNote":
    "Домен зафиксирован. Платформа завершает настройку почтового провайдера - DNS-записи появятся здесь.",
  "saas.channels.email.dnsLead":
    "Добавьте эти записи в DNS вашего домена и нажмите «Проверить DNS». Обновление занимает от минут до пары часов.",
  "saas.channels.email.dns.type": "Тип",
  "saas.channels.email.dns.name": "Имя",
  "saas.channels.email.dns.value": "Значение",
  "saas.channels.email.check": "Проверить DNS",
  "saas.channels.email.verifiedNote":
    "Домен подтверждён. Укажите имя и адрес «От кого» - с него уйдут все письма.",
  "saas.channels.email.fromLabel": "От кого",
  "saas.channels.email.senderName": "Имя отправителя",
  "saas.channels.email.saveSender": "Сохранить отправителя",

  "saas.channels.msg.label": "Имя отправителя",
  "saas.channels.msg.hint":
    "Альфа-имя - то, что получатель видит вместо номера (латиница/цифры, до 11 знаков). Регистрируем у оператора мы.",
  "saas.channels.msg.request": "Запросить",
  "saas.channels.msg.pendingNote":
    "Имя на регистрации у оператора - обычно 1-3 рабочих дня. Канал включится автоматически.",
  "saas.channels.msg.awaitingNote": "Имя подтверждено. Платформа завершает настройку провайдера.",

  "saas.channels.tg.step1": "Откройте @BotFather в Telegram и командой /newbot создайте бота с именем и аватаром вашего продукта.",
  "saas.channels.tg.step2": "Скопируйте токен из ответа BotFather.",
  "saas.channels.tg.step3": "Вставьте токен сюда - мы проверим бота и включим приём подписок.",
  "saas.channels.tg.connect": "Подключить бота",
  "saas.channels.tg.linkLead":
    "Дайте юзерам эту ссылку (подставив их ID) - нажатие Start подписывает их на уведомления с согласием:",
  "saas.channels.tg.disconnect": "Отключить",

  "saas.channels.wa.note":
    "WhatsApp Business требует верификации вашего бизнеса в Meta (WABA). Онбординг ведём мы - напишите нам, когда канал нужен.",

  "saas.channels.err.invalid_domain": "Некорректный домен - нужен вид mail.вашбренд.com.",
  "saas.channels.err.email_not_on_domain": "Адрес должен быть на подключённом поддомене.",
  "saas.channels.err.no_domain": "Сначала подключите поддомен отправки.",
  "saas.channels.err.telegram_invalid_token": "Telegram не принял токен - проверьте, что скопирован целиком.",
  "saas.channels.err.invalid_sms_sender": "Имя: латиница/цифры, 2-11 знаков.",
  "saas.channels.err.invalid_viber_sender": "Имя: латиница/цифры, 2-11 знаков.",
  "saas.channels.err.resend_not_configured": "Почтовый провайдер ещё не настроен платформой.",
  "saas.channels.err.generic": "Не получилось - попробуйте ещё раз.",
};
