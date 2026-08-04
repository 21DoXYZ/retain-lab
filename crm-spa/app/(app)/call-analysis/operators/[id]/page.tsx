import { requireCallRole } from "@/components/call-board/guard";
import { CB_REPORT } from "@/components/call-board/roles";
import { OperatorReportScreen } from "@/components/call-board/OperatorReportScreen";

/**
 * /call-analysis/operators/[id] — Отчёт по оператору (§10.5). Role-gated
 * (CB_REPORT ≡ R_REPORT); оператор видит только свой отчёт и только при
 * разблок. вердикте — это доусиливает сервер (403 → мягкий экран во вьюхе).
 */
export const dynamic = "force-dynamic";

export default async function OperatorReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await requireCallRole(CB_REPORT);
  const { id } = await params;
  return <OperatorReportScreen operatorId={id} />;
}
