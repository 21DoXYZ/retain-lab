/**
 * Shared domain types for the CRM-SPA. Mirrors the Postgres enums in
 * supabase/migrations/0001_crm_schema.sql (crm.user_role, crm.department).
 * Keep this in sync with the DB enums — it is the single TS source of truth
 * for roles used by auth, the role context, the nav matrix and the admin API.
 */

/** All 14 system roles (SPA_BUILD_PLAN.md §1). Order = as in the plan. */
export type UserRole =
  | "super_admin"
  | "director"
  | "head_retention"
  | "head_department"
  | "operator"
  | "vip_manager"
  | "affiliate_manager"
  | "marketing_manager"
  | "analyst"
  | "finance"
  | "risk_officer"
  | "support"
  | "affiliate"
  | "viewer";

export type Department = "retention" | "call_center" | "whatsapp";

/**
 * The signed-in user as the SPA sees it — the auth.users id joined with the
 * crm.crm_users profile. Returned by lib/auth.getCurrentUser() (server) and
 * provided to children via lib/role-context (client, useRole()).
 */
export interface CurrentUser {
  id: string;
  full_name: string;
  role: UserRole;
  department: Department | null;
  /** Only set for role === 'affiliate' (e.g. "AF104"). */
  affiliate_code: string | null;
  is_active: boolean;
}

/** A crm.crm_users row enriched with the auth email — used by the admin screen. */
export interface AdminUserRow {
  id: string;
  full_name: string;
  role: UserRole;
  department: Department | null;
  affiliate_code: string | null;
  is_active: boolean;
  created_at: string;
  email: string;
}
