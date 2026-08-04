import { I18nProvider } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/**
 * Layout for the (auth) area — currently just /login. Deliberately does
 * NOT check auth/session (that would be wrong here: this is the sign-in
 * screen itself, and app/(app)/layout.tsx already owns the redirect-to-login
 * guard for everything else). The ONLY job of this layout is to resolve the
 * locale cookie on the server and hand it to <I18nProvider>, so useT() and
 * <LocaleSwitcher/> work on /login the same way they do inside (app) — see
 * app/(app)/layout.tsx for the sibling pattern.
 */
export default async function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await resolveLocale();

  return <I18nProvider initialLocale={locale}>{children}</I18nProvider>;
}
