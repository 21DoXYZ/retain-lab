"use client";

import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { SectionH2, FieldsGrid, Metric } from "./ui";
import { fmtTry } from "./format";
import type { PlayerSummaryMoney } from "./types";

/**
 * 💰 Деньги — board «Деньги» `.fields` grid, exact field list/order/labels from
 * player_board.py def player() (line 1356). Fed by the /summary `money` slice,
 * ABSENT for operator/support/affiliate (казино-деньги) — parent hides it then.
 */
export function MoneySection({ money }: { money: PlayerSummaryMoney }) {
  const t = useT();
  return (
    <section className="mt-6" data-section="money">
      <SectionH2>{t("analytics.section.money")}</SectionH2>
      {/* title — расшифровки полей: board CARD_TIP (player_board.py:1267-1280). */}
      <FieldsGrid>
        <Metric label={t("analytics.money.depCount")} value={formatInt(money.dep_count)} title={t("card.tip.field.dep_count")} />
        <Metric label={t("analytics.money.cashDeposits")} value={fmtTry(money.cash_deposits)} title={t("card.tip.field.cash_deposits")} />
        <Metric label={t("analytics.money.withdrawalsAbs")} value={fmtTry(money.withdrawals_abs)} title={t("card.tip.field.withdrawals_abs")} />
        <Metric label={t("analytics.money.netCash")} value={fmtTry(money.net_cash)} title={t("card.tip.field.net_cash")} />
        <Metric label={t("analytics.money.bonusCost")} value={fmtTry(money.bonus_cost)} title={t("card.tip.field.bonus_cost")} />
        <Metric
          label={t("analytics.money.depSum")}
          value={fmtTry(money.dep_sum)}
          title={t("card.tip.field.dep_sum")}
        />
        <Metric label={t("analytics.money.depFailed")} value={formatInt(money.dep_failed)} title={t("card.tip.field.dep_failed")} />
        <Metric label={t("analytics.money.wdCount")} value={formatInt(money.wd_count)} title={t("card.tip.field.wd_count")} />
        <Metric label={t("analytics.money.wdRejected")} value={formatInt(money.wd_rejected)} title={t("card.tip.field.wd_rejected")} />
        <Metric label={t("analytics.money.bonusCount")} value={formatInt(money.bonus_count)} title={t("card.tip.field.bonus_count")} />
        <Metric label={t("analytics.money.bonusSum")} value={fmtTry(money.bonus_sum)} title={t("card.tip.field.bonus_sum")} />
        <Metric
          label={t("analytics.money.paymentMethod")}
          value={money.primary_payment_method || "—"}
          title={t("card.tip.field.primary_payment_method")}
        />
        <Metric label={t("analytics.money.depRecencyDays")} value={formatInt(money.deposit_recency_days)} title={t("card.tip.field.deposit_recency_days")} />
      </FieldsGrid>
    </section>
  );
}
