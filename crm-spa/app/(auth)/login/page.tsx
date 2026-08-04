"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { FormField, Input, Button } from "@/components/ui";
import { useT } from "@/lib/i18n";

/**
 * /login — email + password via Supabase Auth (signInWithPassword). On success
 * the session cookie is set and we send the user to ?next (or /), where the
 * (app) index redirects by role. Errors are surfaced inline (loading/error
 * states per plan §0.6). Design uses A2 primitives + design tokens only.
 *
 * useSearchParams needs a Suspense boundary in the App Router, hence the split.
 */
function LoginForm() {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const nextPath = params.get("next") || "/";
  const blocked = params.get("blocked") === "1";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const supabase = createClient();
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (signInError) {
      setLoading(false);
      setError(
        signInError.message === "Invalid login credentials"
          ? t("login.invalidCredentials")
          : signInError.message,
      );
      return;
    }
    // Full navigation so the server layout re-reads the fresh session cookie.
    router.replace(nextPath);
    router.refresh();
  }

  return (
    <div className="min-h-screen w-full grid place-items-center bg-appbg px-4">
      <div className="w-full max-w-[380px]">
        <div className="flex items-center gap-3 mb-6">
          <span
            className="grid place-items-center w-11 h-11 rounded-xl text-white font-extrabold text-lg flex-none"
            style={{
              background: "linear-gradient(135deg,#60a5fa,#3b82f6)",
              boxShadow: "0 8px 20px rgba(59,130,246,.25)",
            }}
          >
            R
          </span>
          <div className="leading-tight">
            <div className="text-[17px] font-bold text-ink">Retention CRM</div>
            <div className="text-[12.5px] text-steel">{t("login.tagline")}</div>
          </div>
        </div>

        <div className="bg-canvas border border-hair2 rounded-card px-6 py-6 shadow-sm">
          <div className="flex items-start justify-between gap-3 mb-1">
            <h1 className="text-[18px] font-semibold text-ink">{t("login.title")}</h1>
          </div>
          <p className="text-[13px] text-steel mb-5">{t("login.subtitle")}</p>

          {blocked ? (
            <div className="mb-4 text-[12.5px] text-neg bg-cream border border-beige rounded-ctl px-3 py-2">
              {t("login.blocked")}
            </div>
          ) : null}

          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <FormField label={t("login.emailLabel")}>
              <Input
                type="email"
                autoComplete="username"
                placeholder="operator@crm.local"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </FormField>
            <FormField label={t("login.passwordLabel")} error={error ?? undefined}>
              <Input
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </FormField>
            <Button type="submit" variant="brand" loading={loading} className="w-full mt-1">
              {t("login.submit")}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-appbg" />}>
      <LoginForm />
    </Suspense>
  );
}
