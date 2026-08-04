"use client";

import { useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";

/**
 * Retention-треугольник (Д2, разбор с Василием). Строки — когорты по неделе
 * первого депозита, столбцы — недели после неё (W0 = неделя депозита). Ячейка —
 * % когорты, вернувшейся к игре. Прежний график был одной усреднённой линией;
 * треугольник показывает, как удержание падает по каждой когорте отдельно и
 * меняется ли оно от когорты к когорте (эффект запуска чего-то нового).
 * Форма треугольная: у свежих когорт поздних недель ещё нет (клетка пустая).
 */
interface TriRow { cohort: string; size: number; cells: (number | null)[] }
interface TriData { weeks: number; rows: TriRow[]; note: string }

/** Цвет ячейки по проценту удержания: зелёный высокий → красный низкий. */
function cellStyle(v: number | null): React.CSSProperties {
  if (v == null) return { background: "transparent" };
  // 0..100 -> красный(0) .. зелёный(60+). Порог насыщенности 60% (выше — уверенно зелёный).
  const h = Math.min(v / 60, 1) * 130;            // 0=red hue .. 130=green
  const light = 92 - Math.min(v, 100) * 0.28;     // выше % — насыщеннее
  return { background: `hsl(${h}, 62%, ${light}%)` };
}

export function RetentionTriangle() {
  const t = useT();
  const [data, setData] = useState<TriData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    flaskFetch<TriData>("/api/v1/money/retention-triangle")
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e?.message ?? "error"));
    return () => { live = false; };
  }, []);

  if (error) return <p className="text-[12px] text-neg">{error}</p>;
  if (!data) return <div className="h-40 animate-pulse rounded-card bg-hair/40" />;
  if (!data.rows.length) return <p className="text-[12px] text-steel">{t("money.triangle.empty")}</p>;

  const cols = data.weeks + 1;
  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-0.5 text-[12px]">
        <thead>
          <tr className="text-steel text-[10.5px] uppercase tracking-[0.4px]">
            <th className="text-left pr-3 font-semibold">{t("money.triangle.colCohort")}</th>
            <th className="text-right pr-3 font-semibold">{t("money.triangle.colSize")}</th>
            {Array.from({ length: cols }, (_, k) => (
              <th key={k} className="px-2 text-center font-semibold">W{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.cohort}>
              <td className="pr-3 whitespace-nowrap font-medium">{row.cohort}</td>
              <td className="pr-3 text-right tabular-nums text-steel">{formatInt(row.size)}</td>
              {row.cells.map((v, k) => (
                <td
                  key={k}
                  className="px-2 py-1 text-center tabular-nums rounded-[3px] min-w-[42px]"
                  style={cellStyle(v)}
                  title={v == null ? "" : `W${k}: ${v}%`}
                >
                  {v == null ? "" : `${Math.round(v)}%`}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[12px] text-steel">{t("money.triangle.note")}</p>
    </div>
  );
}
