"use client";

import { useState } from "react";
import { Eyebrow, Card, Badge, Button, Modal, Select } from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { ScriptGroup, ScriptGroupsData, ScriptGroupOperator, ScriptInfo } from "./types";

/**
 * Группы операторов (§8/§10.8) — руководитель создаёт группы и даёт каждой свой
 * активный скрипт (варианты A/B/C…). Оператор оценивается по скрипту своей
 * группы; без группы — по скрипту казино по умолчанию. Мутации идут в бэкенд,
 * затем onChanged → родитель перезапрашивает список групп и текущий скрипт.
 * Роль-гейт — на уровне страницы (R_SCRIPT_WRITE); здесь доп.гейт не нужен.
 */
const GROUPS_BASE = "/api/v1/call-analysis/script/groups";

export function ScriptGroups({
  data,
  scripts = [],
  defaultRef = null,
  onChanged,
}: {
  data: ScriptGroupsData;
  /** Реестр именованных скриптов (0011) — для назначения «какой куда идёт». */
  scripts?: ScriptInfo[];
  /** Текущий скрипт казино по умолчанию. */
  defaultRef?: string | null;
  onChanged: () => void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ScriptGroup | null>(null);

  /** Общая обёртка мутаций: единый busy/err + перезагрузка родителя. */
  async function mutate(run: () => Promise<unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await run();
      onChanged();
      return true;
    } catch (e) {
      setErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function createGroup() {
    const name = newName.trim();
    if (!name) return;
    const ok = await mutate(() =>
      flaskFetch(GROUPS_BASE, { method: "POST", body: { name } }),
    );
    if (ok) {
      setNewName("");
      setCreating(false);
    }
  }

  async function deleteGroup(group: ScriptGroup) {
    const ok = await mutate(() =>
      flaskFetch(`${GROUPS_BASE}/${group.group_id}`, { method: "DELETE" }),
    );
    if (ok) setPendingDelete(null);
  }

  const assignMember = (groupId: string, operatorId: string) =>
    mutate(() =>
      flaskFetch(`${GROUPS_BASE}/${groupId}/members`, {
        method: "POST",
        body: { operator_id: operatorId },
      }),
    );

  const removeMember = (operatorId: string) =>
    mutate(() =>
      flaskFetch(`${GROUPS_BASE}/members/${operatorId}`, { method: "DELETE" }),
    );

  // «Какой скрипт куда идёт» (0011): назначение скрипта группе / дефолту казино.
  const assignScript = (groupId: string, scriptRef: string | null) =>
    mutate(() =>
      flaskFetch(`${GROUPS_BASE}/${groupId}/script`, {
        method: "POST",
        body: { script_ref: scriptRef },
      }),
    );

  const setDefaultScript = (scriptRef: string) =>
    mutate(() =>
      flaskFetch("/api/v1/call-analysis/script/default", {
        method: "POST",
        body: { script_ref: scriptRef },
      }),
    );

  return (
    <>
      <Eyebrow>{t("callsboard.script.groups.title")}</Eyebrow>
      <p className="mb-3 text-[13px] text-steel">{t("callsboard.script.groups.hint")}</p>

      {err ? <div className="mb-3 text-[13px] text-neg">{err}</div> : null}

      <div className="space-y-3">
        {data.groups.length === 0 ? (
          <Card>
            <p className="text-[13.5px] text-steel">{t("callsboard.script.groups.empty")}</p>
          </Card>
        ) : (
          data.groups.map((g) => (
            <GroupCard
              key={g.group_id}
              group={g}
              ungrouped={data.ungrouped}
              scripts={scripts}
              busy={busy}
              onAdd={(opId) => assignMember(g.group_id, opId)}
              onRemove={removeMember}
              onDelete={() => setPendingDelete(g)}
              onAssignScript={(ref) => assignScript(g.group_id, ref)}
            />
          ))
        )}

        {/* Создание группы — инлайн-инпут */}
        {creating ? (
          <Card>
            <div className="flex flex-wrap items-center gap-2">
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") createGroup();
                  if (e.key === "Escape") setCreating(false);
                }}
                placeholder={t("callsboard.script.groups.createPlaceholder")}
                className="h-[34px] flex-1 min-w-[180px] rounded-ctl border border-hair3 bg-canvas px-3 text-[13.5px] text-ink outline-none focus:border-2 focus:border-primary"
              />
              <Button size="sm" variant="brand" loading={busy} disabled={!newName.trim()} onClick={createGroup}>
                {t("callsboard.script.groups.createConfirm")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => { setCreating(false); setNewName(""); }}>
                {t("callsboard.script.groups.cancel")}
              </Button>
            </div>
          </Card>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setCreating(true)}>
            {t("callsboard.script.groups.create")}
          </Button>
        )}

        {/* Без группы — казино-дефолт */}
        <Card>
          <div className="flex items-center gap-2">
            <span className="text-[13.5px] font-medium text-slate">{t("callsboard.script.groups.ungrouped")}</span>
            <Badge bg="#f2f4f7" fg="#344054">{data.ungrouped.length}</Badge>
          </div>
          <p className="mt-1 text-[12.5px] text-steel">{t("callsboard.script.groups.ungroupedHint")}</p>
          {scripts.length ? (
            <div className="mt-2 flex items-center gap-2">
              <span className="text-[12.5px] text-steel">{t("callsboard.script.defaultSelector")}</span>
              <Select
                value={defaultRef ?? ""}
                disabled={busy}
                className="h-[34px] max-w-[280px] text-[13px]"
                onChange={(e) => {
                  if (e.target.value) setDefaultScript(e.target.value);
                }}
              >
                {scripts.map((s) => (
                  <option key={s.script_ref} value={s.script_ref}>{s.name}</option>
                ))}
              </Select>
            </div>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {data.ungrouped.length === 0 ? (
              <span className="text-[13px] text-steel">{t("callsboard.script.groups.ungroupedEmpty")}</span>
            ) : (
              data.ungrouped.map((op) => <OperatorChip key={op.operator_id} op={op} />)
            )}
          </div>
        </Card>
      </div>

      {/* Подтверждение удаления группы */}
      <Modal
        open={!!pendingDelete}
        onClose={() => setPendingDelete(null)}
        title={t("callsboard.script.groups.deleteTitle")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingDelete(null)}>
              {t("callsboard.script.groups.cancel")}
            </Button>
            <Button variant="brand" loading={busy} onClick={() => pendingDelete && deleteGroup(pendingDelete)}>
              {t("callsboard.script.groups.deleteConfirm")}
            </Button>
          </>
        }
      >
        {pendingDelete ? (
          <p className="text-[13.5px] text-slate">
            {t("callsboard.script.groups.deleteBody", { name: pendingDelete.name })}
          </p>
        ) : null}
      </Modal>
    </>
  );
}

