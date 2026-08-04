"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { ROLE_LABELS, DEPT_LABELS } from "@/lib/permissions";
import { Button } from "@/components/ui";
import { useT, type MessageKey } from "@/lib/i18n";
import type { CurrentUser } from "@/lib/types";

/**
 * Top-right identity chip + sign-out, shown in the AppShell header. Reads the
 * current user (passed down from the server layout) and signs out via the
 * browser Supabase client, then returns to /login.
 */
export function UserMenu({ user }: { user: CurrentUser }) {
  const router = useRouter();
  const t = useT();
  const [loading, setLoading] = useState(false);

  async function signOut() {
    setLoading(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  // Роль/отдел — через ключи словаря ("admin.role.*" / "admin.dept.*"); константы
  // ROLE_LABELS/DEPT_LABELS в lib/permissions остаются русскими данными (они общие
  // и не знают про локаль) и служат фолбэком.
  const roleLabel = t(`admin.role.${user.role}` as MessageKey) || ROLE_LABELS[user.role];
  const scope = user.affiliate_code
    ? user.affiliate_code
    : user.department
      ? t(`admin.dept.${user.department}` as MessageKey) || DEPT_LABELS[user.department]
      : null;

  return (
    <div className="flex items-center gap-3">
      <div className="text-right leading-tight">
        <div className="text-[13px] font-semibold text-ink">{user.full_name}</div>
        <div className="text-[11.5px] text-steel">
          {roleLabel}
          {scope ? ` · ${scope}` : ""}
        </div>
      </div>
      <Button size="sm" variant="ghost" onClick={signOut} loading={loading}>
        {t("ui.signOut")}
      </Button>
    </div>
  );
}
