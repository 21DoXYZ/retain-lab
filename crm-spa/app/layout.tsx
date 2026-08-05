import type { Metadata } from "next";
import { Outfit } from "next/font/google";
import "./globals.css";
import { resolveLocale } from "@/lib/i18n/server";

// Outfit — шрифт пресета TailAdmin; переменную читает --font-sans в globals.css.
const outfit = Outfit({ subsets: ["latin"], variable: "--font-outfit" });

export const metadata: Metadata = {
  title: "Revenue Autopilot",
  description: "Revenue automation for SaaS",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await resolveLocale();
  return (
    <html lang={locale} className={`h-full antialiased ${outfit.variable}`}>
      <body className="min-h-full flex flex-col font-sans">{children}</body>
    </html>
  );
}
