/**
 * tr — Türkçe çeviriler (корень). Partial от набора ключей ru: любой пропущенный или пустой
 * ключ рендерит ru-значение (см. ../messages.ts) — приложение никогда не ломается
 * из-за непереведённого ключа.
 *
 * Разбит по доменам (tr/<домен>.ts) — правь свой домен, этот корень только сливает.
 */
import type { Messages } from "./ru";
import { base } from "./tr/base";
import { nav } from "./tr/nav";
import { ui } from "./tr/ui";
import { card } from "./tr/card";
import { analytics } from "./tr/analytics";
import { money } from "./tr/money";
import { segmentation } from "./tr/segmentation";
import { marketing } from "./tr/marketing";
import { monitor } from "./tr/monitor";
import { players } from "./tr/players";
import { admin } from "./tr/admin";
import { calls } from "./tr/calls";
import { callsboard } from "./tr/callsboard";
import { modules } from "./tr/modules";
import { traffic } from "./tr/traffic";
import { risk } from "./tr/risk";
import { automation } from "./tr/automation";
import { reports } from "./tr/reports";
import { saas } from "./tr/saas";

export const tr: Partial<Messages> = {
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
