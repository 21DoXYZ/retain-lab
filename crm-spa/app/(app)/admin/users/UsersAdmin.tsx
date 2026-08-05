"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useT, type MessageKey } from "@/lib/i18n";
import { isNavKeyEnabled } from "@/lib/modules";
import {
  PageHeader,
  Panel,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  Button,
  Badge,
  Modal,
  FormField,
  Input,
  Select,
} from "@/components/ui";
import { creatableRoles, canManageUser } from "@/lib/permissions";
import type { AdminUserRow, CurrentUser, Department, UserRole } from "@/lib/types";

/** Role/department label keys — lib/permissions.ts owns ROLE_LABELS/DEPT_LABELS
 * (data, not touched here); this maps each code to its "admin.*" translation key. */
const ROLE_KEY: Record<UserRole, MessageKey> = {
  super_admin: "admin.role.super_admin",
  director: "admin.role.director",
  head_retention: "admin.role.head_retention",
  head_department: "admin.role.head_department",
  operator: "admin.role.operator",
  vip_manager: "admin.role.vip_manager",
  affiliate_manager: "admin.role.affiliate_manager",
  marketing_manager: "admin.role.marketing_manager",
  analyst: "admin.role.analyst",
  finance: "admin.role.finance",
  risk_officer: "admin.role.risk_officer",
  support: "admin.role.support",
  affiliate: "admin.role.affiliate",
  viewer: "admin.role.viewer",
};

const DEPT_KEY: Record<Department, MessageKey> = {
  retention: "admin.dept.retention",
  call_center: "admin.dept.call_center",
  whatsapp: "admin.dept.whatsapp",
};

/**
 * Machine error codes from app/api/admin/users/*route.ts (fail(msg, status,
 * code)) → translation key. Only the fixed, non-interpolated failure messages
 * get a code; raw Supabase/GoTrue errors are passed through untranslated by
 * the server (no code), so an unmapped/missing code here just means "show the
 * server's text as-is" — see the call() function below.
 */
const ERROR_KEY: Record<string, MessageKey> = {
  unauthorized: "admin.error.unauthorized",
  bad_request: "admin.error.bad_request",
  name_required: "admin.error.name_required",
  invalid_email: "admin.error.invalid_email",
  unknown_role: "admin.error.unknown_role",
  unknown_department: "admin.error.unknown_department",
  password_too_short: "admin.error.password_too_short",
  affiliate_code_required: "admin.error.affiliate_code_required",
  department_required: "admin.error.department_required",
  role_not_allowed: "admin.error.role_not_allowed",
  email_already_exists: "admin.error.email_already_exists",
  user_not_found: "admin.error.user_not_found",
  forbidden: "admin.error.forbidden",
  unknown_action: "admin.error.unknown_action",
  reassign_same_operator: "admin.error.reassign_same_operator",
  reassign_target_not_found: "admin.error.reassign_target_not_found",
};

/**
 * User administration UI. All mutations go through the /api/admin/* route
 * handlers (which re-check permissions server-side and write audit_log); this
 * screen only shows controls the caller is allowed to use and refreshes the
 * server-rendered list after each action.
 */

interface Props {
  me: CurrentUser;
  initialUsers: AdminUserRow[];
}

type Flash = { type: "ok" | "err"; text: string } | null;

const DEPTS: Department[] = ["retention", "call_center", "whatsapp"];

