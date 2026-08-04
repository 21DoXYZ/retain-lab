"use client";

import { useEffect, useRef } from "react";
import { createClient } from "@/lib/supabase/client";

/**
 * Subscribe to Supabase Realtime postgres_changes on one or more crm.* tables
 * and invoke `onChange` (debounced) whenever a relevant row changes — used to
 * keep the operator queue / pool live without polling (ТЗ КЦ п.2, plan §B2).
 *
 * RLS applies to Realtime too: the browser client is authenticated as the user,
 * so an operator only receives changes for rows it may see. Optional `filter`
 * (e.g. `operator_id=eq.<uuid>`) narrows the stream server-side.
 *
 * REQUIREMENT (persist in a migration — A1): the crm tables must be in the
 * `supabase_realtime` publication, e.g.
 *   ALTER PUBLICATION supabase_realtime ADD TABLE crm.player_assignments, crm.scheduled_calls;
 *   ALTER TABLE crm.player_assignments REPLICA IDENTITY FULL;
 * Without it this hook is a harmless no-op and the server-rendered data (plus
 * the manual refresh button) still keeps the screen correct.
 */

export interface RealtimeSub {
  table: string;
  /** PostgREST filter string, e.g. "operator_id=eq.<uuid>". */
  filter?: string;
  /** Schema (default "crm"). */
  schema?: string;
}

export function useRealtimeRefresh(
  subs: RealtimeSub[],
  onChange: () => void,
  { debounceMs = 400 }: { debounceMs?: number } = {},
): void {
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  // Stable key so the effect only re-subscribes when the subscriptions change.
  const key = subs
    .map((s) => `${s.schema ?? "crm"}.${s.table}:${s.filter ?? "*"}`)
    .join("|");

  useEffect(() => {
    const supabase = createClient();
    const channel = supabase.channel(`crm-rt-${key}`);
    let timer: ReturnType<typeof setTimeout> | undefined;

    const fire = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => onChangeRef.current(), debounceMs);
    };

    for (const s of subs) {
      channel.on(
        "postgres_changes",
        {
          event: "*",
          schema: s.schema ?? "crm",
          table: s.table,
          ...(s.filter ? { filter: s.filter } : {}),
        },
        fire,
      );
    }

    channel.subscribe();

    return () => {
      if (timer) clearTimeout(timer);
      supabase.removeChannel(channel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, debounceMs]);
}
