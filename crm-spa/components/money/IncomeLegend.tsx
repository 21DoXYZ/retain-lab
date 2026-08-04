"use client";

import { Banner } from "@/components/ui/Card";
import { useT } from "@/lib/i18n";

/**
 * «Три разных дохода — не путать»: Net Profit / GGR / NGR.
 *
 * Дисклеймер жил только на карточке аффилиата, хотя путаются эти три величины
 * ровно там, где они стоят рядом — на Обзоре бизнеса и на экране GGR (ТЗ по
 * копирайту, задача 6.1). Вынесен в отдельный компонент, чтобы текст был один
 * на все экраны: разойдись он копиями — начнут расходиться и формулировки.
 *
 * Ключи переиспользуются от аффилиатов (monitor.affiliateDetail.glegend.*):
 * они универсальны и к конкретному источнику трафика не привязаны.
 */
export function IncomeLegend() {
  const t = useT();
  return (
    <Banner>
      📊 <b>{t("monitor.affiliateDetail.glegend.title")}</b>{" "}
      <b>Net Profit</b> {t("monitor.affiliateDetail.glegend.netProfit")}{" "}
      <b>GGR</b> {t("monitor.affiliateDetail.glegend.ggr")}{" "}
      <b>NGR</b> {t("monitor.affiliateDetail.glegend.ngr")}
    </Banner>
  );
}
