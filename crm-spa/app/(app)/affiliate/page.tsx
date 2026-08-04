import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";
import { resolveLocale } from "@/lib/i18n/server";
import { AccessDenied } from "@/components/ui";
import { AffiliateCabinet } from "./AffiliateCabinet";
import type { AffiliatePlayer } from "./types";

/**
 * /affiliate — external affiliate cabinet (ТЗ п.6). RLS (0002) already restricts
 * crm.player_directory and crm.notes to the caller's affiliate_code, so this
 * screen only ever loads the affiliate's own players. No casino money, no export,
 * no aggregate figures — just stages, model signals, a shortened card and notes.
 *
 * NOT to be confused with /affiliates (internal traffic module, C5).
 */
export default async function AffiliatePage() {
  const me = await getCurrentUser();
  if (!me) redirect("/login");

  if (me.role !== "affiliate") {
    return <AccessDenied titleKey="affiliate.title" descKey="access.affiliate.desc" />;
  }

  const locale = await resolveLocale();
  const supabase = await createClient();

  const [dirRes, notesRes] = await Promise.all([
    supabase
      .schema("crm")
      .from("player_directory")
      .select("casino_player_id, display_id, lifecycle, vip_level, country")
      .order("vip_level", { ascending: false }),
    supabase.schema("crm").from("notes").select("casino_player_id"),
  ]);

  const noteIds = new Set((notesRes.data ?? []).map((n) => n.casino_player_id as number));
  const players: AffiliatePlayer[] = (dirRes.data ?? []).map((d) => ({
    casino_player_id: d.casino_player_id as number,
    display_id: d.display_id as string | null,
    lifecycle: d.lifecycle as string | null,
    vip_level: d.vip_level as number | null,
    country: d.country as string | null,
    has_notes: noteIds.has(d.casino_player_id as number),
  }));

  return (
    <AffiliateCabinet
      locale={locale}
      code={me.affiliate_code ?? ""}
      players={players}
      error={!!dirRes.error}
    />
  );
}