export function UsersAdmin({ me, initialUsers }: Props) {
  const t = useT();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);

  // create form
  const [createOpen, setCreateOpen] = useState(false);
  const roles = useMemo(() => creatableRoles(me.role), [me.role]);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    role: (roles[0] ?? "operator") as UserRole,
    department: (me.role === "head_department" ? me.department : "call_center") as Department | null,
    affiliate_code: "",
    password: "",
  });

  // reset / delete targets
  const [resetTarget, setResetTarget] = useState<AdminUserRow | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<AdminUserRow | null>(null);
  const [reassignTo, setReassignTo] = useState("");

  const operators = useMemo(
    () =>
      initialUsers.filter(
        (u) =>
          u.role === "operator" &&
          u.is_active &&
          (me.role !== "head_department" || u.department === me.department),
      ),
    [initialUsers, me],
  );

  async function call(path: string, method: string, body?: unknown): Promise<boolean> {
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch(path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || json.ok === false) {
        // Prefer the machine code (translated via ERROR_KEY) when the server
        // sent one; fall back to its raw text (untranslated — e.g. a passed-
        // through Supabase/GoTrue message), then to a generic status message.
        const codeKey = typeof json.code === "string" ? ERROR_KEY[json.code] : undefined;
        setFlash({
          type: "err",
          text: codeKey
            ? t(codeKey)
            : json.error ?? t("admin.users.flash.errorStatus", { status: res.status }),
        });
        return false;
      }
      return true;
    } catch (e) {
      setFlash({
        type: "err",
        text: e instanceof Error ? e.message : t("admin.users.flash.networkError"),
      });
      return false;
    } finally {
      setBusy(false);
    }
  }

  function openCreate(preset: UserRole) {
    setForm({
      full_name: "",
      email: "",
      role: preset,
      department: me.role === "head_department" ? me.department : "call_center",
      affiliate_code: "",
      password: "",
    });
    setFlash(null);
    setCreateOpen(true);
  }

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    const needsDept = form.role === "operator" || form.role === "head_department";
    const needsAff = form.role === "affiliate";
    const ok = await call("/api/admin/users", "POST", {
      full_name: form.full_name,
      email: form.email,
      role: form.role,
      department: needsDept ? form.department : null,
      affiliate_code: needsAff ? form.affiliate_code : null,
      password: form.password || undefined,
    });
    if (ok) {
      setCreateOpen(false);
      setFlash({ type: "ok", text: t("admin.users.flash.created") });
      router.refresh();
    }
  }

  async function toggleBlock(u: AdminUserRow) {
    const ok = await call(`/api/admin/users/${u.id}`, "PATCH", {
      action: u.is_active ? "block" : "unblock",
    });
    if (ok) {
      setFlash({
        type: "ok",
        text: u.is_active
          ? t("admin.users.flash.blocked")
          : t("admin.users.flash.unblocked"),
      });
      router.refresh();
    }
  }

  async function submitReset(e: React.FormEvent) {
    e.preventDefault();
    if (!resetTarget) return;
    const ok = await call(`/api/admin/users/${resetTarget.id}`, "PATCH", {
      action: "reset_password",
      password: newPassword,
    });
    if (ok) {
      setResetTarget(null);
      setNewPassword("");
      setFlash({ type: "ok", text: t("admin.users.flash.passwordChanged") });
    }
  }

  async function submitDelete(e: React.FormEvent) {
    e.preventDefault();
    if (!deleteTarget) return;
    const ok = await call(`/api/admin/users/${deleteTarget.id}`, "DELETE", {
      reassign_to: reassignTo || null,
    });
    if (ok) {
      setDeleteTarget(null);
      setReassignTo("");
      setFlash({ type: "ok", text: t("admin.users.flash.deleted") });
      router.refresh();
    }
  }

  const needsDept = form.role === "operator" || form.role === "head_department";
  const needsAff = form.role === "affiliate";
  // SaaS-пресет: аффилиатский кабинет скрыт модулем - кнопку тоже прячем
  const canMakeAffiliate = roles.includes("affiliate") && isNavKeyEnabled("affiliate_cabinet");

  return (
    <>
      <PageHeader
        title={t("admin.users.title")}
        lead={t("admin.users.lead")}
        right={
          <>
            <Button variant="brand" onClick={() => openCreate(roles.includes("operator") ? "operator" : roles[0])}>
              {t("admin.users.createOperator")}
            </Button>
            {canMakeAffiliate ? (
              <Button variant="ghost" onClick={() => openCreate("affiliate")}>
                {t("admin.users.createAffiliate")}
              </Button>
            ) : null}
          </>
        }
      />

      {flash ? (
        <div
          className={
            "mt-4 text-[13px] rounded-ctl px-3.5 py-2.5 border " +
            (flash.type === "ok"
              ? "text-pos bg-cream border-beige"
              : "text-neg bg-cream border-beige")
          }
        >
          {flash.text}
        </div>
      ) : null}

      <div className="mt-5">
        <Panel>
          <Table>
            <THead>
              <TR>
                <TH>{t("admin.users.col.name")}</TH>
                <TH className="text-left">{t("admin.users.col.login")}</TH>
                <TH className="text-left">{t("admin.users.col.role")}</TH>
                <TH className="text-left">{t("admin.users.col.scope")}</TH>
                <TH className="text-left">{t("admin.users.col.status")}</TH>
                <TH>{t("admin.users.col.actions")}</TH>
              </TR>
            </THead>
            <TBody>
              {initialUsers.map((u) => {
                const manageable = canManageUser(me, u);
                const scope = u.affiliate_code ?? (u.department ? t(DEPT_KEY[u.department]) : "—");
                return (
                  <TR key={u.id}>
                    <TD className="text-left font-medium text-ink">{u.full_name}</TD>
                    <TD className="text-left font-mono text-steel">{u.email}</TD>
                    <TD className="text-left">
                      <Badge bg="#ecf3ff" fg="#3641f5">{t(ROLE_KEY[u.role])}</Badge>
                    </TD>
                    <TD className="text-left text-slate">{scope}</TD>
                    <TD className="text-left">
                      {u.is_active ? (
                        <span className="text-pos text-[12.5px] font-medium">{t("admin.users.status.active")}</span>
                      ) : (
                        <span className="text-neg text-[12.5px] font-medium">{t("admin.users.status.blocked")}</span>
                      )}
                    </TD>
                    <TD>
                      {manageable ? (
                        <div className="flex gap-1.5 justify-end">
                          <Button size="sm" variant="ghost" onClick={() => toggleBlock(u)} disabled={busy}>
                            {u.is_active ? t("admin.users.action.block") : t("admin.users.action.unblock")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setNewPassword("");
                              setFlash(null);
                              setResetTarget(u);
                            }}
                            disabled={busy}
                          >
                            {t("admin.users.action.password")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setReassignTo("");
                              setFlash(null);
                              setDeleteTarget(u);
                            }}
                            disabled={busy}
                          >
                            {t("admin.users.action.delete")}
                          </Button>
                        </div>
                      ) : (
                        <span className="text-stone">—</span>
                      )}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </Panel>
      </div>

      {/* -------- Create -------- */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={form.role === "affiliate" ? t("admin.users.modal.createAffiliateTitle") : t("admin.users.modal.createUserTitle")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>{t("admin.users.btn.cancel")}</Button>
            <Button variant="brand" onClick={submitCreate} loading={busy}>{t("admin.users.btn.create")}</Button>
          </>
        }
      >
        <form onSubmit={submitCreate} className="grid gap-4">
          <FormField label={t("admin.users.field.name")} required>
            <Input
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              placeholder={t("admin.users.field.namePlaceholder")}
              required
            />
          </FormField>
          <FormField label={t("admin.users.field.loginEmail")} required hint={t("admin.users.field.loginHint")}>
            <Input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="operator@crm.local"
              required
            />
          </FormField>
          <FormField label={t("admin.users.field.role")}>
            <Select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value as UserRole })}
            >
              {roles.map((r) => (
                <option key={r} value={r}>{t(ROLE_KEY[r])}</option>
              ))}
            </Select>
          </FormField>
          {needsDept ? (
            <FormField label={t("admin.users.field.dept")} required>
              <Select
                value={form.department ?? ""}
                onChange={(e) => setForm({ ...form, department: e.target.value as Department })}
                disabled={me.role === "head_department"}
              >
                {DEPTS.map((d) => (
                  <option key={d} value={d}>{t(DEPT_KEY[d])}</option>
                ))}
              </Select>
            </FormField>
          ) : null}
          {needsAff ? (
            <FormField label={t("admin.users.field.affCode")} required hint={t("admin.users.field.affCodeHint")}>
              <Input
                value={form.affiliate_code}
                onChange={(e) => setForm({ ...form, affiliate_code: e.target.value })}
                placeholder="AF104"
                required
              />
            </FormField>
          ) : null}
          <FormField label={t("admin.users.field.password")} hint={t("admin.users.field.passwordHint")}>
            <Input
              type="text"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder="crm12345"
            />
          </FormField>
        </form>
      </Modal>

      {/* -------- Reset password -------- */}
      <Modal
        open={resetTarget !== null}
        onClose={() => setResetTarget(null)}
        title={t("admin.users.modal.resetTitle")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setResetTarget(null)}>{t("admin.users.btn.cancel")}</Button>
            <Button variant="brand" onClick={submitReset} loading={busy}>{t("admin.users.btn.save")}</Button>
          </>
        }
      >
        <form onSubmit={submitReset}>
          <div className="text-[13px] text-steel mb-3">
            {t("admin.users.resetBody", {
              name: resetTarget?.full_name ?? "",
              email: resetTarget?.email ?? "",
            })}
          </div>
          <FormField label={t("admin.users.field.newPassword")} required hint={t("admin.users.field.newPasswordHint")}>
            <Input
              type="text"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder={t("admin.users.field.newPasswordPlaceholder")}
              required
            />
          </FormField>
        </form>
      </Modal>

      {/* -------- Delete with reassignment -------- */}
      <Modal
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={t("admin.users.modal.deleteTitle")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>{t("admin.users.btn.cancel")}</Button>
            <Button variant="brand" onClick={submitDelete} loading={busy}>{t("admin.users.action.delete")}</Button>
          </>
        }
      >
        <form onSubmit={submitDelete}>
          <div className="text-[13px] text-steel mb-3">
            {t("admin.users.deleteBody", {
              name: deleteTarget?.full_name ?? "",
              email: deleteTarget?.email ?? "",
            })}
          </div>
          <FormField label={t("admin.users.field.reassignTo")} hint={t("admin.users.field.reassignHint")}>
            <Select value={reassignTo} onChange={(e) => setReassignTo(e.target.value)}>
              <option value="">{t("admin.users.reassignNone")}</option>
              {operators
                .filter((o) => o.id !== deleteTarget?.id)
                .map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.full_name} ({o.department ? t(DEPT_KEY[o.department]) : "—"})
                  </option>
                ))}
            </Select>
          </FormField>
        </form>
      </Modal>
    </>
  );
}
