"use client";

import { useEffect, useState } from "react";
import { Modal, Button, Select } from "@/components/ui";
import { createClient } from "@/lib/supabase/client";
import { useRole } from "@/lib/role-context";
import { useT } from "@/lib/i18n";
import { assignPlayers } from "@/components/queue/mutations";
import type { OperatorOption } from "@/components/queue/types";
import type { UserRole } from "@/lib/types";

/**
 * «Назначить WhatsApp» (запрос клиента): оператор после разговора передаёт игрока
 * WhatsApp-менеджеру или руководителю отдела. Переиспользует assignPlayers —
 * добавляет назначение выбранному получателю (crm.player_assignments под RLS,
 * audit пишется). Получатели: операторы/VIP-менеджеры + руководители.
 */
const HANDOFF_ROLES = new Set<UserRole>([
  "operator",
  "vip_manager",
  "head_department",
  "head_retention",
  "super_admin",
]);

export function HandoffButton({ playerId }: { playerId: number }) {
  const t = useT();
  const me = useRole();
  const [open, setOpen] = useState(false);
  const [recips, setRecips] = useState<OperatorOption[] | null>(null);
  const [rid, setRid] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const allowed = HANDOFF_ROLES.has(me.role);

  useEffect(() => {
    if (!open || recips) return;
    // Через SECURITY DEFINER функцию (миграция 0017): у оператора RLS на crm_users
    // отдаёт только его самого, поэтому список получателей грузим функцией — она в
    // обход RLS возвращает активных операторов/VIP/руководителей (кроме себя).
    createClient()
      .schema("crm")
      .rpc("handoff_recipients")
      .then(({ data }) => {
        setRecips(
          (data ?? []).map((o: { id: string; full_name: string; department: string | null }) => ({
            id: o.id,
            full_name: o.full_name,
            department: o.department ?? null,
          })),
        );
      });
  }, [open, recips]);

  if (!allowed) return null;

  async function submit() {
    if (!rid) return;
    setBusy(true);
    setMsg(null);
    const res = await assignPlayers({
      actorId: me.id,
      playerIds: [playerId],
      operatorIds: [rid],
      mode: "all",
    });
    setBusy(false);
    if (res.ok) {
      const name = recips?.find((o) => o.id === rid)?.full_name ?? "";
      setMsg(t("card.handoff.done", { name }));
      setTimeout(() => setOpen(false), 900);
    } else {
      setMsg(res.errorKey ? t(res.errorKey) : res.error ?? t("card.common.error"));
    }
  }

  return (
    <>
      <Button variant="ghost" onClick={() => setOpen(true)}>
        {t("card.handoff.button")}
      </Button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("card.handoff.title")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("card.handoff.cancel")}
            </Button>
            <Button variant="brand" loading={busy} disabled={!rid} onClick={submit}>
              {t("card.handoff.confirm")}
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-steel mb-2">{t("card.handoff.hint")}</p>
        <Select value={rid} onChange={(e) => setRid(e.target.value)}>
          <option value="">{t("card.handoff.pick")}</option>
          {(recips ?? []).map((o) => (
            <option key={o.id} value={o.id}>
              {o.full_name}
              {o.department ? ` · ${o.department}` : ""}
            </option>
          ))}
        </Select>
        {msg ? <div className="mt-2 text-[12.5px] text-slate">{msg}</div> : null}
      </Modal>
    </>
  );
}
