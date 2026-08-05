/**
 * en — English translations (корень). Partial от набора ключей ru: любой пропущенный или пустой
 * ключ рендерит ru-значение (см. ../messages.ts) — приложение никогда не ломается
 * из-за непереведённого ключа.
 *
 * Разбит по доменам (en/<домен>.ts) — правь свой домен, этот корень только сливает.
 */
import type { Messages } from "./ru";
import { base } from "./en/base";
import { nav } from "./en/nav";
import { ui } from "./en/ui";
import { card } from "./en/card";
import { analytics } from "./en/analytics";
import { money } from "./en/money";
import { segmentation } from "./en/segmentation";
import { marketing } from "./en/marketing";
import { monitor } from "./en/monitor";
import { players } from "./en/players";
import { admin } from "./en/admin";
import { calls } from "./en/calls";
import { callsboard } from "./en/callsboard";
import { modules } from "./en/modules";
import { traffic } from "./en/traffic";
import { risk } from "./en/risk";
import { automation } from "./en/automation";
import { reports } from "./en/reports";
import { saas } from "./en/saas";

export const en: Partial<Messages> = {
  ...base,
  ...nav,
  ...ui,
  ...card,
  ...analytics,
  ...money,
  ...segmentation,
  ...marketing,
  ...monitor,
  ...players,
  ...admin,
  ...calls,
  ...callsboard,
  ...modules,
  ...traffic,
  ...risk,
  ...automation,
  ...reports,
  ...saas,
};
