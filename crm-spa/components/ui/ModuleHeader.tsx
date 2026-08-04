"use client";

import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import { Eyebrow } from "./AppShell";

/**
 * ModuleHeader — шапка модуля «чья боль / боль / действие» (ТЗ перестройки
 * меню на 7 модулей, этап 1). По решению владельца (17.07) — КОМПАКТНАЯ:
 * свёрнута в одну тонкую строку под PageHeader, разворачивается по клику
 * (нативный <details>, как Collapsible). Тексты — домен словаря `modules.*`.
 */

/** Ключ модуля — 7 модулей меню (docs/plans/2026-07-17-modules-etap3-plan.md). */
export type ModuleHeaderKey =
  | "traffic"
  | "vip"
  | "bonuseco"
  | "risk"
  | "core"
  | "analytics"
  | "data";

interface ModuleHeaderProps {
  module: ModuleHeaderKey;
  className?: string;
}

export function ModuleHeader({ module, className }: ModuleHeaderProps) {
  const t = useT();
  return (
    <details
      className={cn(
        "group mt-3 bg-canvas border border-hair2 rounded-ctl px-4 py-[7px]",
        className,
      )}
    >
      <summary className="flex items-center gap-2 cursor-pointer list-none select-none [&::-webkit-details-marker]:hidden">
        <span className="text-[12px] text-steel">
          ℹ️ {t("modules.header.about")}
          <span className="text-stone"> · {t(`modules.${module}.chair`)}</span>
        </span>
        <span className="ml-auto text-[11px] text-stone whitespace-nowrap">
          <span className="group-open:hidden">{t("ui.collapsible.expand")}</span>
          <span className="hidden group-open:inline">{t("ui.collapsible.collapse")}</span>
        </span>
      </summary>
      <div className="grid gap-4 md:grid-cols-3 mt-3 pb-1.5">
        <div>
          <Eyebrow>{t("modules.header.chair")}</Eyebrow>
          <div className="text-[13.5px] leading-relaxed">{t(`modules.${module}.chair`)}</div>
        </div>
        <div>
          <Eyebrow>{t("modules.header.pain")}</Eyebrow>
          <div className="text-[13.5px] leading-relaxed">{t(`modules.${module}.pain`)}</div>
        </div>
        <div>
          <Eyebrow>{t("modules.header.action")}</Eyebrow>
          <div className="text-[13.5px] leading-relaxed">{t(`modules.${module}.action`)}</div>
        </div>
      </div>
    </details>
  );
}
