"use client";

import { useCallback } from "react";
import type { ReactNode } from "react";
import { LifecycleBadge, TierBadge, VipBadge } from "@/components/ui";
import { formatDate } from "@/lib/format";
import { useT, useLocale, type MessageKey } from "@/lib/i18n";
import type { DimensionDef, ResultCell } from "./types";

/**
 * useDimValue — форматтер значения разреза для сводной таблицы и чипов фильтра.
 * Коды (VIP-уровень, стадия цикла, тир, день недели) не переводим свободным
 * текстом — рендерим существующими бейджами / словарными подписями (тот же приём,
 * что useDow). Даты — в Europe/Istanbul-формате борда; месяц — локализованным
 * названием.
 */
const LOCALE_TAG: Record<string, string> = { ru: "ru-RU", en: "en-US", tr: "tr-TR" };

/** Индекс дня недели ClickHouse toDayOfWeek: 1=Пн … 7=Вс → base-ключи day.0..day.6. */
const WEEKDAY_KEY: Record<number, MessageKey> = {
  1: "day.0",
  2: "day.1",
  3: "day.2",
  4: "day.3",
  5: "day.4",
  6: "day.5",
  7: "day.6",
};

export function useDimValue(): (dim: DimensionDef, raw: ResultCell) => ReactNode {
  const t = useT();
  const { locale } = useLocale();

  return useCallback(
    (dim: DimensionDef, raw: ResultCell): ReactNode => {
      if (raw == null || raw === "") {
        // enum-разрезы всегда имеют значение; пусто бывает у профильных строк
        return dim.value_type === "str" ? t("reports.value.none") : String(raw ?? "—");
      }

      switch (dim.key) {
        case "month": {
          const d = new Date(`${raw}T00:00:00Z`);
          if (Number.isNaN(d.getTime())) return String(raw);
          return new Intl.DateTimeFormat(LOCALE_TAG[locale] ?? "ru-RU", {
            year: "numeric",
            month: "long",
            timeZone: "UTC",
          }).format(d);
        }
        case "week":
          return t("reports.value.weekOf", { date: formatDate(`${raw}T00:00:00Z`) });
        case "day":
          return formatDate(`${raw}T00:00:00Z`);
        case "weekday": {
          const key = WEEKDAY_KEY[Number(raw)];
          return key ? t(key) : String(raw);
        }
        case "hour":
          return t("reports.value.hour", { h: String(raw) });
        case "vip_level_at":
          return <VipBadge level={Number(raw)} />;
        case "lifecycle_at":
          return <LifecycleBadge stage={String(raw)} />;
        case "early_tier_at":
          return <TierBadge tier={String(raw)} />;
        default:
          return String(raw);
      }
    },
    [t, locale],
  );
}
