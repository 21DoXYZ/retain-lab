import { notFound, redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { PlayerCard } from "@/components/player-card/PlayerCard";

/**
 * /players/[id] — the player card (B3 owns this page). Thin server shell: it
 * validates the session and the numeric id, then hands off to the client
 * PlayerCard, which fetches the Flask summary + Supabase crm.* rows and renders
 * the header, operational blocks (call/notes/schedule) and the C2 analytics slot.
 *
 * NAV: this route is reached from the "Игроки" list (nav key "players", href "/",
 * owned by C2). No new nav entry is declared here — the card is a detail view of
 * an existing section, not a top-level menu item.
 */
export const dynamic = "force-dynamic";

export default async function PlayerCardPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const me = await getCurrentUser();
  if (!me) redirect("/login");

  const playerId = Number(id);
  if (!Number.isInteger(playerId) || playerId <= 0) notFound();

  return <PlayerCard playerId={playerId} />;
}
