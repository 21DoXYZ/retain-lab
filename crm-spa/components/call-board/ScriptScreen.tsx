"use client";

import { useMemo, useState } from "react";
import { Button, ErrorState, FormField, Select } from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useRole } from "@/lib/role-context";
import { useCallResource } from "./kit";
import { canWriteScript } from "./roles";
import { ScriptEditor } from "./ScriptEditor";
import { ScriptGroups } from "./ScriptGroups";
import { ScriptReadOnly } from "./ScriptReadOnly";
import { useT } from "@/lib/i18n";
import type { ScriptData, ScriptGroupsData, ScriptsData } from "./types";

/**
 * Скрипт (§10.8/§10.9 + 0011). Руководитель/админ ведут НЕСКОЛЬКО именованных
 * скриптов: селектор «какой правим» + кнопка «Новый скрипт» (создал → сохранил →
 * создаёшь следующий). «Какой скрипт куда идёт» — ниже, в блоке групп: у каждой
 * группы селект назначенного скрипта, отдельно — скрипт казино по умолчанию.
 * Оператору — активная версия ЕГО скрипта read-only на TR (резолвит сервер).
 */
export function ScriptScreen() {
  const me = useRole();
  const canWrite = canWriteScript(me.role);
  return canWrite ? <ScriptManage /> : <ScriptOperator />;
}

/** Ветка оператора: активный скрипт read-only, без групп (не трогаем). */
function ScriptOperator() {
  const { state, data, error, reload } = useCallResource<ScriptData>("/api/v1/call-analysis/script");
  if (state === "error") return <ErrorState description={error ?? undefined} onRetry={reload} />;
  if (state !== "data" || !data) return <div className="mt-6 h-64 animate-pulse rounded-card bg-hair2/50" />;
  return <ScriptReadOnly active={data.active} />;
}

