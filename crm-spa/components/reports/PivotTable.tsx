"use client";

import type { ReactNode } from "react";
import { Table, THead, TBody } from "@/components/ui";
import { formatInt, formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useDimValue } from "./dimValue";
import { fieldLabel } from "./labels";
import type { FieldsCatalog, ResultCell, ResultColumn, ResultRow, RunResult } from "./types";

/**
 * PivotTable — «сводная как в Excel». Строит вложенные группы ИЗ ПЛОСКИХ строк,
 * которые backend вернул уже отсортированными по dims (ORDER BY dims). Порядок
 * разрезов задаёт вложенность: dims[0] — верхний уровень (строка-заголовок
 * группы), dims[последний] — листья с метриками. Смена порядка разрезов → новый
 * прогон → те же строки в другом порядке → дерево перестраивается здесь.
 *
 * Итог (totals) считает backend отдельным запросом БЕЗ группировок — поэтому он
 * корректен и для uniq-метрик (их нельзя суммировать по группам на клиенте),
 * рисуем жирной строкой сверху. Подытоги по группам НЕ считаем на клиенте по той
 * же причине — заголовок группы это ярлык уровня, а не сумма.
 */
const INDENT_BASE = 14; // px, совпадает с px-3.5 ячейки
const INDENT_STEP = 18;

interface PivotTableProps {
  result: RunResult;
  /** Ключи разрезов в порядке вложенности (ranSpec.dims). */
  dims: string[];
  /** Ключи метрик в порядке колонок (ranSpec.metrics). */
  metrics: string[];
  catalog: FieldsCatalog;
}

// Heatmap только для колонок, где ВЫШЕ = ЛУЧШЕ (конверсии/маржа, ТЗ П6 §7).
// Неоднозначные отношения (wd/dep, bonus cost) НЕ красим — цвет ввёл бы в заблуждение.
const HEATMAP_GOOD_HIGH = new Set([
  "reg_to_fd", "try_rd_to_rd", "out_conversion", "uniq_out_ratio", "margin",
]);

/** Фон ячейки-конверсии: красный (0%) → зелёный (100%), приглушённый. */
function heatBg(col: ResultColumn, raw: ResultCell): string | undefined {
  if (col.type !== "pct" || !HEATMAP_GOOD_HIGH.has(col.key)) return undefined;
  const n = typeof raw === "number" ? raw : Number(raw);
  if (Number.isNaN(n)) return undefined;
  const h = Math.max(0, Math.min(120, (Math.max(0, Math.min(100, n)) / 100) * 120));
  return `hsl(${h} 62% 90%)`;
}

function formatMetric(col: ResultColumn, raw: ResultCell, usd: boolean): string {
  if (raw == null) return "—";
  const n = typeof raw === "number" ? raw : Number(raw);
  if (Number.isNaN(n)) return String(raw);
  if (col.type === "pct") return `${n}%`;
  if (col.type === "money") return usd ? formatMoney(n).replace(" ₺", " $") : formatMoney(n);
  return formatInt(n);
}

