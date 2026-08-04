"use client";

import { useEffect, useState } from "react";
import { Button, Select, Modal } from "@/components/ui";
import { createClient } from "@/lib/supabase/client";
import { useRole } from "@/lib/role-context";
import { useT } from "@/lib/i18n";
import { assignPlayers, unassignAll } from "@/components/queue/mutations";
import type { OperatorOption } from "@/components/queue/types";

/**
 * Панель массового назначения из списка игроков: выбрал пачку чекбоксами →
 * выбрал оператора → «Назначить». Переиспользует мутацию assignPlayers (пишет в
 * crm.player_assignments под RLS, mode=all → все выбранные одному оператору).
 * Показывается только раздающим игроков (гейт в PlayersScreen).
 */
export function BulkAssignBar({
  playerIds,
  onClear,
  onDone,
}: {
  playerIds: number[];
  onClear: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const me = useRole();
  const [operators, setOperators] = useState<OperatorOption[] | null>(null);
  const [opId, setOpId] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmUnassign, setConfirmUnassign] = useState(false);
  const [unbusy, setUnbusy] = useState(false);

  useEffect(() => {
    createClient()
      .schema("crm")
      .from("crm_users")
      .select("id, full_name, department")
      .eq("role", "operator")
      .eq("is_active", true)
      .order("full_name")
      .then(({ data }) => {
        setOperators(
          (data ?? []).map((o) => ({
            id: o.id as string,
            full_name: o.full_name as string,
            department: (o.department as string) ?? null,
          })),
        );
      });
  }, []);

  async function submit() {
    if (!opId || playerIds.length === 0) return;
    setBusy(true);
    setMsg(null);
    const res = await assignPlayers({
      actorId: me.id,
      playerIds,
      operatorIds: [opId],
      mode: "all",
    });
    setBusy(false);
    if (res.ok) {
      const name = operators?.find((o) => o.id === opId)?.full_name ?? "";
      setMsg(t("players.bulk.done", { n: playerIds.length, name }));
      setOpId("");
      onDone();
    } else {
      setMsg(res.errorKey ? t(res.errorKey) : res.error ?? t("card.common.error"));
    }
  }

  // Массовая отвязка: снять всех операторов у выбранных игроков (под RLS).
  async function doUnassignAll() {
    setUnbusy(true);
    setMsg(null);
    const res = await unassignAll({ actorId: me.id, playerIds });
    setUnbusy(false);
    setConfirmUnassign(false);
    if (res.ok) {
      setMsg(t("players.bulk.unassignDone", { n: playerIds.length }));
      onDone();
    } else {
      setMsg(res.errorKey ? t(res.errorKey) : res.error ?? t("card.common.error"));
    }
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-card border border-primary/40 bg-primary/5 px-3 py-2">
      <span className="text-[13px] font-medium text-ink">
        {t("players.bulk.selected", { n: playerIds.length })}
      </span>
      <Select value={opId} onChange={(e) => setOpId(e.target.value)} className="w-56">
        <option value="">{t("players.bulk.pick")}</option>
        {(operators ?? []).map((o) => (
          <option key={o.id} value={o.id}>
            {o.full_name}
            {o.department ? ` · ${o.department}` : ""}
          </option>
        ))}
      </Select>
      <Button variant="brand" size="sm" loading={busy} disabled={!opId} onClick={submit}>
        {t("players.bulk.assign")}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirmUnassign(true)}>
        {t("players.bulk.unassign")}
      </Button>
      <Button variant="ghost" size="sm" onClick={onClear}>
        {t("players.bulk.clear")}
      </Button>
      {msg ? <span className="text-[12.5px] text-slate">{msg}</span> : null}

      {/* Подтверждение массовой отвязки операторов */}
      <Modal
        open={confirmUnassign}
        onClose={() => setConfirmUnassign(false)}
        title={t("players.bulk.unassign")}
        widthClass="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmUnassign(false)}>
              {t("ui.cancel")}
            </Button>
            <Button variant="brand" loading={unbusy} onClick={doUnassignAll}>
              {t("players.bulk.unassign")}
            </Button>
          </>
        }
      >
        <div className="text-[13.5px] text-slate">
          {t("players.bulk.unassignConfirm", { n: playerIds.length })}
        </div>
      </Modal>
    </div>
  );
}
