"use client";

import { useEffect, useState } from "react";
import { Modal, Button, Select } from "@/components/ui";
import { createClient } from "@/lib/supabase/client";
import { useRole } from "@/lib/role-context";
import { useT } from "@/lib/i18n";
import { assignPlayers } from "@/components/queue/mutations";
import type { OperatorOption } from "@/components/queue/types";

/**
 * «Назначить оператору» прямо из строки Пульта / Играют сейчас.
 *
 * Пробел механики: руководитель видел горящего игрока, но чтобы отдать его
 * оператору, шёл в отдельный экран Пула и искал заново. Здесь — назначение в
 * один клик: сам грузит список операторов, переиспользует готовую мутацию
 * assignPlayers (та же запись в crm.player_assignments под RLS).
 *
 * Роль-гейт: только те, кто раздаёт игроков (как страница /pool). Оператору и
 * прочим кнопка не показывается — компонент возвращает null.
 */
const ASSIGN_ROLES = new Set(["super_admin", "head_retention", "head_department"]);

export function AssignButton({ playerId }: { playerId: number }) {
  const t = useT();
  const me = useRole();
  const [open, setOpen] = useState(false);
  const [operators, setOperators] = useState<OperatorOption[] | null>(null);
  const [opId, setOpId] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const allowed = ASSIGN_ROLES.has(me.role);

  useEffect(() => {
    if (!open || operators) return;
    // грузим активных операторов один раз при первом открытии
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
  }, [open, operators]);

  if (!allowed) return null;

  async function submit() {
    if (!opId) return;
    setBusy(true);
    setMsg(null);
    const res = await assignPlayers({
      actorId: me.id,
      playerIds: [playerId],
      operatorIds: [opId],
      mode: "all",
    });
    setBusy(false);
    if (res.ok) {
      const name = operators?.find((o) => o.id === opId)?.full_name ?? "";
      setMsg(t("monitor.assign.done", { name }));
      setTimeout(() => setOpen(false), 900);
    } else {
      setMsg(res.errorKey ? t(res.errorKey) : res.error ?? t("card.common.error"));
    }
  }

  return (
    <>
      <button
        type="button"
        className="text-[12px] text-primary hover:underline whitespace-nowrap"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(true);
        }}
      >
        {t("monitor.assign.button")}
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("monitor.assign.title", { id: playerId })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("monitor.assign.cancel")}
            </Button>
            <Button variant="brand" loading={busy} disabled={!opId} onClick={submit}>
              {t("monitor.assign.confirm")}
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-steel mb-2">{t("monitor.assign.hint")}</p>
        <Select value={opId} onChange={(e) => setOpId(e.target.value)}>
          <option value="">{t("monitor.assign.pick")}</option>
          {(operators ?? []).map((o) => (
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
