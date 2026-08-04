"use client";

import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { SectionH2, FieldsGrid, Metric } from "./ui";
import { fmtTry, fmtBool, fmtNaiveDate } from "./format";
import type { PlayerSummary } from "./types";

/**
 * 👤 Профиль — board «Профиль» `.fields` grid, exact field list/order/labels
 * (player_board.py line 1350-1355): VIP-уровень, тип, статус, страна,
 * регистрация, возраст, аффилиат, депозитор, первый деп, phone✓/email✓, баланс
 * и бонус (снимок), activity_status. Fed by the /summary `profile` slice
 * (restricted roles get the money-free safe_profile → those fields show «—»).
 */
export function ProfileSection({ summary }: { summary: PlayerSummary }) {
  const t = useT();
  const p = summary.profile;
  if (!p) return null;

  return (
    <section className="mt-6" data-section="profile">
      <SectionH2>{t("analytics.section.profile")}</SectionH2>
      {/* title — расшифровки полей: board CARD_TIP / _viptip (player_board.py:1254-1303,1354). */}
      <FieldsGrid>
        <Metric
          label={t("analytics.profile.vipLevel")}
          value={summary.vip_label || "—"}
          title={t("card.tip.field.vip_level")}
        />
        <Metric label={t("analytics.profile.type")} value={p.account_type || "—"} title={t("card.tip.field.account_type")} />
        <Metric label={t("analytics.profile.status")} value={p.status || "—"} title={t("card.tip.field.status")} />
        <Metric label={t("analytics.profile.country")} value={p.country || "—"} title={t("card.tip.field.country")} />
        <Metric label={t("analytics.profile.registration")} value={fmtNaiveDate(p.reg_date)} title={t("card.tip.field.reg_date")} />
        <Metric label={t("analytics.profile.ageDays")} value={formatInt(p.tenure_days)} title={t("card.tip.field.tenure_days")} />
        <Metric
          label={t("analytics.profile.affiliate")}
          value={p.affiliate_type || "—"}
          title={t("card.tip.field.affiliate_type")}
        />
        <Metric
          label={t("analytics.profile.depositor")}
          value={fmtBool(p.is_depositor, t("analytics.common.yes"), t("analytics.common.no"))}
        />
        <Metric label={t("analytics.profile.firstDeposit")} value={fmtTry(p.ftd_amount)} title={t("card.tip.field.ftd_amount")} />
        <Metric
          label={t("analytics.profile.phoneVerified")}
          value={fmtBool(p.phone_verified, t("analytics.common.yes"), t("analytics.common.no"))}
        />
        <Metric
          label={t("analytics.profile.emailVerified")}
          value={fmtBool(p.email_verified, t("analytics.common.yes"), t("analytics.common.no"))}
        />
        <Metric label={t("analytics.profile.balanceSnapshot")} value={fmtTry(p.balance)} title={t("card.tip.field.balance")} />
        <Metric label={t("analytics.profile.bonusSnapshot")} value={fmtTry(p.bonus_balance)} title={t("card.tip.field.bonus_balance")} />
        <Metric
          label={t("analytics.profile.activityStatus")}
          value={p.activity_status || "—"}
          title={t("card.tip.field.activity_status")}
        />
      </FieldsGrid>
    </section>
  );
}
