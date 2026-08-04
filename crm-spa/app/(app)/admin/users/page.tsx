import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { canAccessAdmin } from "@/lib/permissions";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { UsersAdmin } from "./UsersAdmin";
import type { AdminUserRow } from "@/lib/types";

/**
 * /admin/users — user administration (super_admin / head_retention /
 * head_department per the "who creates whom" matrix).
 *
 * The list is RLS-scoped: it is read with the CALLER's session, so each admin
 * only sees the users they are allowed to (e.g. a head_department sees their
 * own department's operators). Emails live in auth.users, so they are fetched
 * with the service-role client and joined onto the visible rows only.
 */
export const dynamic = "force-dynamic";

export default async function AdminUsersPage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");
  if (!canAccessAdmin(me.role)) redirect("/");

  // RLS-scoped profiles (what this admin may see).
  const supabase = await createClient();
  const { data: rows } = await supabase
    .schema("crm")
    .from("crm_users")
    .select("id, full_name, role, department, affiliate_code, is_active, created_at")
    .order("created_at", { ascending: true });

  // Emails from auth.users via service role, mapped to the visible ids only.
  const admin = createAdminClient();
  const emailById = new Map<string, string>();
  for (let page = 1; page <= 10; page++) {
    const { data } = await admin.auth.admin.listUsers({ page, perPage: 200 });
    const users = data?.users ?? [];
    users.forEach((u) => emailById.set(u.id, u.email ?? ""));
    if (users.length < 200) break;
  }

  const users: AdminUserRow[] = (rows ?? []).map((r) => ({
    ...r,
    email: emailById.get(r.id) ?? "",
  }));

  return <UsersAdmin me={me} initialUsers={users} />;
}
