"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n";
import { Button, Card } from "@/components/ui";

/**
 * Экран «пространств ещё нет»: бэкенд отвечает no_tenant_selected, когда у
 * платформенного пользователя не заведено ни одного клиента (или их несколько
 * и ни один не выбран). Показываем путь дальше, а не сырую ошибку.
 */
export function NoTenant() {
  const t = useT();
  return (
    <Card className="p-6">
      <div className="text-[15px] font-semibold text-ink">{t("saas.noTenant.title")}</div>
      <p className="mt-1.5 max-w-[560px] text-[13.5px] leading-relaxed text-slate">
        {t("saas.noTenant.desc")}
      </p>
      <Link href="/admin/workspaces" className="mt-4 inline-block">
        <Button variant="brand" size="sm">{t("saas.noTenant.cta")}</Button>
      </Link>
    </Card>
  );
}

/** Код ошибки из FlaskApiError, если это именно «нет пространства». */
export function isNoTenant(e: unknown): boolean {
  return e instanceof Error && e.message === "no_tenant_selected";
}
