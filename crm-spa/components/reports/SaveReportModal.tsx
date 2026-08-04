"use client";

import { useState } from "react";
import { Modal, Button, Chip, FormField, Input, Select } from "@/components/ui";
import { flaskFetch, flaskErrorText, FlaskApiError } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { SAVE_ROLE_OPTIONS, type ReportSpec, type SavedReport, type Visibility } from "./types";

/**
 * SaveReportModal — сохранить текущий spec как отчёт (POST) или обновить открытый
 * (PUT). Видимость personal/shared/roles + мультиселект ролей при roles; чекбокс
 * «официальный» — только для OFFICIAL_ROLES (director/head_retention/super_admin),
 * бэкенд повторно это проверяет (403). 409 (дубль имени) — инлайн-ошибка.
 *
 * Свежее состояние на каждое открытие: ReportBuilder монтирует модалку по `key`.
 */
interface SaveReportModalProps {
  onClose: () => void;
  spec: ReportSpec;
  /** Открытый из списка отчёт (для режима «обновить»); null — сохраняем новый. */
  loaded: SavedReport | null;
  canOfficial: boolean;
  onSaved: () => void;
}

export function SaveReportModal({ onClose, spec, loaded, canOfficial, onSaved }: SaveReportModalProps) {
  const t = useT();
  const editable = Boolean(loaded?.mine);

  const [name, setName] = useState(loaded?.name ?? "");
  const [visibility, setVisibility] = useState<Visibility>(loaded?.visibility ?? "personal");
  const [roles, setRoles] = useState<string[]>(loaded?.roles ?? []);
  const [official, setOfficial] = useState(loaded?.is_official ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleRole(role: string) {
    setRoles((cur) => (cur.includes(role) ? cur.filter((r) => r !== role) : [...cur, role]));
  }

  async function submit(asNew: boolean) {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t("reports.save.nameRequired"));
      return;
    }
    if (spec.metrics.length === 0) {
      setError(t("reports.save.noMetrics"));
      return;
    }
    setBusy(true);
    setError(null);
    const body = {
      name: trimmed,
      spec,
      visibility,
      roles: visibility === "roles" ? roles : [],
      is_official: official,
    };
    try {
      if (editable && !asNew && loaded) {
        await flaskFetch(`/api/v1/reports/saved/${loaded.report_id}`, { method: "PUT", body });
      } else {
        await flaskFetch("/api/v1/reports/saved", { method: "POST", body });
      }
      onSaved();
      onClose();
    } catch (e: unknown) {
      if (e instanceof FlaskApiError && e.status === 409) {
        setError(t("reports.save.duplicate"));
      } else {
        setError(flaskErrorText(e, t, "reports.save.failed"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={t("reports.save.title")}
      widthClass="max-w-lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("ui.cancel")}
          </Button>
          {editable ? (
            <>
              <Button variant="ghost" onClick={() => submit(true)} disabled={busy}>
                {t("reports.save.asNew")}
              </Button>
              <Button variant="brand" onClick={() => submit(false)} loading={busy}>
                {t("reports.save.update")}
              </Button>
            </>
          ) : (
            <Button variant="brand" onClick={() => submit(true)} loading={busy}>
              {t("reports.save.submit")}
            </Button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField label={t("reports.save.name")} required>
          <Input
            value={name}
            autoFocus
            placeholder={t("reports.save.name.placeholder")}
            onChange={(e) => setName(e.target.value)}
          />
        </FormField>

        <FormField label={t("reports.save.visibility")}>
          <Select value={visibility} onChange={(e) => setVisibility(e.target.value as Visibility)}>
            <option value="personal">{t("reports.save.visibility.personal")}</option>
            <option value="shared">{t("reports.save.visibility.shared")}</option>
            <option value="roles">{t("reports.save.visibility.roles")}</option>
          </Select>
        </FormField>

        {visibility === "roles" ? (
          <FormField label={t("reports.save.roles")} hint={t("reports.save.roles.hint")}>
            <div className="flex flex-wrap gap-1.5">
              {SAVE_ROLE_OPTIONS.map((role) => (
                <Chip key={role} active={roles.includes(role)} onClick={() => toggleRole(role)}>
                  {t(`admin.role.${role}` as MessageKey)}
                </Chip>
              ))}
            </div>
            {roles.length === 0 ? (
              <span className="text-[12px] text-stone mt-1">{t("reports.save.roles.empty")}</span>
            ) : null}
          </FormField>
        ) : null}

        {canOfficial ? (
          <label className="flex items-start gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={official}
              onChange={(e) => setOfficial(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-primary cursor-pointer"
            />
            <span>
              <span className="text-[13.5px] font-medium text-ink">⭐ {t("reports.save.official")}</span>
              <span className="block text-[12px] text-steel">{t("reports.save.official.hint")}</span>
            </span>
          </label>
        ) : null}

        {error ? <p className="text-[12.5px] text-neg">{error}</p> : null}
      </div>
    </Modal>
  );
}
