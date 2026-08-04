"use client";

import { useCallback, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  PageHeader,
  Panel,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  Badge,
  LifecycleBadge,
  VipBadge,
  BeatsCasinoBadge,
  Button,
  Pill,
  SCard,
  SCardGrid,
  Banner,
  EmptyState,
} from "@/components/ui";
import { formatDateShort } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { CurrentUser } from "@/lib/types";
import { ASSIGN_STATUS, assignStatusTone } from "./labels";
import { PreCallWarning } from "./PreCallWarning";
import { requestWaTransfer } from "./mutations";
import { useRealtimeRefresh } from "./useRealtimeRefresh";
import type { OperatorQueueData, QueueRow } from "./types";

const COL_COUNT = 10;

/**
 * Operator queue (/queue). Server-rendered rows, kept live via Supabase
 * Realtime (assignments/schedule/calls for this operator) with a manual refresh
 * fallback. Rows are sorted with the day plan on top (overdue first) then by
 * model priority; clicking a row opens the player card (/players/<id>, owned by
 * B3). Empty/data handled here; loading/error at the route level.
 */

function PlanCell({ row }: { row: QueueRow }) {
  const t = useT();
  const s = row.scheduled;
  if (!s) return <span className="text-stone">—</span>;
  const when = formatDateShort(s.scheduled_at);
  if (s.overdue) {
    return (
      <Badge bg="#fee2e2" fg="#991b1b" title={s.comment ?? undefined}>
        {t("players.queue.plan.overdue", { when })}
      </Badge>
    );
  }
  if (s.today) {
    return (
      <Badge bg="#dbeafe" fg="#1e40af" title={s.comment ?? undefined}>
        {t("players.queue.plan.today", { when })}
      </Badge>
    );
  }
  return (
    <span className="text-slate" title={s.comment ?? undefined}>
      {when}
      {s.by_system ? ` · ${t("players.queue.plan.auto")}` : ""}
    </span>
  );
}

function CoAssignees({ names }: { names: string[] }) {
  const t = useT();
  if (names.length === 0) return <span className="text-stone">—</span>;
  const shown = names.slice(0, 2).join(", ");
  const extra = names.length - 2;
  return (
    <span className="text-slate" title={t("players.queue.alsoWithTitle", { names: names.join(", ") })}>
      {shown}
      {extra > 0 ? ` +${extra}` : ""}
    </span>
  );
}