export function PivotTable({ result, dims, metrics, catalog }: PivotTableProps) {
  const t = useT();
  const usd = result.meta.currency === "USD";
  const moneySym = usd ? "$" : "₺";
  const dimValue = useDimValue();

  const byKey = new Map(result.columns.map((c) => [c.key, c]));
  const metricCols = metrics.map((k) => byKey.get(k)).filter((c): c is ResultColumn => Boolean(c));
  const totalCols = 1 + metricCols.length;

  function metricCells(row: Record<string, ResultCell>, keyPrefix: string): ReactNode {
    return metricCols.map((c) => (
      <td
        key={`${keyPrefix}:${c.key}`}
        className="text-right px-3.5 py-[9px] border-b border-hair whitespace-nowrap font-mono tabular-nums"
        style={{ background: heatBg(c, row[c.key]) }}
      >
        {formatMetric(c, row[c.key], usd)}
      </td>
    ));
  }

  function leafRow(row: ResultRow, depth: number, keyBase: string): ReactNode {
    const dimKey = dims[depth];
    const dimDef = catalog.dimensions[dimKey];
    return (
      <tr key={keyBase} className="hover:bg-cream transition-colors">
        <td
          className="text-left px-3.5 py-[9px] border-b border-hair whitespace-nowrap"
          style={{ paddingLeft: INDENT_BASE + depth * INDENT_STEP }}
        >
          {dimDef ? dimValue(dimDef, row[dimKey]) : String(row[dimKey])}
        </td>
        {metricCells(row, keyBase)}
      </tr>
    );
  }

  function groupHeader(dimKey: string, val: ResultCell, depth: number, keyBase: string): ReactNode {
    const dimDef = catalog.dimensions[dimKey];
    return (
      <tr key={`h:${keyBase}`} className="bg-surface">
        <td
          colSpan={totalCols}
          className="text-left px-3.5 py-[7px] border-b border-hair font-semibold text-slate text-[13px]"
          style={{ paddingLeft: INDENT_BASE + depth * INDENT_STEP }}
        >
          {dimDef ? dimValue(dimDef, val) : String(val)}
        </td>
      </tr>
    );
  }

  function renderLevel(rows: ResultRow[], depth: number, keyBase: string): ReactNode[] {
    const dimKey = dims[depth];
    const isLeaf = depth === dims.length - 1;
    if (isLeaf) {
      return rows.map((row, i) => leafRow(row, depth, `${keyBase}/${String(row[dimKey])}#${i}`));
    }
    const out: ReactNode[] = [];
    let i = 0;
    while (i < rows.length) {
      const val = rows[i][dimKey];
      let j = i;
      while (j < rows.length && rows[j][dimKey] === val) j++;
      const path = `${keyBase}/${String(val)}`;
      out.push(groupHeader(dimKey, val, depth, path));
      out.push(...renderLevel(rows.slice(i, j), depth + 1, path));
      i = j;
    }
    return out;
  }

  const firstHeader = dims.length
    ? dims.map((k) => fieldLabel(t, k, catalog.dimensions[k]?.label ?? k)).join(" › ")
    : t("reports.pivot.dimsCol");

  return (
    <div className="overflow-hidden rounded-card border border-hair bg-canvas">
      <Table>
        <THead>
          <tr>
            <th className="text-left font-normal text-steel text-[11px] uppercase tracking-[0.5px] bg-surface px-3.5 py-[11px] border-b border-hair whitespace-nowrap sticky top-0">
              {firstHeader}
            </th>
            {metricCols.map((c) => (
              <th
                key={c.key}
                className="text-right font-normal text-steel text-[11px] uppercase tracking-[0.5px] bg-surface px-3.5 py-[11px] border-b border-hair whitespace-nowrap sticky top-0"
              >
                {fieldLabel(t, c.key, c.label)} <span className="text-stone">{c.type === "money" ? moneySym : c.type === "pct" ? "%" : "#"}</span>
              </th>
            ))}
          </tr>
        </THead>
        <TBody>
          {/* Итог — жирной строкой сверху (backend totals, корректно для uniq-метрик) */}
          <tr className="bg-cream font-semibold">
            <td className="text-left px-3.5 py-[10px] border-b border-hair2 text-ink">
              {t("reports.pivot.total")}
            </td>
            {metricCols.map((c) => (
              <td
                key={`total:${c.key}`}
                className="text-right px-3.5 py-[10px] border-b border-hair2 font-mono tabular-nums text-ink"
              >
                {formatMetric(c, result.totals[c.key] ?? null, usd)}
              </td>
            ))}
          </tr>

          {dims.length === 0
            ? // без разрезов — одна строка «Все данные» (равна итогу)
              (result.rows[0] ? (
                <tr className="hover:bg-cream transition-colors">
                  <td className="text-left px-3.5 py-[9px] border-b border-hair">
                    {t("reports.pivot.allData")}
                  </td>
                  {metricCells(result.rows[0], "all")}
                </tr>
              ) : null)
            : renderLevel(result.rows, 0, "r")}
        </TBody>
      </Table>
    </div>
  );
}
