import Link from "next/link";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_LABELS, DEPT_LABELS, roleHome } from "@/lib/permissions";
import { NAV_GROUPS, canSee } from "@/components/ui/nav";
import { isNavKeyEnabled, isGroupEnabled } from "@/lib/modules";
import { PageHeader, Eyebrow, Banner } from "@/components/ui";
import { getMessages, type MessageKey } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/**
 * (app) index at "/". Role landing / launcher.
 *
 * The plan calls for a "default redirect by role" (operator→/queue,
 * analyst/finance/director→/overview, affiliate→/affiliate, ...). The redirect
 * targets are owned by later waves (B2/B4/C) and don't exist yet, so hard-
 * redirecting would 404. Until they land, this renders a role-scoped launcher
 * (greeting + the sections this role may open, straight from the nav matrix).
 *
 * The role→home mapping already lives in lib/permissions.roleHome(); flip the
 * marked line below to `redirect(roleHome(user.role))` once those pages exist.
 */
/** Роли, видящие дашборд владельца (= LEAK_ROLES в api/saas.py). */
const OWNER_ROLES = new Set([
  "super_admin", "head_retention", "director", "analyst", "finance", "marketing_manager",
]);

export default async function AppHome() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  // SaaS-пресет: владельцу/аналитику - дашборд «цифры + с чего начать»
  // (ответ на «зашёл и ничего не понятно»), операторам - прежний лаунчер.
  if (OWNER_ROLES.has(user.role)) {
    const { HomeView } = await import("@/components/saas/HomeView");
    return <HomeView />;
  }

  // Server-side translation for the nav item labels below (this page renders
  // outside AppChrome's useT()-driven tree, but resolveLocale()/getMessages()
  // give the same result without needing a client context here).
  const messages = getMessages(await resolveLocale());

  const home = roleHome(user.role);
  // Роль/отдел — через ключи словаря (ROLE_LABELS/DEPT_LABELS в lib/permissions
  // остаются русскими данными: они общие и не знают про локаль).
  const roleLabel = messages[`admin.role.${user.role}` as MessageKey] ?? ROLE_LABELS[user.role];
  const scope =
    user.affiliate_code ??
    (user.department
      ? (messages[`admin.dept.${user.department}` as MessageKey] ?? DEPT_LABELS[user.department])
      : null);

  // Sections this role can open (from the same matrix that filters the sidebar),
  // excluding "players" whose href is "/" (this page).
  const sections = NAV_GROUPS.filter((g) => isGroupEnabled(g.title))
    .flatMap((g) => g.items)
    .filter(
    (it) => canSee(it, user.role) && it.href !== "/" && isNavKeyEnabled(it.key),
  );

  return (
    <>
      <PageHeader
        title={messages["home.greeting"].replace("{name}", user.full_name.split(" ")[0])}
        lead={
          <>
            {messages["home.yourRole"]} <b>{roleLabel}</b>
            {scope ? <> · {scope}</> : null}. {messages["home.leadTail"]}
          </>
        }
      />

      <Eyebrow>{messages["home.sections"]}</Eyebrow>
      {sections.length === 0 ? (
        <Banner>{messages["home.empty"]}</Banner>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sections.map((it) => {
            const primary = it.href === home;
            return (
              <Link
                key={it.key}
                href={it.href}
                className={
                  "flex items-center gap-3 bg-canvas border rounded-card px-4 py-3.5 transition-colors hover:border-primary " +
                  (primary ? "border-primary" : "border-hair2")
                }
              >
                <span className="text-[22px] leading-none flex-none">{it.emoji}</span>
                <div className="min-w-0">
                  <div className="text-[14px] font-semibold text-ink truncate">{messages[it.label]}</div>
                  {primary ? (
                    <div className="text-[11.5px] text-primary">{messages["home.yourSection"]}</div>
                  ) : null}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}
