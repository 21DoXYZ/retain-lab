"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { AppShell } from "@/components/ui";
import { activeKeyForPath } from "@/components/ui/nav";
import { RoleProvider } from "@/lib/role-context";
import { LocaleSwitcher, useT } from "@/lib/i18n";
import { UserMenu } from "@/components/UserMenu";
import { DataFreshness } from "@/components/DataFreshness";
import type { CurrentUser } from "@/lib/types";

/**
 * Client chrome for the protected (app) area. The server layout resolves the
 * user and renders this once; it:
 *   - provides the user to the whole subtree via RoleProvider (useRole()),
 *   - derives the active nav key from the current pathname,
 *   - renders A2's AppShell with role-filtered navigation + a sign-out header.
 *
 * Kept minimal on purpose — screens are the children.
 */
export function AppChrome({
  user,
  children,
}: {
  user: CurrentUser;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const active = activeKeyForPath(pathname);
  const t = useT();

  return (
    <RoleProvider user={user}>
      <AppShell
        active={active}
        role={user.role}
        t={t}
        headerRight={
          <div className="flex items-center gap-3">
            <DataFreshness />
            <LocaleSwitcher />
            <UserMenu user={user} />
          </div>
        }
      >
        {children}
      </AppShell>
    </RoleProvider>
  );
}
