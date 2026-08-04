"use client";

import { useT, type MessageKey } from "@/lib/i18n";
import { PageHeader } from "./AppShell";
import { Banner } from "./Card";

/**
 * Ветка «раздел недоступен для вашей роли» для СЕРВЕРНЫХ page.tsx.
 *
 * Зачем компонент: page.tsx — серверные (гейт роли через getCurrentUser), а
 * useT() работает только в клиентских. Добавлять "use client" в саму страницу
 * нельзя — она тянет server-only (lib/auth, next/headers). Поэтому страница
 * рендерит этот маленький клиентский компонент, и текст отказа переводится.
 * Провайдер локали — глобальный (app/(app)/layout.tsx), так что t() здесь жив.
 *
 * Ключи живут в базовом словаре ("access.*"), потому что страницы принадлежат
 * разным доменам, а компонент отказа один.
 */
export function AccessDenied({
  titleKey,
  descKey,
}: {
  titleKey: MessageKey;
  /** По умолчанию — общий текст «обратитесь к руководителю». */
  descKey?: MessageKey;
}) {
  const t = useT();
  return (
    <>
      <PageHeader title={t(titleKey)} />
      <Banner>{t(descKey ?? "common.accessDesc")}</Banner>
    </>
  );
}
