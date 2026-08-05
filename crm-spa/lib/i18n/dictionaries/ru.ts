/**
 * ru — BASE dictionary (корень). Источник истины для НАБОРА КЛЮЧЕЙ: любой ключ,
 * который использует экран, обязан существовать здесь, иначе он не MessageKey.
 *
 * Словарь разбит ПО ДОМЕНАМ (ru/<домен>.ts), чтобы разные экраны/агенты правили
 * свои файлы независимо и не конфликтовали. Этот корень только СЛИВАЕТ их —
 * добавляя новый домен, заведи ru/<домен>.ts + en/<домен>.ts + tr/<домен>.ts и
 * впиши сюда одной строкой.
 *
 * Соглашение: плоские ключи "<домен>.<имя>", интерполяция {var}.
 * en/tr — Partial этого набора и падают в ru по каждому ключу (см. ../messages.ts).
 */
import { base } from "./ru/base";
import { nav } from "./ru/nav";
import { ui } from "./ru/ui";
import { card } from "./ru/card";
import { analytics } from "./ru/analytics";
import { money } from "./ru/money";
import { segmentation } from "./ru/segmentation";
import { marketing } from "./ru/marketing";
import { monitor } from "./ru/monitor";
import { players } from "./ru/players";
import { admin } from "./ru/admin";
import { calls } from "./ru/calls";
import { callsboard } from "./ru/callsboard";
import { modules } from "./ru/modules";
import { traffic } from "./ru/traffic";
import { risk } from "./ru/risk";
import { automation } from "./ru/automation";
import { reports } from "./ru/reports";
import { saas } from "./ru/saas";

export const ru = {
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
} satisfies Record<string, string>;

/** Every valid message key (derived from the base dictionary). */
export type MessageKey = keyof typeof ru;

/** A fully-resolved dictionary for one locale. */
export type Messages = Record<MessageKey, string>;
