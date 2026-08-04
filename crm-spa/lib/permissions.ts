import type { CurrentUser, Department, UserRole } from "./types";

/**
 * Pure authorization rules — shared by the admin route handlers (server, hard
 * enforcement) and the admin UI (client, show/hide controls). No server or
 * Supabase imports so it is safe to use in "use client" components.
 *
 * These mirror the DB guard trigger crm.guard_user_mutation and the RLS
 * policies in supabase/migrations (0001/0002). App checks are the first line;
 * the DB is the backstop (defense-in-depth).
 */

/** Roles allowed to open the /admin/users screen at all. */
export function canAccessAdmin(role: UserRole): boolean {
  return (
    role === "super_admin" ||
    role === "head_retention" ||
    role === "head_department"
  );
}

/**
 * Which roles a given actor may create ("кто создаёт кого", plan §1).
 * super_admin → any; head_retention → retention vertical + affiliate cabinets;
 * head_department → operator (own department only, enforced in canCreateUser);
 * affiliate_manager → affiliate cabinets. Everyone else → none.
 */
export function creatableRoles(actorRole: UserRole): UserRole[] {
  switch (actorRole) {
    case "super_admin":
      return [
        "director",
        "head_retention",
        "head_department",
        "operator",
        "vip_manager",
        "affiliate_manager",
        "marketing_manager",
        "analyst",
        "finance",
        "risk_officer",
        "support",
        "affiliate",
        "viewer",
      ];
    case "head_retention":
      return ["head_department", "operator", "vip_manager", "affiliate"];
    case "head_department":
      return ["operator"];
    case "affiliate_manager":
      return ["affiliate"];
    default:
      return [];
  }
}

/** Can `actor` create a user with `targetRole` in `targetDept`? */
export function canCreateUser(
  actor: Pick<CurrentUser, "role" | "department">,
  targetRole: UserRole,
  targetDept: Department | null,
): boolean {
  if (!creatableRoles(actor.role).includes(targetRole)) return false;
  // head_department may only add operators to its OWN department.
  if (actor.role === "head_department") {
    return targetRole === "operator" && targetDept === actor.department;
  }
  return true;
}

/**
 * Can `actor` manage (block / unblock / reset password / delete) `target`?
 * super_admin → anyone; head_retention → anyone except super_admin;
 * head_department → operators of its own department. Nobody manages themselves
 * through this screen (self-lockout guard is applied in the UI/handlers).
 */
export function canManageUser(
  actor: Pick<CurrentUser, "role" | "department" | "id">,
  target: Pick<CurrentUser, "role" | "department" | "id">,
): boolean {
  if (actor.id === target.id) return false;
  switch (actor.role) {
    case "super_admin":
      return true;
    case "head_retention":
      return target.role !== "super_admin";
    case "head_department":
      return (
        target.role === "operator" && target.department === actor.department
      );
    default:
      return false;
  }
}

/**
 * Landing route for each role after login (plan §6 "дефолтный роут по роли").
 * Exposed so app/(app)/page.tsx can redirect and the landing can link there.
 * NOTE: some targets (/queue, /overview, /affiliate) are built by later waves
 * (B2/B4/C) — until then the (app) index renders a role-scoped landing instead
 * of hard-redirecting, to keep the app navigable.
 */
export function roleHome(role: UserRole): string {
  switch (role) {
    case "operator":
    case "vip_manager":
      return "/queue";
    case "head_department":
      return "/desk";
    case "affiliate":
      return "/affiliate";
    case "support":
    case "viewer":
      return "/players"; // список игроков (короткая/маскированная карточка)
    case "marketing_manager":
      return "/actions"; // Действия / Офферы (казино-GGR /overview закрыт по правам)
    case "affiliate_manager":
      return "/affiliates";
    case "risk_officer":
      return "/audit";
    default:
      // super_admin, head_retention, director, analyst, finance → казино-обзор
      return "/overview";
  }
}

export const ROLE_LABELS: Record<UserRole, string> = {
  super_admin: "Супер-админ",
  director: "Директор",
  head_retention: "Глава ретеншена",
  head_department: "Глава отдела",
  operator: "Оператор",
  vip_manager: "VIP-менеджер",
  affiliate_manager: "Трафик-менеджер",
  marketing_manager: "Маркетинг",
  analyst: "Аналитик",
  finance: "Финансист",
  risk_officer: "Риск-офицер",
  support: "Саппорт",
  affiliate: "Аффилиат",
  viewer: "Гость",
};

export const DEPT_LABELS: Record<Department, string> = {
  retention: "Ретеншн",
  call_center: "Колл-центр",
  whatsapp: "WhatsApp",
};
