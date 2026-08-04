import type { MessageKey } from "@/lib/i18n";

/** A player under the affiliate's code (crm.player_directory, RLS-scoped). */
export interface AffiliatePlayer {
  casino_player_id: number;
  display_id: string | null;
  lifecycle: string | null;
  vip_level: number | null;
  country: string | null;
  has_notes: boolean;
}

/** A note row visible to the affiliate (own + notes on their players). */
export interface AffiliateNote {
  id: string;
  casino_player_id: number;
  author_id: string;
  content: string;
  tags: string[];
  created_at: string;
}

/**
 * Minimal slice of the A3 /players/:id/summary payload the affiliate cabinet
 * uses. Deliberately excludes casino money/GGR/commissions (ТЗ п.6.1/6.5) — the
 * cabinet only surfaces stage + model signals + a masked contact for calling.
 */
export interface AffiliateSummary {
  player_id: number;
  stage: string | null;
  vip_level: number | null;
  contact: { phone: string | null } | null;
  scores: { p_churn: number | null } | null;
  recommendation: {
    action: string | null;
    offer_name: string | null;
  } | null;
}

/** Lifecycle → localized signal label + badge tint (board-style tints). */
export function lifecycleSignal(lifecycle: string | null | undefined): {
  key: MessageKey;
  bg: string;
  fg: string;
} {
  switch (lifecycle) {
    case "cooling":
      return { key: "affiliate.signal.cooling", bg: "#fff7ed", fg: "#c2410c" };
    case "at_risk":
      return { key: "affiliate.signal.atRisk", bg: "#fef2f2", fg: "#dc2626" };
    case "churned":
      return { key: "affiliate.signal.churned", bg: "#fef2f2", fg: "#b91c1c" };
    case "dormant":
      return { key: "affiliate.signal.dormant", bg: "#f1f5f9", fg: "#64748b" };
    case "active":
      return { key: "affiliate.signal.active", bg: "#ecfdf5", fg: "#1f9d57" };
    case "never":
      return { key: "affiliate.signal.new", bg: "#eff6ff", fg: "#1d4ed8" };
    default:
      return { key: "affiliate.signal.unknown", bg: "#f1f5f9", fg: "#64748b" };
  }
}
