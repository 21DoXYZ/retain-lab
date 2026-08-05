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
};
