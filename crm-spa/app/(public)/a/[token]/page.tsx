import type { Metadata } from "next";
import { PublicAnalytics } from "./PublicAnalytics";

/**
 * /a/<token> — публичный read-only дашборд аналитики по внешней ссылке.
 * Без авторизации (см. app/(public)/layout.tsx). noindex: ссылка приватная,
 * её не должно быть в поиске.
 */
export const dynamic = "force-dynamic";

// Превью в мессенджерах: владелец шлёт эту ссылку инвестору/партнёру -
// карточка должна выглядеть как продукт, а не как голый URL.
export const metadata: Metadata = {
  title: "Live business report",
  description:
    "Revenue, growth and retention - a live read-only dashboard shared via Revenue Autopilot.",
  robots: { index: false, follow: false },
  openGraph: {
    type: "website",
    siteName: "Revenue Autopilot",
    title: "Live business report",
    description: "Revenue, growth and retention - live and read-only.",
    images: [{ url: "https://retivo.digital/img/og-report.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Live business report",
    description: "Revenue, growth and retention - live and read-only.",
    images: ["https://retivo.digital/img/og-report.png"],
  },
};

export default async function PublicAnalyticsPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <PublicAnalytics token={token} />;
}
