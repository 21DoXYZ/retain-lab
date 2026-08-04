"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { CurrentUser } from "./types";

/**
 * Client-side role context. The protected (app) layout resolves the user on the
 * server (lib/auth.getCurrentUser) and provides it here, so every client
 * component below can read the current user + role without another round-trip.
 *
 * For B2/B3/B4/C agents (client components):
 *   import { useRole } from "@/lib/role-context";
 *   const me = useRole();               // { id, full_name, role, department, ... }
 *   if (me.role === "operator") { ... } // gate UI by role
 *
 * useRole() throws if used outside the (app) layout (i.e. no signed-in user),
 * which is the correct failure mode for protected screens. Use useMaybeRole()
 * if you need a nullable read.
 */
const RoleContext = createContext<CurrentUser | null>(null);

export function RoleProvider({
  user,
  children,
}: {
  user: CurrentUser;
  children: ReactNode;
}) {
  return <RoleContext.Provider value={user}>{children}</RoleContext.Provider>;
}

export function useRole(): CurrentUser {
  const user = useContext(RoleContext);
  if (!user) {
    throw new Error("useRole() must be used inside the (app) RoleProvider.");
  }
  return user;
}

export function useMaybeRole(): CurrentUser | null {
  return useContext(RoleContext);
}
