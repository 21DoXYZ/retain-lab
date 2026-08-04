"use client";

import { useT } from "@/lib/i18n";

/**
 * Дельта к периоду сравнения (0.2, просьба Василия «сравнение двух периодов»).
 * «▲ 12%» / «▼ 5%» с цветом по направлению. Знак «хорошо/плохо» НЕ зашиваем:
 * для депозитов рост — хорошо, для расхода на бонусы — плохо; ставить оценку
 * должен человек. Поэтому цвет нейтрально-информативный: рост зелёный, падение
 * красный, просто чтобы направление читалось с одного взгляда.
 */
export function DeltaBadge({ pct }: { pct: number | null | undefined }) {
  const t = useT();
  if (pct == null) return <span className="text-steel/70">{t("compare.noBase")}</span>;
  const up = pct > 0;
  const flat = pct === 0;
  const cls = flat ? "text-steel" : up ? "text-pos" : "text-neg";
  const arrow = flat ? "→" : up ? "▲" : "▼";
  return (
    <span className={`inline-flex items-center gap-0.5 font-semibold ${cls}`} title={t("compare.vsPrev")}>
      {arrow} {Math.abs(pct)}%
    </span>
  );
}
