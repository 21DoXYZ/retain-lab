import { redirect } from "next/navigation";

/**
 * "/" в SPA: публичный корень домена всегда отдаёт ЛЕНДИНГ (Caddy), поэтому
 * внутренние переходы на "/" уводим на дашборд.
 */
export default function RootRedirect() {
  redirect("/home");
}
