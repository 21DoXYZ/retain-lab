import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { resolveLocale } from "@/lib/i18n/server";
import { AccessDenied } from "@/components/ui";
import { CalendarClient } from "@/components/calendar/CalendarClient";
import { loadHeadSummary, loadOperatorCalendar } from "./load";

/**
 * /calendar — calendar aggregate views (B4). Creation of a scheduled call lives
 * in the player card (B3); this screen renders the operator day plan + heatmap
 * auto-plan, or the head-of-department per-operator summary. Role-gated to the
 * operational (call-center) roles; RLS is the hard boundary (0002).
 */

const OPERATOR_ROLES = new Set(["operator", "vip_manager"]);
const HEAD_ROLES = new Set(["head_department", "head_retention", "super_admin"]);

export default async function CalendarPage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");

  const locale = await resolveLocale();
  const isHead = HEAD_ROLES.has(me.role);
  const isOperator = OPERATOR_ROLES.has(me.role);

  if (!isHead && !isOperator) {
    return <AccessDenied titleKey="calendar.title" descKey="access.calendar.desc" />;
  }

  if (isHead) {
    const { error, rows } = await loadHeadSummary();
    return (
      <CalendarClient
        locale={locale}
        isHead
        error={error}
        dayPlan={[]}
        autoPlan={[]}
        summary={rows}
      />
    );
  }

  const { error, dayPlan, autoPlan } = await loadOperatorCalendar(me.id);
  return (
    <CalendarClient
      locale={locale}
      isHead={false}
      error={error}
      dayPlan={dayPlan}
      autoPlan={autoPlan}
      summary={[]}
    />
  );
}