/** Ветка руководителя/админа: реестр скриптов + редактор + маршрутизация групп. */
function ScriptManage() {
  const t = useT();
  const [scriptRef, setScriptRef] = useState<string | null>(null);
  // одна inline-форма имени на три операции: создать / переименовать / копия
  const [nameMode, setNameMode] = useState<"create" | "rename" | "duplicate" | null>(null);
  const [newName, setNewName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);

  const registry = useCallResource<ScriptsData>("/api/v1/call-analysis/scripts");
  const groups = useCallResource<ScriptGroupsData>("/api/v1/call-analysis/script/groups");

  // Пока не выбран руками — правим дефолт казино. Исчезнувший из реестра
  // выбор (скрипт удалили в другой вкладке) молча откатывается к дефолту —
  // деривацией, без setState-в-эффекте.
  const knownRefs = useMemo(
    () => new Set((registry.data?.scripts ?? []).map((s) => s.script_ref)),
    [registry.data],
  );
  const selectedValid = scriptRef && (!registry.data || knownRefs.has(scriptRef)) ? scriptRef : null;
  const effectiveRef = selectedValid ?? registry.data?.default_ref ?? null;
  const scriptPath = effectiveRef
    ? `/api/v1/call-analysis/script?script_ref=${encodeURIComponent(effectiveRef)}`
    : "/api/v1/call-analysis/script";
  const script = useCallResource<ScriptData>(scriptPath);

  const current = registry.data?.scripts.find((s) => s.script_ref === effectiveRef) ?? null;

  function reloadAll() {
    registry.reload();
    groups.reload();
    script.reload();
  }

  async function submitName() {
    const name = newName.trim();
    if (!name || !nameMode) return;
    setCreateBusy(true);
    setCreateErr(null);
    try {
      if (nameMode === "create") {
        const res = await flaskFetch<{ script_ref: string }>("/api/v1/call-analysis/scripts", {
          method: "POST",
          body: { name },
        });
        setScriptRef(res.script_ref);   // сразу открываем новый (пустой) скрипт
      } else if (nameMode === "rename" && effectiveRef) {
        await flaskFetch(`/api/v1/call-analysis/scripts/${effectiveRef}`, {
          method: "PATCH",
          body: { name },
        });
      } else if (nameMode === "duplicate" && effectiveRef) {
        const res = await flaskFetch<{ script_ref: string }>(
          `/api/v1/call-analysis/scripts/${effectiveRef}/duplicate`,
          { method: "POST", body: { name } },
        );
        setScriptRef(res.script_ref);   // копия открывается с блоками-черновиком
      }
      setNewName("");
      setNameMode(null);
      reloadAll();
    } catch (e) {
      setCreateErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
    } finally {
      setCreateBusy(false);
    }
  }

  // архив: не удаление — версии остаются в статистике; дефолт/назначенные защищает сервер
  const archiveBlocked = !current || current.is_default || current.groups.length > 0;
  async function archiveScript() {
    if (!effectiveRef) return;
    setCreateBusy(true);
    setCreateErr(null);
    try {
      await flaskFetch(`/api/v1/call-analysis/scripts/${effectiveRef}/archive`, { method: "POST" });
      setScriptRef(null);   // вернуться к дефолту
      reloadAll();
    } catch (e) {
      setCreateErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
    } finally {
      setCreateBusy(false);
    }
  }

  if (script.state === "error") {
    return <ErrorState description={script.error ?? undefined} onRetry={script.reload} />;
  }
  if (script.state !== "data" || !script.data) {
    return <div className="mt-6 h-64 animate-pulse rounded-card bg-hair2/50" />;
  }

  return (
    <>
      {/* Реестр: какой скрипт правим + «Новый скрипт» (0011). */}
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div className="max-w-[340px] flex-1 min-w-[240px]">
          <FormField
            label={t("callsboard.script.picker")}
            hint={t("callsboard.script.pickerHint")}
          >
            <Select
              value={effectiveRef ?? ""}
              onChange={(e) => setScriptRef(e.target.value || null)}
            >
              {(registry.data?.scripts ?? []).length === 0 ? (
                <option value="">{t("callsboard.script.groups.defaultScript")}</option>
              ) : null}
              {(registry.data?.scripts ?? []).map((s) => (
                <option key={s.script_ref} value={s.script_ref}>
                  {s.name}
                  {s.active_version != null ? ` · v${s.active_version}` : ` · ${t("callsboard.script.noActiveShort")}`}
                  {s.is_default ? ` · ${t("callsboard.script.defaultMark")}` : ""}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
        {nameMode ? (
          <div className="flex items-center gap-2">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitName();
                if (e.key === "Escape") setNameMode(null);
              }}
              placeholder={t(
                nameMode === "rename"
                  ? "callsboard.script.renamePlaceholder"
                  : nameMode === "duplicate"
                    ? "callsboard.script.duplicatePlaceholder"
                    : "callsboard.script.createPlaceholder",
              )}
              className="h-[42px] w-[240px] rounded-ctl border border-hair3 bg-canvas px-3 text-[13.5px] text-ink outline-none focus:border-2 focus:border-primary"
            />
            <Button variant="brand" loading={createBusy} disabled={!newName.trim()} onClick={submitName}>
              {t("callsboard.script.createConfirm")}
            </Button>
            <Button variant="ghost" onClick={() => { setNameMode(null); setNewName(""); setCreateErr(null); }}>
              {t("callsboard.script.groups.cancel")}
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <Button variant="ghost" onClick={() => { setNewName(""); setNameMode("create"); }}>
              {t("callsboard.script.create")}
            </Button>
            <Button variant="ghost" disabled={!current}
                    onClick={() => { setNewName(current?.name ?? ""); setNameMode("rename"); }}>
              {t("callsboard.script.rename")}
            </Button>
            <Button variant="ghost" disabled={!current}
                    onClick={() => { setNewName(current ? `${current.name} (копия)` : ""); setNameMode("duplicate"); }}>
              {t("callsboard.script.duplicate")}
            </Button>
            <Button variant="ghost" disabled={archiveBlocked} loading={createBusy}
                    title={archiveBlocked ? t("callsboard.script.archiveBlocked") : undefined}
                    onClick={archiveScript}>
              {t("callsboard.script.archive")}
            </Button>
          </div>
        )}
      </div>
      {createErr ? <div className="mt-2 text-[13px] text-neg">{createErr}</div> : null}

      <ScriptEditor
        key={`${effectiveRef ?? "default"}:${script.data.active?.version ?? "draft"}`}
        initial={script.data}
        scriptRef={effectiveRef}
        scriptName={current?.name ?? script.data.script_name ?? null}
        isDefault={current?.is_default ?? true}
        onReload={reloadAll}
      />

      {groups.data ? (
        <div className="mt-8">
          <ScriptGroups
            data={groups.data}
            scripts={registry.data?.scripts ?? []}
            defaultRef={registry.data?.default_ref ?? null}
            onChanged={reloadAll}
          />
        </div>
      ) : null}
    </>
  );
}
