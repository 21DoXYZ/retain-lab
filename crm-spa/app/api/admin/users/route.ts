import { getCurrentUser } from "@/lib/auth";
import { createAdminClient } from "@/lib/supabase/admin";
import { canCreateUser } from "@/lib/permissions";
import { auditLog, fail, ok } from "@/lib/admin-api";
import type { Department, UserRole } from "@/lib/types";

/**
 * POST /api/admin/users — create a user (operator, vip_manager, head_department,
 * affiliate cabinet, ...). Flow (plan §B1.4):
 *   1. Authenticate the caller (RLS-bound session).
 *   2. Validate input.
 *   3. Authorize "who creates whom" (canCreateUser — mirrors crm.guard trigger).
 *   4. Create the GoTrue auth user (service role), then the crm.crm_users row.
 *      Roll back the auth user if the profile insert fails.
 *   5. Write an audit_log entry as the caller.
 *
 * Affiliate cabinets are just role="affiliate" + affiliate_code (no department).
 */

/**
 * Стойкий случайный временный пароль (не хардкод). Возвращается создателю ОДИН
 * раз в ответе, чтобы передать пользователю; при первом входе пусть сменит.
 */
function generateTempPassword(): string {
  return (crypto.randomUUID() + crypto.randomUUID()).replace(/-/g, "").slice(0, 20);
}

const VALID_ROLES: UserRole[] = [
  "super_admin", "director", "head_retention", "head_department", "operator",
  "vip_manager", "affiliate_manager", "marketing_manager", "analyst",
  "finance", "risk_officer", "support", "affiliate", "viewer",
];
const VALID_DEPTS: Department[] = ["retention", "call_center", "whatsapp"];

export async function POST(request: Request) {
  const me = await getCurrentUser();
  if (!me) return fail("Не авторизовано", 401, "unauthorized");

  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return fail("Некорректный запрос", 400, "bad_request");
  }

  const full_name = String(body.full_name ?? "").trim();
  const email = String(body.email ?? "").trim().toLowerCase();
  const role = body.role as UserRole;
  const department = (body.department ? String(body.department) : null) as Department | null;
  const affiliate_code = body.affiliate_code ? String(body.affiliate_code).trim() : null;
  const providedPassword = body.password ? String(body.password) : null;
  const password = providedPassword ?? generateTempPassword();

  // --- validation ---
  if (!full_name) return fail("Укажите имя", 400, "name_required");
  if (!email || !email.includes("@"))
    return fail("Укажите корректный e-mail (логин)", 400, "invalid_email");
  if (!role || !VALID_ROLES.includes(role)) return fail("Неизвестная роль", 400, "unknown_role");
  if (department && !VALID_DEPTS.includes(department))
    return fail("Неизвестный отдел", 400, "unknown_department");
  if (password.length < 6) return fail("Пароль минимум 6 символов", 400, "password_too_short");
  if (role === "affiliate" && !affiliate_code)
    return fail("Укажите affiliate-код", 400, "affiliate_code_required");
  if ((role === "operator" || role === "head_department") && !department)
    return fail("Укажите отдел", 400, "department_required");

  // --- authorization (server-side; DB guard is the backstop) ---
  if (!canCreateUser(me, role, department))
    return fail("Недостаточно прав для создания пользователя с этой ролью", 403, "role_not_allowed");

  const admin = createAdminClient();

  // --- create auth user ---
  const { data: created, error: authErr } = await admin.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
    user_metadata: { full_name },
  });
  if (authErr || !created?.user) {
    // "already exists" is a fixed, translatable message; anything else passes
    // the raw GoTrue error through untranslated (see fail()'s code param doc).
    if (authErr?.message?.toLowerCase().includes("already")) {
      return fail("Пользователь с таким e-mail уже существует", 400, "email_already_exists");
    }
    return fail(authErr?.message ?? "Не удалось создать учётную запись", 400);
  }
  const id = created.user.id;

  // --- create crm profile ---
  const { error: profErr } = await admin
    .schema("crm")
    .from("crm_users")
    .insert({
      id,
      full_name,
      role,
      department,
      affiliate_code: role === "affiliate" ? affiliate_code : null,
      created_by: me.id,
    });
  if (profErr) {
    await admin.auth.admin.deleteUser(id); // roll back the orphaned auth user
    return fail(`Не удалось создать профиль: ${profErr.message}`, 400);
  }

  await auditLog(admin, me.id, "create_user", "user", id, {
    role,
    department,
    email,
    affiliate_code: role === "affiliate" ? affiliate_code : null,
  });

  // Если пароль сгенерирован — вернуть его создателю один раз (для передачи юзеру).
  return ok(providedPassword ? { id } : { id, generated_password: password });
}
