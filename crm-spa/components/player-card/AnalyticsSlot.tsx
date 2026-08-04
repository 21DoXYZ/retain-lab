import { PlayerAnalytics } from "@/components/player-analytics";
import type { UserRole } from "@/lib/types";

/**
 * Slot for C2's analytical card sections (money / game / pattern / trajectory /
 * session log / rhythm / LTV). C2 owns the sections as components in
 * crm-spa/components/player-analytics/ (+ api/players_analytics.py); B3 only
 * mounts the slot on the page it owns. This is the ONLY coupling point between
 * B3 and C2.
 */
export function AnalyticsSlot({ playerId, role }: { playerId: number; role: UserRole }) {
  return (
    <div data-analytics-slot data-player-id={playerId} data-role={role}>
      <PlayerAnalytics playerId={playerId} role={role} />
    </div>
  );
}
