import type { Metadata } from "next";
import "./globals.css";
import { resolveLocale } from "@/lib/i18n/server";

// System-font stack only (no web fonts) — matches the live dashboard.
//
// The <meta name="description"> below is SEO/tab-preview content, not UI a
// signed-in operator reads — it is intentionally left as static Russian
// rather than wired to lib/i18n (that would mean inventing a new dictionary
// namespace outside this pass's login.*/affiliate.* scope for a string
// nobody-facing sees). <html lang> DOES matter for accessibility/SEO across
// locales, so that one is resolved from the locale cookie below.
export const metadata: Metadata = {
  title: "Retention CRM",
  description: "CRM · колл-центр · аналитика",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await resolveLocale();
  return (
    <html lang={locale} className="h-full antialiased">
      <body className="min-h-full flex flex-col font-sans">{children}</body>
    </html>
  );
}
