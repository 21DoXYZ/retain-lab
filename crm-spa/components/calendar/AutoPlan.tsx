"use client";

import { useEffect, useState } from "react";
import { DataTable, LifecycleBadge, Badge, type Column } from "@/components/ui";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import type { AutoPlanCandidate } from "./types";

/**
 * Auto-plan (ТЗ п.5.4): assigned players with no scheduled touch get a suggested
 * slot from their activity heatmap (A3 /players/:id/heatmap), marked "предложено
 * системой". Best-effort: if the heatmap is unavailable (no analytics data for a
 * player), we fall back to a default-slot label — the row still surfaces so the
 * operator plans it in the card (B3, single source of truth for creation).
 */

interface HeatmapResponse {
  player_id: number;
  heatmap: { dow: number[]; hour: number[]; hm: [number, number, number][] };
  stats: { peak_day: string; peak_hour: number; active_days: number };
}

interface Suggestion {
  /** Weekday index 0..6 (Mon..Sun), or null when there is no activity data. */
  dayIndex: number | null;
  hour: number | null;
}

function argmax(values: number[]): number {
  let best = 0;
  for (let i = 1; i < values.length; i += 1) {
    if (values[i] > values[best]) best = i;
  }
  return best;
}

async function suggestFor(playerId: number): Promise<Suggestion> {
  try {
    const res = await flaskFetch<HeatmapResponse>(`/api/v1/players/${playerId}/heatmap`);
    const dow = res?.heatmap?.dow ?? [];
    const hour = res?.heatmap?.hour ?? [];
    const total = dow.reduce((a, b) => a + b, 0);
    if (total <= 0) return { dayIndex: null, hour: null };
    return { dayIndex: argmax(dow), hour: argmax(hour) };
  } catch {
    return { dayIndex: null, hour: null };
  }
}

export function AutoPlan({ candidates }: { candidates: AutoPlanCandidate[] }) {
  const t = useT();
  const [loading, setLoading] = useState(candidates.length > 0);
  const [byId, setById] = useState<Record<number, Suggestion>>({});

  useEffect(() => {
    if (candidates.length === 0) {
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    Promise.all(
      candidates.map(async (c) => [c.casino_player_id, await suggestFor(c.casino_player_id)] as const),
    ).then((pairs) => {
      if (!alive) return;
      setById(Object.fromEntries(pairs));
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [candidates]);

  function slotText(playerId: number): string {
    const s = byId[playerId];
    if (loading || !s) return t("calendar.suggest.loading");
    if (s.dayIndex == null || s.hour == null) return t("calendar.suggest.fallback");
    const day = t(`day.${s.dayIndex}` as MessageKey);
    return t("calendar.suggest.activeAt", { day, hour: s.hour });
  }

  const columns: Column<AutoPlanCandidate>[] = [
    {
      key: "player",
      header: t("calendar.col.player"),
      align: "left",
      id: true,
      render: (c) => c.player?.display_id ?? `#${c.casino_player_id}`,
    },
    {
      key: "stage",
      header: t("calendar.col.stage"),
      align: "left",
      render: (c) => <LifecycleBadge stage={c.player?.lifecycle} />,
    },
    {
      key: "suggested",
      header: t("calendar.col.suggested"),
      align: "left",
      render: (c) => (
        <div className="flex items-center gap-2">
          <span className="text-slate">{slotText(c.casino_player_id)}</span>
          <Badge bg="#eff6ff" fg="#1d4ed8">
            {t("calendar.badge.system")}
          </Badge>
        </div>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={candidates}
      state={candidates.length === 0 ? "empty" : "data"}
      getRowKey={(c) => c.casino_player_id}
      getRowHref={(c) => `/players/${c.casino_player_id}`}
      emptyTitle={t("calendar.empty.autoplan.title")}
      emptyDescription={t("calendar.empty.autoplan.desc")}
    />
  );
}
