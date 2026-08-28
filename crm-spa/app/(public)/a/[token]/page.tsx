import type { Metadata } from "next";
import { PublicAnalytics } from "./PublicAnalytics";

/**
 * /a/<token> — публичный read-only дашборд аналитики по внешней ссылке.
 * Без авторизации (см. app/(public)/layout.tsx). noindex: ссылка приватная,
 * её не должно быть в поиске.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Analytics",
  robots: { index: false, follow: false },
};

export default async function PublicAnalyticsPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <PublicAnalytics token={token} />;
}
