import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import type { UserRole } from "@/lib/types";
import { CallCardScreen } from "@/components/call-analysis/CallCardScreen";

/**
 * /call-analysis/calls/[id] — карточка звонка, ядро продукта (§10.3). Гейт:
 * руководители + админ (полный доступ) и аналитик (только чтение — бэк отдаёт
 * can_play_audio=false и 403 на confirm/override, фронт прячет кнопки/плеер).
 * Оператора сюда не пускаем — у него собственный экран «Мои звонки» (§10.10).
 */
export const dynamic = "force-dynamic";

const CARD_ROLES: readonly UserRole[] = [
  "head_department",
  "head_retention",
  "super_admin",
  "analyst",
];

export default async function CallCardPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (!CARD_ROLES.includes(me.role)) redirect("/");
  return <CallCardScreen callId={id} />;
}