function QueueRowView({
  row,
  isCallCenter,
  busyWa,
  onWaTransfer,
}: {
  row: QueueRow;
  isCallCenter: boolean;
  busyWa: number | null;
  onWaTransfer: (playerId: number) => void;
}) {
  const t = useT();
  const router = useRouter();
  const tone = assignStatusTone(row.status);
  const href = `/players/${row.playerId}`;
  const go = () => router.push(href);

  return (
    <>
      <TR href={href}>
        <TD idCell>
          <span className="inline-flex items-center gap-1.5">
            {row.directory?.display_id ?? row.playerId}
            {row.beatsCasino ? <BeatsCasinoBadge /> : null}
          </span>
        </TD>
        <TD className="text-left">
          <LifecycleBadge stage={row.directory?.lifecycle} />
        </TD>
        <TD className="text-left">
          <VipBadge level={row.directory?.vip_level} />
        </TD>
        <TD className="text-left">
          <Badge bg={tone.bg} fg={tone.fg}>
            {t(ASSIGN_STATUS[row.status].labelKey)}
          </Badge>
        </TD>
        <TD>
          {row.hasNotes ? (
            <span title={t("players.queue.notesCountTitle", { n: row.notesCount })}>📝</span>
          ) : (
            <span className="text-stone">—</span>
          )}
        </TD>
        <TD className="text-left text-slate">
          {row.lastTouchAt ? (
            formatDateShort(row.lastTouchAt)
          ) : (
            <span className="text-stone">{t("players.queue.lastTouchNone")}</span>
          )}
        </TD>
        <TD className="text-left">
          <CoAssignees names={row.coAssignees} />
        </TD>
        <TD className="text-left">
          <PlanCell row={row} />
        </TD>
        <TD className="text-left">
          {row.priority?.action ? (
            <span className="text-slate" title={row.priority.bonus ?? undefined}>
              {row.priority.action}
            </span>
          ) : (
            <span className="text-stone">—</span>
          )}
        </TD>
        <TD>
          {isCallCenter ? (
            <Button
              size="sm"
              variant="ghost"
              loading={busyWa === row.playerId}
              onClick={(e) => {
                e.stopPropagation();
                onWaTransfer(row.playerId);
              }}
            >
              → WhatsApp
            </Button>
          ) : null}
        </TD>
      </TR>
      {row.todayTouchesByOthers.length > 0 ? (
        <tr onClick={go} className="cursor-pointer">
          <td colSpan={COL_COUNT} className="px-3.5 pb-2.5 border-b border-hair">
            <PreCallWarning touches={row.todayTouchesByOthers} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function QueueBoard({
  me,
  data,
}: {
  me: CurrentUser;
  data: OperatorQueueData;
}) {
  const t = useT();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [flash, setFlash] = useState<string | null>(null);
  const [busyWa, setBusyWa] = useState<number | null>(null);

  const refresh = useCallback(() => {
    startTransition(() => router.refresh());
  }, [router]);

  useRealtimeRefresh(
    [
      { table: "player_assignments", filter: `operator_id=eq.${me.id}` },
      { table: "scheduled_calls", filter: `operator_id=eq.${me.id}` },
      { table: "calls", filter: `operator_id=eq.${me.id}` },
    ],
    refresh,
  );

  const isCallCenter = me.department === "call_center";

  async function onWaTransfer(playerId: number) {
    setBusyWa(playerId);
    setFlash(null);
    const res = await requestWaTransfer({ actorId: me.id, playerId });
    setBusyWa(null);
    setFlash(
      res.ok
        ? t("players.queue.waTransferSent", { playerId })
        : res.error ?? t("players.queue.waTransferFailed"),
    );
  }

  const { rows, plannedToday, overdue } = data;

  return (
    <>
      <PageHeader
        title={t("players.queue.title")}
        lead={t("players.queue.lead")}
        right={
          <div className="flex items-center gap-2">
            <Pill live>● live</Pill>
            <Button variant="ghost" onClick={refresh} loading={isPending}>
              {t("players.queue.refresh")}
            </Button>
          </div>
        }
      />

      <SCardGrid className="mt-5 lg:grid-cols-3">
        <SCard label={t("players.queue.card.inQueue")} value={rows.length} icon="📋" />
        <SCard
          label={t("players.queue.card.planToday")}
          value={plannedToday}
          icon="🗓"
          variant={plannedToday > 0 ? "cream" : "default"}
        />
        <SCard
          label={t("players.queue.card.overdue")}
          value={overdue}
          icon="⏰"
          variant={overdue > 0 ? "alert" : "default"}
          valueTone={overdue > 0 ? "neg" : "default"}
        />
      </SCardGrid>

      {data.prioritiesDegraded ? <Banner>{t("players.queue.degraded")}</Banner> : null}

      {flash ? (
        <div className="mt-4 text-[13px] rounded-ctl px-3.5 py-2.5 border text-ink bg-cream border-beige">
          {flash}
        </div>
      ) : null}

      <div className="mt-5">
        {rows.length === 0 ? (
          <Panel>
            <EmptyState
              icon="📞"
              title={t("players.queue.emptyTitle")}
              description={t("players.queue.emptyDesc")}
            />
          </Panel>
        ) : (
          <Panel>
            <Table>
              <THead>
                <TR>
                  <TH>{t("players.queue.col.player")}</TH>
                  <TH className="text-left">{t("players.queue.col.stage")}</TH>
                  <TH className="text-left">VIP</TH>
                  <TH className="text-left">{t("players.queue.col.status")}</TH>
                  <TH>{t("players.queue.col.notes")}</TH>
                  <TH className="text-left">{t("players.queue.col.lastTouch")}</TH>
                  <TH className="text-left">{t("players.queue.col.alsoWith")}</TH>
                  <TH className="text-left">{t("players.queue.col.plan")}</TH>
                  <TH className="text-left">{t("players.queue.col.action")}</TH>
                  <TH></TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <QueueRowView
                    key={row.assignmentId}
                    row={row}
                    isCallCenter={isCallCenter}
                    busyWa={busyWa}
                    onWaTransfer={onWaTransfer}
                  />
                ))}
              </TBody>
            </Table>
          </Panel>
        )}
      </div>
    </>
  );
}