/** Карточка одной группы: имя, счётчик, активная версия, чипы операторов. */
function GroupCard({
  group,
  ungrouped,
  scripts,
  busy,
  onAdd,
  onRemove,
  onDelete,
  onAssignScript,
}: {
  group: ScriptGroup;
  ungrouped: ScriptGroupOperator[];
  scripts: ScriptInfo[];
  busy: boolean;
  onAdd: (operatorId: string) => void;
  onRemove: (operatorId: string) => void;
  onDelete: () => void;
  onAssignScript: (scriptRef: string | null) => void;
}) {
  const t = useT();
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-medium text-ink">{group.name}</span>
          <Badge bg="#f2f4f7" fg="#344054">{group.members}</Badge>
          {group.script_name ? (
            <Badge bg="#f5f3ff" fg="#5b21b6">{group.script_name}</Badge>
          ) : (
            <Badge bg="#f0fdf4" fg="#166534">{t("callsboard.script.groups.inheritsDefault")}</Badge>
          )}
          {group.active_version != null ? (
            <Badge bg="#ecf3ff" fg="#101828">
              {t("callsboard.script.groups.activeVersion", { version: group.active_version })}
            </Badge>
          ) : (
            <Badge bg="#fff7ed" fg="#9a3412">{t("callsboard.script.groups.noActiveVersion")}</Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {scripts.length ? (
            <Select
              value={group.script_ref ?? ""}
              disabled={busy}
              className="h-[34px] max-w-[240px] text-[13px]"
              onChange={(e) => onAssignScript(e.target.value || null)}
            >
              <option value="">{t("callsboard.script.groups.inheritsDefault")}</option>
              {scripts.map((s) => (
                <option key={s.script_ref} value={s.script_ref}>{s.name}</option>
              ))}
            </Select>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onDelete}>
            {t("callsboard.script.groups.delete")}
          </Button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {group.members_list.length === 0 ? (
          <span className="text-[13px] text-steel">{t("callsboard.script.groups.noMembers")}</span>
        ) : (
          group.members_list.map((op) => (
            <OperatorChip key={op.operator_id} op={op} onRemove={() => onRemove(op.operator_id)} />
          ))
        )}
      </div>

      {ungrouped.length ? (
        <div className="mt-2">
          <Select
            value=""
            disabled={busy}
            className="h-[34px] max-w-[260px] text-[13px]"
            onChange={(e) => {
              if (e.target.value) onAdd(e.target.value);
            }}
          >
            <option value="">{t("callsboard.script.groups.addOperator")}</option>
            {ungrouped.map((op) => (
              <option key={op.operator_id} value={op.operator_id}>
                {op.name ?? op.operator_id}
                {op.department ? ` · ${op.department}` : ""}
              </option>
            ))}
          </Select>
        </div>
      ) : null}
    </Card>
  );
}

/** Чип оператора; с ✕ — если группа позволяет убрать. */
function OperatorChip({
  op,
  onRemove,
}: {
  op: ScriptGroupOperator;
  onRemove?: () => void;
}) {
  const t = useT();
  const label = op.name ?? op.operator_id;
  return (
    <span
      title={op.department ?? undefined}
      className="inline-flex items-center gap-1.5 rounded-full border border-hair2 bg-canvas px-[11px] py-[5px] text-[12.5px] text-steel"
    >
      {label}
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          aria-label={t("callsboard.script.groups.removeMember")}
          className="text-stone hover:text-neg leading-none cursor-pointer"
        >
          ✕
        </button>
      ) : null}
    </span>
  );
}
