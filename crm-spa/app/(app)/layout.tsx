import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AppChrome } from "@/components/AppChrome";
import { I18nProvider } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/**
 * Protected layout for the whole (app) area. Runs on the server for every
 * (app) route:
 *   1. Resolve the signed-in user (session + crm.crm_users profile via RLS).
 *   2. No session  → /login.  Deactivated account → /login?blocked=1.
 *   3. Otherwise wrap children in AppChrome (AppShell + role context + menu).
 *
 * This is the authoritative guard for pages; proxy.ts is only an optimistic
 * first pass. Every child screen can call useRole() (client) or getCurrentUser()
 * (server) to read the same user.
 */
export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getCurrentUser();

  if (!user) redirect("/login");
  if (!user.is_active) redirect("/login?blocked=1");

  // Локаль читается из cookie на сервере и раздаётся всему (app)-дереву, поэтому
  // переключатель языка в шапке работает на всех экранах, а не только на B4.
  const locale = await resolveLocale();

  return (
    <I18nProvider initialLocale={locale}>
      <AppChrome user={user}>{children}</AppChrome>
    </I18nProvider>
  );
}
