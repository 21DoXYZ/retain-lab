import { getCurrentUser } from "@/lib/auth";
import { createAdminClient } from "@/lib/supabase/admin";
import { canManageUser } from "@/lib/permissions";
import { auditLog, fail, ok, loadTarget } from "@/lib/admin-api";

/**
 * PATCH /api/admin/users/:id — block | unblock | reset_password.
 * DELETE /api/admin/users/:id — delete, reassigning the user's players first.
 *
 * Both authenticate the caller, load the target's role/department, and check
 * canManageUser (super_admin → anyone; head_retention → all but super_admin;
 * head_department → own-department operators; never yourself). Every action is
 * written to crm.audit_log.
 *
 * Block/unblock bans the account in GoTrue (真 login block) AND flips
 * crm_users.is_active, so the (app) layout also bounces an already-open session.
 */

const BAN_FOREVER = "876000h"; // ~100 years

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const me = await getCurrentUser();
  if (!me) return fail("Не авторизовано", 401, "unauthorized");

  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return fail("Некорректный запрос", 400, "bad_request");
  }
  const action = String(body.action ?? "");

  const admin = createAdminClient();
  const target = await loadTarget(admin, id);
  if (!target) return fail("Пользователь не найден", 404, "user_not_found");
  if (!canManageUser(me, target)) return fail("Недостаточно прав", 403, "forbidden");

  if (action === "block" || action === "unblock") {
    const blocking = action === "block";
    const { error: authErr } = await admin.auth.admin.updateUserById(id, {
      ban_duration: blocking ? BAN_FOREVER : "none",
    });
    if (authErr) return fail(authErr.message, 400);
    const { error: profErr } = await admin
      .schema("crm")
      .from("crm_users")
      .update({ is_active: !blocking })
      .eq("id", id);
    if (profErr) return fail(profErr.message, 400);
    await auditLog(admin, me.id, blocking ? "block_user" : "unblock_user", "user", id, {});
    return ok({ id, is_active: !blocking });
  }

  if (action === "reset_password") {
    const password = String(body.password ?? "");
    if (password.length < 6) return fail("Пароль минимум 6 символов", 400, "password_too_short");
    const { error: authErr } = await admin.auth.admin.updateUserById(id, { password });
    if (authErr) return fail(authErr.message, 400);
    await auditLog(admin, me.id, "reset_password", "user", id, {});
    return ok({ id });
  }

  return fail("Неизвестное действие", 400, "unknown_action");
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const me = await getCurrentUser();
  if (!me) return fail("Не авторизовано", 401, "unauthorized");

  let reassignTo: string | null = null;
  try {
    const body = (await request.json()) as Record<string, unknown>;
    reassignTo = body.reassign_to ? String(body.reassign_to) : null;
  } catch {
    // no body — delete without reassignment
  }

  const admin = createAdminClient();
  const target = await loadTarget(admin, id);
  if (!target) return fail("Пользователь не найден", 404, "user_not_found");
  if (!canManageUser(me, target)) return fail("Недостаточно прав", 403, "forbidden");

  let reassignedCount = 0;
  if (reassignTo) {
    if (reassignTo === id)
      return fail("Нельзя передать игроков тому же оператору", 400, "reassign_same_operator");
    const dest = await loadTarget(admin, reassignTo);
    if (!dest) return fail("Оператор для передачи не найден", 400, "reassign_target_not_found");

    // Move only players the destination doesn't already have (UNIQUE constraint);
    // duplicates are dropped by the cascade on user delete (no data loss — dest
    // already has them). This preserves the transferred players' queue history.
    const { data: mine } = await admin
      .schema("crm")
      .from("player_assignments")
      .select("id, casino_player_id")
      .eq("operator_id", id);
    const { data: theirs } = await admin
      .schema("crm")
      .from("player_assignments")
      .select("casino_player_id")
      .eq("operator_id", reassignTo);

    const destSet = new Set((theirs ?? []).map((r) => r.casino_player_id));
    const moveIds = (mine ?? [])
      .filter((a) => !destSet.has(a.casino_player_id))
      .map((a) => a.id);

    if (moveIds.length > 0) {
      const { error: moveErr } = await admin
        .schema("crm")
        .from("player_assignments")
        .update({ operator_id: reassignTo, assigned_by: me.id })
        .in("id", moveIds);
      if (moveErr) return fail(`Не удалось передать игроков: ${moveErr.message}`, 400);
      reassignedCount = moveIds.length;
    }
  }

  // Deleting the auth user cascades to crm_users and any remaining assignments.
  const { error: delErr } = await admin.auth.admin.deleteUser(id);
  if (delErr) return fail(delErr.message, 400);

  await auditLog(admin, me.id, "delete_user", "user", id, {
    reassigned_to: reassignTo,
    reassigned_count: reassignedCount,
  });

  return ok({ id, reassigned: reassignedCount });
}
