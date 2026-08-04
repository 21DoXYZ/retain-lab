"use client";

import { useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";

/**
 * Бейдж свежести данных в шапке (роадмап RT-0): «данные до 15.07 20:54».
 * Известная боль: дыра потока (например, июльская) выглядит как «игрок молчит» —
 * бейдж делает границу данных видимой на каждом экране. Fail-silent: если
 * эндпоинт недоступен (нет сессии, CH лежит) — просто ничего не рендерим.
 */
interface Freshness {
  money_until: string | null;
  game_until: string | null;
}

export function DataFreshness() {
  const t = useT();
  const [f, setF] = useState<Freshness | null>(null);

  useEffect(() => {
    let alive = true;
    flaskFetch<Freshness>("/api/v1/meta/freshness")
      .then((d) => {
        if (alive) setF(d);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const until = f?.game_until ?? f?.money_until;
  if (!until) return null;
  return (
    <span
      className="hidden sm:inline-flex items-center rounded-full border border-hair2 bg-surface px-[10px] py-[4px] text-[12px] text-steel"
      title={t("ui.freshness.hint", {
        money: f?.money_until ?? "—",
        game: f?.game_until ?? "—",
      })}
    >
      {t("ui.freshness.badge", { ts: until })}
    </span>
  );
}
